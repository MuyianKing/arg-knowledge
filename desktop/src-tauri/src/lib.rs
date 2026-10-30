use std::{
    collections::HashSet,
    env,
    fs::{self, OpenOptions},
    io::Write,
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, BufReader};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const PYTHON_PROBE: &str = r#"import json, platform, struct, sys
print(json.dumps({
    "version": platform.python_version(),
    "bits": struct.calcsize("P") * 8,
    "executable": sys.executable,
    "implementation": platform.python_implementation(),
}))"#;

const RUNTIME_PROBE: &str = r#"import json, platform, sys
result = {"python": platform.python_version(), "executable": sys.executable}
try:
    import torch
    result["torch"] = torch.__version__
    result["cuda"] = bool(torch.cuda.is_available())
    result["cuda_device"] = torch.cuda.get_device_name(0) if result["cuda"] else None
except Exception as exc:
    result["torch"] = None
    result["cuda"] = False
    result["error"] = type(exc).__name__ + ": " + str(exc)
try:
    import fastapi, qdrant_client, fastembed, FlagEmbedding
    result["deps_ok"] = True
except Exception as exc:
    result["deps_ok"] = False
    result["deps_error"] = type(exc).__name__ + ": " + str(exc)
print(json.dumps(result))"#;

const MODEL_MANIFEST: &[(&str, u64)] = &[
    ("bge-m3/config.json", 100),
    ("bge-m3/pytorch_model.bin", 2_200_000_000),
    ("bge-m3/tokenizer.json", 15_000_000),
    ("bge-m3/tokenizer_config.json", 100),
    ("bge-m3/special_tokens_map.json", 100),
    ("bge-m3/sentencepiece.bpe.model", 4_000_000),
    ("bge-m3/1_Pooling/config.json", 100),
    ("bge-m3/colbert_linear.pt", 1_000_000),
    ("bge-m3/sparse_linear.pt", 1_000),
    ("bge-reranker-v2-m3/config.json", 100),
    ("bge-reranker-v2-m3/model.safetensors", 2_200_000_000),
    ("bge-reranker-v2-m3/tokenizer.json", 15_000_000),
    ("bge-reranker-v2-m3/tokenizer_config.json", 100),
    ("bge-reranker-v2-m3/special_tokens_map.json", 100),
    ("bge-reranker-v2-m3/sentencepiece.bpe.model", 4_000_000),
    ("bm25/config.json", 1),
    ("bm25/english.txt", 100),
    ("bm25/chinese.txt", 100),
    ("bm25/stopwords.txt", 100),
];

/* ------------------------------------------------------------------ models */

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct Check {
    key: String,
    label: String,
    status: String,
    detail: String,
    required: bool,
}

impl Check {
    fn new(
        key: &str,
        label: &str,
        status: &str,
        detail: impl Into<String>,
        required: bool,
    ) -> Self {
        Self {
            key: key.to_string(),
            label: label.to_string(),
            status: status.to_string(),
            detail: detail.into(),
            required,
        }
    }
}

fn passes(checks: &[Check]) -> bool {
    checks
        .iter()
        .filter(|check| check.required)
        .all(|check| check.status != "error")
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct GpuInfo {
    name: String,
    driver: String,
    memory_mb: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SystemReport {
    os: String,
    arch: String,
    os_version: String,
    ram_total_mb: u64,
    disk_free_mb: u64,
    webview2: String,
    gpus: Vec<GpuInfo>,
    checks: Vec<Check>,
    pass: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PythonCandidate {
    command: String,
    path: String,
    version: String,
    bits: u32,
    ok: bool,
    error: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PythonReport {
    candidates: Vec<PythonCandidate>,
    selected: Option<String>,
    checks: Vec<Check>,
    pass: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeReport {
    venv_python: String,
    venv_exists: bool,
    torch: Option<String>,
    cuda: bool,
    cuda_device: Option<String>,
    deps_ok: bool,
    deps_error: Option<String>,
    checks: Vec<Check>,
    pass: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ModelIssue {
    path: String,
    size: u64,
    minimum: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ModelReport {
    model_root: String,
    checked: usize,
    total_bytes: u64,
    missing: Vec<String>,
    truncated: Vec<ModelIssue>,
    checks: Vec<Check>,
    pass: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ServiceStatus {
    qdrant_binary: Option<String>,
    qdrant_running: bool,
    qdrant_port: u16,
    engine_running: bool,
    engine_port: u16,
    engine_health: Value,
    checks: Vec<Check>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PathsInfo {
    home: String,
    engine: Option<String>,
    venv: String,
    models: String,
    logs: String,
    qdrant_storage: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConnectionReport {
    base_url: String,
    ok: bool,
    reachable: bool,
    status: Option<String>,
    ready: Option<bool>,
    warmup_ms: Option<u64>,
    latency_ms: u64,
    error: Option<String>,
    health: Value,
}

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase", default)]
struct AppSettings {
    /// Client -> engine endpoint. Independent from the local deployment settings.
    base_url: String,
    tenant_id: String,
    acl: String,
    engine_root: Option<String>,
    python_path: Option<String>,
    model_root: Option<String>,
    engine_port: u16,
    qdrant_http_port: u16,
    qdrant_grpc_port: u16,
    setup_completed: bool,
    llm_base_url: String,
    llm_model_name: String,
    llm_model_revision: String,
    llm_temperature: f64,
    llm_max_tokens: u32,
    llm_mock: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            base_url: "http://127.0.0.1:8080".to_string(),
            tenant_id: "acme".to_string(),
            acl: "internal".to_string(),
            engine_root: None,
            python_path: None,
            model_root: None,
            engine_port: 8080,
            qdrant_http_port: 6333,
            qdrant_grpc_port: 6334,
            setup_completed: false,
            llm_base_url: String::new(),
            llm_model_name: String::new(),
            llm_model_revision: String::new(),
            llm_temperature: 0.1,
            llm_max_tokens: 512,
            llm_mock: false,
        }
    }
}

#[derive(Default)]
struct AppState {
    qdrant: Mutex<Option<Child>>,
    engine: Mutex<Option<Child>>,
}

/* ----------------------------------------------------------------- helpers */

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn app_home(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(value) = env::var("APP_HOME") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    app.path()
        .local_data_dir()
        .map(|base| base.join("ARG-Knowledge"))
        .map_err(|error| format!("无法获取应用数据目录: {error}"))
}

fn ensure_layout(home: &Path) -> Result<(), String> {
    for dir in [
        home.join("runtime"),
        home.join("models"),
        home.join("logs"),
        home.join("qdrant_storage"),
        home.join("snapshots"),
        home.join("data").join("uploads"),
    ] {
        fs::create_dir_all(&dir)
            .map_err(|error| format!("创建目录失败 {}: {error}", dir.display()))?;
    }
    Ok(())
}

fn display_path(path: &Path) -> String {
    path.to_string_lossy().to_string()
}

fn normalize_base_url(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        return Err("引擎地址不能为空".to_string());
    }
    if !(trimmed.starts_with("http://") || trimmed.starts_with("https://")) {
        return Err("引擎地址必须以 http:// 或 https:// 开头".to_string());
    }
    Ok(trimmed.to_string())
}

fn is_loopback(url: &str) -> bool {
    let lower = url.to_lowercase();
    lower.contains("127.0.0.1") || lower.contains("localhost") || lower.contains("[::1]")
}

fn apply_identity(
    builder: reqwest::RequestBuilder,
    settings: &AppSettings,
) -> reqwest::RequestBuilder {
    let mut builder = builder;
    if !settings.tenant_id.trim().is_empty() {
        builder = builder.header("X-Tenant-Id", settings.tenant_id.trim());
    }
    if !settings.acl.trim().is_empty() {
        builder = builder.header("X-Acl", settings.acl.trim());
    }
    builder
}

fn engine_target(app: &AppHandle, path: &str) -> Result<(String, AppSettings), String> {
    let settings = read_settings(app);
    let base = normalize_base_url(&settings.base_url)?;
    Ok((format!("{base}{path}"), settings))
}

async fn json_response(response: reqwest::Response) -> Result<Value, String> {
    let status = response.status();
    let text = response.text().await.unwrap_or_default();
    if !status.is_success() {
        return Err(format!("HTTP {status}: {}", text.trim()));
    }
    if text.trim().is_empty() {
        return Ok(Value::Null);
    }
    serde_json::from_str(&text).map_err(|error| format!("响应不是合法 JSON: {error}"))
}

fn settings_path(home: &Path) -> PathBuf {
    home.join("settings.json")
}

fn read_settings(app: &AppHandle) -> AppSettings {
    let Ok(home) = app_home(app) else {
        return AppSettings::default();
    };
    let path = settings_path(&home);
    let mut settings: AppSettings = fs::read_to_string(&path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default();
    if !path.exists() {
        // Development launcher hint: only applies before the first save.
        if let Ok(value) = env::var("ARG_ENGINE_URL") {
            let trimmed = value.trim();
            if !trimmed.is_empty() {
                settings.base_url = trimmed.to_string();
            }
        }
    }
    settings
}

fn write_settings(app: &AppHandle, settings: &AppSettings) -> Result<(), String> {
    let home = app_home(app)?;
    ensure_layout(&home)?;
    let text = serde_json::to_string_pretty(settings).map_err(|error| error.to_string())?;
    fs::write(settings_path(&home), text).map_err(|error| format!("写入配置失败: {error}"))
}

fn resolve_engine_root(app: &AppHandle, settings: &AppSettings) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(value) = &settings.engine_root {
        if !value.trim().is_empty() {
            candidates.push(PathBuf::from(value));
        }
    }
    if let Ok(value) = env::var("ARG_ENGINE_ROOT") {
        if !value.trim().is_empty() {
            candidates.push(PathBuf::from(value));
        }
    }
    if let Ok(home) = app_home(app) {
        candidates.push(home.join("engine"));
    }
    if let Ok(resources) = app.path().resource_dir() {
        candidates.push(resources.join("engine"));
    }
    if let Ok(cwd) = env::current_dir() {
        candidates.extend(cwd.ancestors().map(Path::to_path_buf));
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.extend(dir.ancestors().map(Path::to_path_buf));
        }
    }
    let mut seen = HashSet::new();
    candidates.into_iter().find(|candidate| {
        let key = candidate.to_string_lossy().to_lowercase();
        if !seen.insert(key) {
            return false;
        }
        candidate.join("app").join("main.py").is_file()
            && candidate.join("requirements.txt").is_file()
    })
}

fn resolve_model_root(app: &AppHandle, settings: &AppSettings) -> Result<PathBuf, String> {
    if let Some(value) = &settings.model_root {
        if !value.trim().is_empty() {
            return Ok(PathBuf::from(value));
        }
    }
    if let Ok(value) = env::var("ARG_MODELS_DIR") {
        if !value.trim().is_empty() {
            return Ok(PathBuf::from(value));
        }
    }
    let home = app_home(app)?;
    let home_models = home.join("models");
    if home_models.join("bge-m3").is_dir() {
        return Ok(home_models);
    }
    if let Some(engine) = resolve_engine_root(app, settings) {
        let engine_models = engine.join("models");
        if engine_models.join("bge-m3").is_dir() {
            return Ok(engine_models);
        }
    }
    Ok(home_models)
}

fn venv_python(venv: &Path) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn venv_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(value) = env::var("ARG_VENV_DIR") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    Ok(app_home(app)?.join("runtime").join("venv"))
}

fn hide_window(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(not(windows))]
    let _ = command;
}

fn run_capture(
    program: &str,
    args: &[String],
    cwd: Option<&Path>,
    extra_env: &[(String, String)],
) -> Result<String, String> {
    let mut command = Command::new(program);
    command.args(args);
    if let Some(dir) = cwd {
        command.current_dir(dir);
    }
    for (key, value) in extra_env {
        command.env(key, value);
    }
    hide_window(&mut command);
    let output = command
        .output()
        .map_err(|error| format!("无法执行 {program}: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        let detail = if stderr.trim().is_empty() {
            stdout.trim().to_string()
        } else {
            stderr.trim().to_string()
        };
        return Err(format!(
            "{program} 退出码 {:?}: {detail}",
            output.status.code()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

fn parse_last_json(text: &str) -> Option<Value> {
    text.lines()
        .rev()
        .find_map(|line| serde_json::from_str::<Value>(line.trim()).ok())
}

fn port_open(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, Duration::from_millis(300)).is_ok()
}

fn which(name: &str) -> Option<PathBuf> {
    let path = env::var_os("PATH")?;
    for dir in env::split_paths(&path) {
        for extension in ["exe", "cmd", "bat", ""] {
            let candidate = if extension.is_empty() {
                dir.join(name)
            } else {
                dir.join(format!("{name}.{extension}"))
            };
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

fn webview2_version() -> Option<String> {
    let roots = [
        r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
        r"C:\Program Files\Microsoft\EdgeWebView\Application",
    ];
    for root in roots {
        let Ok(entries) = fs::read_dir(root) else {
            continue;
        };
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                return Some(entry.file_name().to_string_lossy().to_string());
            }
        }
    }
    None
}

fn nvidia_gpus() -> Vec<GpuInfo> {
    let output = Command::new("nvidia-smi")
        .args([
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ])
        .output();
    let Ok(output) = output else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| {
            let mut parts = line.split(',').map(str::trim);
            let name = parts.next()?.to_string();
            let driver = parts.next()?.to_string();
            let memory = parts.next().unwrap_or("0").parse::<u64>().unwrap_or(0);
            Some(GpuInfo {
                name,
                driver,
                memory_mb: memory,
            })
        })
        .collect()
}

/* ---------------------------------------------------------------- commands */

#[tauri::command]
fn paths(app: AppHandle) -> Result<PathsInfo, String> {
    let home = app_home(&app)?;
    let settings = read_settings(&app);
    let engine = resolve_engine_root(&app, &settings);
    let models = resolve_model_root(&app, &settings)?;
    Ok(PathsInfo {
        home: display_path(&home),
        engine: engine.as_deref().map(display_path),
        venv: display_path(&venv_python(&venv_dir(&app)?)),
        models: display_path(&models),
        logs: display_path(&home.join("logs")),
        qdrant_storage: display_path(&home.join("qdrant_storage")),
    })
}

#[tauri::command]
fn get_settings(app: AppHandle) -> Result<AppSettings, String> {
    Ok(read_settings(&app))
}

#[tauri::command]
fn save_settings(app: AppHandle, settings: AppSettings) -> Result<AppSettings, String> {
    write_settings(&app, &settings)?;
    Ok(settings)
}

#[tauri::command]
fn probe_system(app: AppHandle) -> Result<SystemReport, String> {
    let home = app_home(&app)?;
    let os = std::env::consts::OS.to_string();
    let arch = std::env::consts::ARCH.to_string();
    let os_version = sysinfo::System::long_os_version().unwrap_or_else(|| os.clone());

    let mut system = sysinfo::System::new();
    system.refresh_memory();
    let ram_total_mb = system.total_memory() / (1024 * 1024);

    let disks = sysinfo::Disks::new_with_refreshed_list();
    let home_key = home.to_string_lossy().to_lowercase();
    let mut disk_free: u64 = 0;
    for disk in disks.list() {
        let mount = disk.mount_point().to_string_lossy().to_lowercase();
        if home_key.starts_with(&mount) && disk.available_space() > disk_free {
            disk_free = disk.available_space();
        }
    }
    if disk_free == 0 {
        disk_free = disks
            .list()
            .iter()
            .map(|disk| disk.available_space())
            .max()
            .unwrap_or(0);
    }
    let disk_free_mb = disk_free / (1024 * 1024);

    let webview2 = webview2_version();
    let gpus = nvidia_gpus();

    let mut checks = Vec::new();
    checks.push(Check::new(
        "os",
        "操作系统",
        "ok",
        format!("{os_version} · {arch}"),
        true,
    ));

    let ram_status = if ram_total_mb >= 8192 {
        "ok"
    } else if ram_total_mb >= 6144 {
        "warn"
    } else {
        "error"
    };
    checks.push(Check::new(
        "ram",
        "内存",
        ram_status,
        format!("{ram_total_mb} MB（建议 ≥ 8192 MB）"),
        true,
    ));

    let disk_status = if disk_free_mb >= 15 * 1024 {
        "ok"
    } else if disk_free_mb >= 10 * 1024 {
        "warn"
    } else {
        "error"
    };
    checks.push(Check::new(
        "disk",
        "磁盘空间",
        disk_status,
        format!("{disk_free_mb} MB 可用（模型 + 依赖建议 ≥ 15 GB）"),
        true,
    ));

    match &webview2 {
        Some(version) => checks.push(Check::new(
            "webview2",
            "WebView2 运行时",
            "ok",
            format!("版本 {version}"),
            true,
        )),
        None => checks.push(Check::new(
            "webview2",
            "WebView2 运行时",
            "error",
            "未检测到，安装程序会提示安装 Microsoft Edge WebView2",
            true,
        )),
    }

    if gpus.is_empty() {
        checks.push(Check::new(
            "gpu",
            "GPU",
            "warn",
            "未检测到 NVIDIA GPU，将使用 CPU 推理（重排会明显变慢）",
            false,
        ));
    } else {
        for gpu in &gpus {
            let driver = gpu
                .driver
                .split('.')
                .next()
                .and_then(|v| v.parse::<u32>().ok());
            let status = if driver.unwrap_or(0) >= 560 {
                "ok"
            } else {
                "warn"
            };
            let detail = format!(
                "{} · 驱动 {} · {} MB 显存{}",
                gpu.name,
                gpu.driver,
                gpu.memory_mb,
                if status == "ok" {
                    ""
                } else {
                    "（建议升级驱动以使用 cu126）"
                }
            );
            checks.push(Check::new(
                &format!("gpu-{}", gpu.name),
                "NVIDIA GPU",
                status,
                detail,
                false,
            ));
        }
    }

    let pass = passes(&checks);
    Ok(SystemReport {
        os,
        arch,
        os_version,
        ram_total_mb,
        disk_free_mb,
        webview2: webview2.unwrap_or_else(|| "未检测到".to_string()),
        gpus,
        checks,
        pass,
    })
}

struct Runner {
    program: String,
    prefix: Vec<String>,
    label: String,
}

fn python_candidates(custom: Option<&str>) -> Vec<Runner> {
    let mut runners = Vec::new();
    if let Some(path) = custom {
        let trimmed = path.trim();
        if !trimmed.is_empty() {
            runners.push(Runner {
                program: trimmed.to_string(),
                prefix: Vec::new(),
                label: trimmed.to_string(),
            });
        }
    }
    runners.push(Runner {
        program: "py".to_string(),
        prefix: Vec::new(),
        label: "py".to_string(),
    });
    for program in [
        "python3.12",
        "python3.11",
        "python3.10",
        "python",
        "python3",
    ] {
        runners.push(Runner {
            program: program.to_string(),
            prefix: Vec::new(),
            label: program.to_string(),
        });
    }
    let mut extra = Vec::new();
    if let Ok(local) = env::var("LOCALAPPDATA") {
        for folder in ["Python312", "Python311", "Python310"] {
            extra.push(
                PathBuf::from(&local)
                    .join("Programs")
                    .join("Python")
                    .join(folder)
                    .join("python.exe"),
            );
        }
    }
    if let Ok(program_files) = env::var("ProgramFiles") {
        for folder in ["Python312", "Python311", "Python310"] {
            extra.push(
                PathBuf::from(&program_files)
                    .join(folder)
                    .join("python.exe"),
            );
        }
    }
    for folder in ["Python312", "Python311", "Python310"] {
        extra.push(PathBuf::from(format!(r"C:\{folder}\python.exe")));
    }
    for path in extra {
        if path.is_file() {
            runners.push(Runner {
                program: display_path(&path),
                prefix: Vec::new(),
                label: display_path(&path),
            });
        }
    }
    runners
}

fn python_version_supported(version: &str) -> bool {
    let mut parts = version.split('.');
    let major = parts
        .next()
        .and_then(|part| part.parse::<u32>().ok())
        .unwrap_or(0);
    let minor = parts
        .next()
        .and_then(|part| part.parse::<u32>().ok())
        .unwrap_or(0);
    major == 3 && (10..=12).contains(&minor)
}

#[tauri::command]
fn probe_python(custom_path: Option<String>) -> Result<PythonReport, String> {
    let mut candidates: Vec<PythonCandidate> = Vec::new();
    let mut seen = HashSet::new();

    for runner in python_candidates(custom_path.as_deref()) {
        let mut args = runner.prefix.clone();
        args.push("-c".to_string());
        args.push(PYTHON_PROBE.to_string());
        let result = run_capture(&runner.program, &args, None, &[]);
        let candidate = match result {
            Ok(stdout) => match parse_last_json(&stdout) {
                Some(value) => {
                    let version = value
                        .get("version")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string();
                    let bits = value.get("bits").and_then(Value::as_u64).unwrap_or(0) as u32;
                    let path = value
                        .get("executable")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string();
                    if !seen.insert(path.to_lowercase()) {
                        continue;
                    }
                    let mut issues = Vec::new();
                    if bits != 64 {
                        issues.push(format!("需要 64 位，当前 {bits} 位"));
                    }
                    if !python_version_supported(&version) {
                        issues.push(format!("版本需 3.10–3.12，当前 {version}"));
                    }
                    let ok = issues.is_empty();
                    let error = if ok { None } else { Some(issues.join("；")) };
                    PythonCandidate {
                        command: runner.label,
                        path,
                        version,
                        bits,
                        ok,
                        error,
                    }
                }
                None => PythonCandidate {
                    command: runner.label,
                    path: String::new(),
                    version: String::new(),
                    bits: 0,
                    ok: false,
                    error: Some("无法解析版本输出".to_string()),
                },
            },
            Err(error) => PythonCandidate {
                command: runner.label,
                path: String::new(),
                version: String::new(),
                bits: 0,
                ok: false,
                error: Some(error),
            },
        };
        candidates.push(candidate);
    }

    let selected_info = candidates
        .iter()
        .find(|candidate| candidate.ok)
        .map(|candidate| {
            (
                candidate.path.clone(),
                candidate.version.clone(),
                candidate.bits,
            )
        });
    let selected = selected_info.as_ref().map(|(path, _, _)| path.clone());

    let mut checks = Vec::new();
    match &selected_info {
        Some((path, version, bits)) => {
            checks.push(Check::new(
                "python",
                "Python 3.10–3.12（64 位）",
                "ok",
                format!("{path}（{version}，{bits} 位）"),
                true,
            ));
            if path.to_lowercase().contains("windowsapps") {
                checks.push(Check::new(
                    "store-alias",
                    "Store 版本拦截",
                    "warn",
                    "当前解释器位于 WindowsApps，建议安装 python.org 版本并勾选 Add to PATH",
                    false,
                ));
            }
        }
        None => checks.push(Check::new(
            "python",
            "Python 3.10–3.12（64 位）",
            "error",
            "未找到受支持的 Python。需要 64 位、版本 3.10–3.12（推荐 3.12）",
            true,
        )),
    }

    let pass = selected.is_some();
    Ok(PythonReport {
        candidates,
        selected,
        checks,
        pass,
    })
}

fn runtime_report(app: &AppHandle) -> Result<RuntimeReport, String> {
    let home = app_home(app)?;
    let settings = read_settings(app);
    let venv = venv_dir(app)?;
    let python = venv_python(&venv);
    let venv_exists = python.is_file();
    let engine = resolve_engine_root(app, &settings);
    let model_root = resolve_model_root(app, &settings)?;

    let mut torch = None;
    let mut cuda = false;
    let mut cuda_device = None;
    let mut deps_ok = false;
    let mut deps_error = None;
    let mut probe_error = None;

    if venv_exists {
        let args = vec!["-c".to_string(), RUNTIME_PROBE.to_string()];
        match run_capture(
            &display_path(&python),
            &args,
            Some(&home),
            &[
                ("APP_HOME".to_string(), display_path(&home)),
                ("PYTHONIOENCODING".to_string(), "utf-8".to_string()),
            ],
        ) {
            Ok(stdout) => {
                if let Some(value) = parse_last_json(&stdout) {
                    torch = value
                        .get("torch")
                        .and_then(Value::as_str)
                        .map(str::to_string);
                    cuda = value.get("cuda").and_then(Value::as_bool).unwrap_or(false);
                    cuda_device = value
                        .get("cuda_device")
                        .and_then(Value::as_str)
                        .map(str::to_string);
                    deps_ok = value
                        .get("deps_ok")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    deps_error = value
                        .get("deps_error")
                        .and_then(Value::as_str)
                        .map(str::to_string);
                } else {
                    probe_error = Some("无法解析运行时探测输出".to_string());
                }
            }
            Err(error) => probe_error = Some(error),
        }
    }

    let mut checks = Vec::new();
    checks.push(if venv_exists {
        Check::new("venv", "虚拟环境", "ok", display_path(&venv), true)
    } else {
        Check::new(
            "venv",
            "虚拟环境",
            "error",
            "尚未创建，点击“安装依赖”开始",
            true,
        )
    });

    match &torch {
        Some(version) => checks.push(Check::new("torch", "PyTorch", "ok", version.clone(), true)),
        None => checks.push(Check::new(
            "torch",
            "PyTorch",
            "error",
            probe_error.clone().unwrap_or_else(|| "未安装".to_string()),
            true,
        )),
    }

    checks.push(if cuda {
        Check::new(
            "cuda",
            "CUDA",
            "ok",
            cuda_device.clone().unwrap_or_else(|| "可用".to_string()),
            false,
        )
    } else {
        Check::new(
            "cuda",
            "CUDA",
            "warn",
            "不可用，将使用 CPU（重排明显变慢）",
            false,
        )
    });

    checks.push(if deps_ok {
        Check::new(
            "deps",
            "引擎依赖",
            "ok",
            "fastapi / qdrant / FlagEmbedding 可导入",
            true,
        )
    } else {
        Check::new(
            "deps",
            "引擎依赖",
            "error",
            deps_error
                .clone()
                .unwrap_or_else(|| "依赖未安装或不完整".to_string()),
            true,
        )
    });

    checks.push(match &engine {
        Some(root) => Check::new(
            "engine",
            "引擎程序文件",
            "ok",
            format!("{}（本地部署所需）", display_path(root)),
            true,
        ),
        None => Check::new(
            "engine",
            "引擎程序文件",
            "error",
            "未找到 app/main.py；本地部署需要引擎代码，连接远程引擎时不需要",
            true,
        ),
    });

    checks.push(Check::new(
        "models",
        "模型目录",
        if model_root.join("bge-m3").is_dir() {
            "ok"
        } else {
            "warn"
        },
        display_path(&model_root),
        false,
    ));

    let pass = passes(&checks);
    Ok(RuntimeReport {
        venv_python: display_path(&python),
        venv_exists,
        torch,
        cuda,
        cuda_device,
        deps_ok,
        deps_error,
        checks,
        pass,
    })
}

#[tauri::command]
fn probe_runtime(app: AppHandle) -> Result<RuntimeReport, String> {
    runtime_report(&app)
}

#[tauri::command]
fn build_model_report(root: &Path) -> ModelReport {
    let mut missing = Vec::new();
    let mut truncated = Vec::new();
    let mut total: u64 = 0;

    for (relative, minimum) in MODEL_MANIFEST {
        let path = root.join(relative);
        if !path.is_file() {
            missing.push((*relative).to_string());
            continue;
        }
        let size = path.metadata().map(|meta| meta.len()).unwrap_or(0);
        total += size;
        if size < *minimum {
            truncated.push(ModelIssue {
                path: (*relative).to_string(),
                size,
                minimum: *minimum,
            });
        }
    }

    let mut checks = Vec::new();
    checks.push(Check::new(
        "root",
        "模型目录",
        if root.is_dir() { "ok" } else { "error" },
        display_path(root),
        true,
    ));

    if missing.is_empty() && truncated.is_empty() {
        checks.push(Check::new(
            "files",
            "文件完整性",
            "ok",
            format!(
                "{} 个文件，共 {:.2} GiB",
                MODEL_MANIFEST.len(),
                total as f64 / 1024f64.powi(3)
            ),
            true,
        ));
    } else {
        checks.push(Check::new(
            "files",
            "文件完整性",
            "error",
            format!("缺少 {} 个文件，异常 {} 个", missing.len(), truncated.len()),
            true,
        ));
    }

    let pass = missing.is_empty() && truncated.is_empty();
    ModelReport {
        model_root: display_path(root),
        checked: MODEL_MANIFEST.len(),
        total_bytes: total,
        missing,
        truncated,
        checks,
        pass,
    }
}

#[tauri::command]
fn probe_models(app: AppHandle) -> Result<ModelReport, String> {
    let settings = read_settings(&app);
    let root = resolve_model_root(&app, &settings)?;
    Ok(build_model_report(&root))
}

fn resolve_qdrant_binary(app: &AppHandle, settings: &AppSettings) -> Option<String> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(value) = env::var("ARG_QDRANT_BIN") {
        if !value.trim().is_empty() {
            candidates.push(PathBuf::from(value));
        }
    }
    if let Ok(home) = app_home(app) {
        candidates.push(home.join("bin").join("qdrant.exe"));
    }
    if let Some(engine) = resolve_engine_root(app, settings) {
        candidates.push(engine.join("tools").join("qdrant").join("qdrant.exe"));
    }
    if let Ok(resources) = app.path().resource_dir() {
        candidates.push(resources.join("qdrant").join("qdrant.exe"));
        candidates.push(
            resources
                .join("resources")
                .join("qdrant")
                .join("qdrant.exe"),
        );
    }
    if let Some(path) = candidates.into_iter().find(|path| path.is_file()) {
        return Some(display_path(&path));
    }
    which("qdrant").map(|path| display_path(&path))
}

fn child_alive(slot: &Mutex<Option<Child>>) -> bool {
    let mut guard = lock(slot);
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(Some(_)) => {
                *guard = None;
                false
            }
            Ok(None) => true,
            Err(_) => false,
        },
        None => false,
    }
}

fn spawn_logged(
    program: &str,
    args: &[String],
    cwd: Option<&Path>,
    envs: &[(String, String)],
    log_path: &Path,
    header: &str,
) -> Result<Child, String> {
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("创建日志目录失败 {}: {error}", parent.display()))?;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .map_err(|error| format!("打开日志失败 {}: {error}", log_path.display()))?;
    let _ = writeln!(file, "\n===== {header} =====");
    let mut command = Command::new(program);
    command.args(args);
    if let Some(dir) = cwd {
        command.current_dir(dir);
    }
    for (key, value) in envs {
        command.env(key, value);
    }
    command
        .stdout(Stdio::from(
            file.try_clone()
                .map_err(|error| format!("复制日志句柄失败: {error}"))?,
        ))
        .stderr(Stdio::from(file));
    hide_window(&mut command);
    command
        .spawn()
        .map_err(|error| format!("启动 {program} 失败: {error}"))
}

fn quick_status(app: &AppHandle, state: &AppState) -> ServiceStatus {
    let settings = read_settings(app);
    let qdrant_running = child_alive(&state.qdrant) || port_open(settings.qdrant_http_port);
    ServiceStatus {
        qdrant_binary: resolve_qdrant_binary(app, &settings),
        qdrant_running,
        qdrant_port: settings.qdrant_http_port,
        engine_running: child_alive(&state.engine),
        engine_port: settings.engine_port,
        engine_health: Value::Null,
        checks: Vec::new(),
    }
}

#[tauri::command]
fn start_qdrant(app: AppHandle, state: State<'_, AppState>) -> Result<ServiceStatus, String> {
    let settings = read_settings(&app);
    if child_alive(&state.qdrant) || port_open(settings.qdrant_http_port) {
        return Ok(quick_status(&app, &state));
    }
    let binary = resolve_qdrant_binary(&app, &settings).ok_or_else(|| {
        "未找到 qdrant.exe。请把 qdrant 放到应用资源目录或 tools/qdrant/ 下。".to_string()
    })?;
    let home = app_home(&app)?;
    ensure_layout(&home)?;
    let log_path = home.join("logs").join("qdrant.log");
    let envs = vec![
        (
            "QDRANT__STORAGE__STORAGE_PATH".to_string(),
            display_path(&home.join("qdrant_storage")),
        ),
        (
            "QDRANT__STORAGE__SNAPSHOTS_PATH".to_string(),
            display_path(&home.join("snapshots")),
        ),
        // Qdrant defaults to 0.0.0.0; a local deployment must stay on loopback.
        ("QDRANT__SERVICE__HOST".to_string(), "127.0.0.1".to_string()),
        (
            "QDRANT__SERVICE__HTTP_PORT".to_string(),
            settings.qdrant_http_port.to_string(),
        ),
        (
            "QDRANT__SERVICE__GRPC_PORT".to_string(),
            settings.qdrant_grpc_port.to_string(),
        ),
        (
            "QDRANT__SERVICE__ENABLE_CORS".to_string(),
            "false".to_string(),
        ),
        ("QDRANT__TELEMETRY_DISABLED".to_string(), "true".to_string()),
    ];
    let child = spawn_logged(&binary, &[], Some(&home), &envs, &log_path, "qdrant")?;
    *lock(&state.qdrant) = Some(child);
    Ok(quick_status(&app, &state))
}

#[tauri::command]
fn init_collection(app: AppHandle) -> Result<String, String> {
    let home = app_home(&app)?;
    let settings = read_settings(&app);
    let engine = resolve_engine_root(&app, &settings)
        .ok_or_else(|| "未找到引擎源码（app/main.py）。".to_string())?;
    let python = venv_python(&venv_dir(&app)?);
    if !python.is_file() {
        return Err("虚拟环境尚未创建，请先完成“依赖”步骤。".to_string());
    }
    if !port_open(settings.qdrant_http_port) {
        return Err(format!(
            "Qdrant 未启动（127.0.0.1:{}）。",
            settings.qdrant_http_port
        ));
    }
    let envs = vec![
        ("APP_HOME".to_string(), display_path(&home)),
        (
            "QDRANT_URL".to_string(),
            format!("http://127.0.0.1:{}", settings.qdrant_http_port),
        ),
        ("PYTHONIOENCODING".to_string(), "utf-8".to_string()),
        ("PYTHONDONTWRITEBYTECODE".to_string(), "1".to_string()),
    ];
    let output = run_capture(
        &display_path(&python),
        &["scripts/create_collection.py".to_string()],
        Some(&engine),
        &envs,
    )?;
    Ok(output.trim().to_string())
}

#[tauri::command]
fn start_engine(app: AppHandle, state: State<'_, AppState>) -> Result<ServiceStatus, String> {
    let settings = read_settings(&app);
    if child_alive(&state.engine) || port_open(settings.engine_port) {
        // The engine is a standalone service: an instance started in an earlier
        // session (or by the user) is adopted instead of spawning a duplicate.
        return Ok(quick_status(&app, &state));
    }
    let home = app_home(&app)?;
    ensure_layout(&home)?;
    let venv = venv_dir(&app)?;
    let python = venv_python(&venv);
    if !python.is_file() {
        return Err("虚拟环境尚未创建，请先完成“依赖”步骤。".to_string());
    }
    let engine = resolve_engine_root(&app, &settings)
        .ok_or_else(|| "未找到引擎源码（app/main.py）。".to_string())?;
    let model_root = resolve_model_root(&app, &settings)?;
    let log_path = home.join("logs").join("engine.log");

    let mut envs = vec![
        ("APP_HOME".to_string(), display_path(&home)),
        ("WARMUP_ON_STARTUP".to_string(), "true".to_string()),
        ("CACHE_ENABLED".to_string(), "false".to_string()),
        ("DEV_TOOLS_ENABLED".to_string(), "true".to_string()),
        ("PYTHONUNBUFFERED".to_string(), "1".to_string()),
        ("PYTHONIOENCODING".to_string(), "utf-8".to_string()),
        ("PYTHONDONTWRITEBYTECODE".to_string(), "1".to_string()),
        (
            "QDRANT_URL".to_string(),
            format!("http://127.0.0.1:{}", settings.qdrant_http_port),
        ),
        (
            "BGE_M3_PATH".to_string(),
            display_path(&model_root.join("bge-m3")),
        ),
        (
            "BGE_RERANKER_PATH".to_string(),
            display_path(&model_root.join("bge-reranker-v2-m3")),
        ),
        (
            "BM25_MODEL_PATH".to_string(),
            display_path(&model_root.join("bm25")),
        ),
    ];
    if !settings.llm_base_url.trim().is_empty() {
        envs.push((
            "LLM_BASE_URL".to_string(),
            settings.llm_base_url.trim().to_string(),
        ));
    }
    if !settings.llm_model_name.trim().is_empty() {
        envs.push((
            "LLM_MODEL_NAME".to_string(),
            settings.llm_model_name.trim().to_string(),
        ));
    }
    if !settings.llm_model_revision.trim().is_empty() {
        envs.push((
            "LLM_MODEL_REVISION".to_string(),
            settings.llm_model_revision.trim().to_string(),
        ));
    }
    envs.push((
        "LLM_TEMPERATURE".to_string(),
        settings.llm_temperature.to_string(),
    ));
    envs.push((
        "LLM_MAX_TOKENS".to_string(),
        settings.llm_max_tokens.to_string(),
    ));
    envs.push((
        "LLM_MOCK".to_string(),
        if settings.llm_mock { "true" } else { "false" }.to_string(),
    ));
    if let Some(key) = read_llm_key() {
        envs.push(("LLM_API_KEY".to_string(), key));
    }
    if let Ok(value) = env::var("LLM_MOCK") {
        envs.push(("LLM_MOCK".to_string(), value));
    }

    let args = vec![
        "-m".to_string(),
        "uvicorn".to_string(),
        "app.main:app".to_string(),
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        settings.engine_port.to_string(),
    ];
    let child = spawn_logged(
        &display_path(&python),
        &args,
        Some(&engine),
        &envs,
        &log_path,
        "engine",
    )?;
    *lock(&state.engine) = Some(child);
    Ok(quick_status(&app, &state))
}

#[tauri::command]
fn stop_service(
    app: AppHandle,
    state: State<'_, AppState>,
    service: String,
) -> Result<ServiceStatus, String> {
    let settings = read_settings(&app);
    let (slot, port) = match service.as_str() {
        "engine" => (&state.engine, settings.engine_port),
        "qdrant" => (&state.qdrant, settings.qdrant_http_port),
        other => return Err(format!("未知服务: {other}")),
    };
    let mut stopped = false;
    if let Some(mut child) = lock(slot).take() {
        let _ = child.kill();
        let _ = child.wait();
        stopped = true;
    }
    if !stopped && port_open(port) {
        return Err(format!(
            "{service} 不是本次会话启动的进程（端口 {port} 仍在监听），请在部署助手外停止。"
        ));
    }
    Ok(quick_status(&app, &state))
}

#[tauri::command]
fn read_log_tail(app: AppHandle, service: String, lines: Option<usize>) -> Result<String, String> {
    let name = match service.as_str() {
        "engine" => "engine.log",
        "qdrant" => "qdrant.log",
        other => return Err(format!("未知服务: {other}")),
    };
    let home = app_home(&app)?;
    let path = home.join("logs").join(name);
    let Ok(text) = fs::read_to_string(&path) else {
        return Ok(String::new());
    };
    let limit = lines.unwrap_or(80).max(1);
    let collected: Vec<&str> = text.lines().rev().take(limit).collect();
    let mut output: Vec<&str> = collected.into_iter().rev().collect();
    while output.first().is_some_and(|line| line.is_empty()) {
        output.remove(0);
    }
    Ok(output.join("\n"))
}

#[tauri::command]
async fn probe_connection(
    app: AppHandle,
    base_url: Option<String>,
    tenant_id: Option<String>,
    acl: Option<String>,
) -> Result<ConnectionReport, String> {
    let settings = read_settings(&app);
    let url = normalize_base_url(base_url.as_deref().unwrap_or(&settings.base_url))?;
    let tenant = tenant_id.unwrap_or_else(|| settings.tenant_id.clone());
    let acl = acl.unwrap_or_else(|| settings.acl.clone());
    let target = format!("{url}/health");

    let mut request = reqwest::Client::new()
        .get(&target)
        .timeout(Duration::from_secs(3));
    if !tenant.trim().is_empty() {
        request = request.header("X-Tenant-Id", tenant);
    }
    if !acl.trim().is_empty() {
        request = request.header("X-Acl", acl);
    }

    let started = Instant::now();
    match request.send().await {
        Ok(response) => {
            let latency_ms = started.elapsed().as_millis() as u64;
            let status_code = response.status();
            if !status_code.is_success() {
                return Ok(ConnectionReport {
                    base_url: url,
                    ok: false,
                    reachable: true,
                    status: None,
                    ready: None,
                    warmup_ms: None,
                    latency_ms,
                    error: Some(format!("HTTP {status_code}")),
                    health: Value::Null,
                });
            }
            match response.json::<Value>().await {
                Ok(health) => {
                    let status = health
                        .get("status")
                        .and_then(Value::as_str)
                        .map(str::to_string);
                    let ready = health.get("ready").and_then(Value::as_bool);
                    let warmup_ms = health.get("warmup_ms").and_then(Value::as_u64);
                    Ok(ConnectionReport {
                        base_url: url,
                        ok: true,
                        reachable: true,
                        status,
                        ready,
                        warmup_ms,
                        latency_ms,
                        error: None,
                        health,
                    })
                }
                Err(error) => Ok(ConnectionReport {
                    base_url: url,
                    ok: false,
                    reachable: true,
                    status: None,
                    ready: None,
                    warmup_ms: None,
                    latency_ms,
                    error: Some(format!("响应不是合法 JSON: {error}")),
                    health: Value::Null,
                }),
            }
        }
        Err(error) => Ok(ConnectionReport {
            base_url: url,
            ok: false,
            reachable: false,
            status: None,
            ready: None,
            warmup_ms: None,
            latency_ms: started.elapsed().as_millis() as u64,
            error: Some(error.to_string()),
            health: Value::Null,
        }),
    }
}

#[tauri::command]
async fn engine_health(app: AppHandle) -> Result<Value, String> {
    let settings = read_settings(&app);
    let url = normalize_base_url(&settings.base_url)?;
    let mut request = reqwest::Client::new()
        .get(format!("{url}/health"))
        .timeout(Duration::from_secs(3));
    if !settings.tenant_id.trim().is_empty() {
        request = request.header("X-Tenant-Id", settings.tenant_id);
    }
    if !settings.acl.trim().is_empty() {
        request = request.header("X-Acl", settings.acl);
    }
    let response = request
        .send()
        .await
        .map_err(|error| format!("引擎不可达: {error}"))?;
    if !response.status().is_success() {
        return Err(format!("引擎返回 HTTP {}", response.status()));
    }
    response
        .json::<Value>()
        .await
        .map_err(|error| format!("解析健康响应失败: {error}"))
}

#[tauri::command]
async fn probe_services(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<ServiceStatus, String> {
    let settings = read_settings(&app);
    let qdrant_binary = resolve_qdrant_binary(&app, &settings);
    let qdrant_running = child_alive(&state.qdrant) || port_open(settings.qdrant_http_port);
    let engine_running = child_alive(&state.engine) || port_open(settings.engine_port);

    let mut health = Value::Null;
    if port_open(settings.engine_port) {
        let url = format!("http://127.0.0.1:{}/health", settings.engine_port);
        if let Ok(response) = reqwest::Client::new()
            .get(&url)
            .timeout(Duration::from_secs(2))
            .send()
            .await
        {
            if let Ok(value) = response.json::<Value>().await {
                health = value;
            }
        }
    }

    let mut checks = Vec::new();
    checks.push(match &qdrant_binary {
        Some(path) => Check::new("qdrant-bin", "Qdrant 可执行文件", "ok", path, true),
        None if qdrant_running => Check::new(
            "qdrant-bin",
            "Qdrant 可执行文件",
            "ok",
            "使用外部 Qdrant 实例",
            true,
        ),
        None => Check::new(
            "qdrant-bin",
            "Qdrant 可执行文件",
            "error",
            "未找到 qdrant.exe",
            true,
        ),
    });
    checks.push(Check::new(
        "qdrant-port",
        "Qdrant 端口",
        if qdrant_running { "ok" } else { "error" },
        format!("127.0.0.1:{}", settings.qdrant_http_port),
        true,
    ));
    checks.push(Check::new(
        "engine",
        "引擎进程",
        if engine_running { "ok" } else { "error" },
        format!("127.0.0.1:{}", settings.engine_port),
        true,
    ));

    if health.is_null() {
        checks.push(Check::new(
            "engine-health",
            "引擎健康检查",
            if engine_running { "warn" } else { "error" },
            if engine_running {
                "引擎启动中，模型预热完成前 /health 不可用"
            } else {
                "引擎未启动"
            },
            false,
        ));
    } else {
        let ready = health
            .get("ready")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let warmup = health.get("warmup_ms").and_then(Value::as_u64);
        checks.push(Check::new(
            "engine-health",
            "引擎健康检查",
            if ready { "ok" } else { "warn" },
            if ready {
                warmup
                    .map(|ms| format!("模型已预热（{ms} ms）"))
                    .unwrap_or_else(|| "模型已预热".to_string())
            } else {
                "服务在线，模型尚未加载".to_string()
            },
            false,
        ));
    }

    Ok(ServiceStatus {
        qdrant_binary,
        qdrant_running,
        qdrant_port: settings.qdrant_http_port,
        engine_running,
        engine_port: settings.engine_port,
        engine_health: health,
        checks,
    })
}

/* --------------------------------------------------------------- engine API */

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_')
}

#[tauri::command]
async fn ask_engine(
    app: AppHandle,
    query: String,
    top_k: Option<u32>,
    use_cache: Option<bool>,
    filters: Option<Value>,
) -> Result<Value, String> {
    let query = query.trim().to_string();
    if query.is_empty() {
        return Err("问题不能为空".to_string());
    }
    let (url, settings) = engine_target(&app, "/api/v1/ask")?;
    let body = json!({
        "query": query,
        "top_k": top_k,
        "use_cache": use_cache.unwrap_or(true),
        "filters": filters,
    });
    let response = apply_identity(
        reqwest::Client::new()
            .post(url)
            .timeout(Duration::from_secs(120))
            .json(&body),
        &settings,
    )
    .send()
    .await
    .map_err(|error| format!("请求失败: {error}"))?;
    json_response(response).await
}

#[tauri::command]
async fn submit_ingest(
    app: AppHandle,
    file_path: String,
    version: String,
    doc_type: String,
    effective_date: Option<String>,
) -> Result<Value, String> {
    let path = PathBuf::from(file_path.trim());
    if !path.is_file() {
        return Err(format!("文件不存在: {}", path.display()));
    }
    let filename = path
        .file_name()
        .map(|name| name.to_string_lossy().to_string())
        .ok_or_else(|| "非法文件名".to_string())?;
    let bytes = tokio::fs::read(&path)
        .await
        .map_err(|error| format!("读取文件失败: {error}"))?;
    if bytes.len() > 512 * 1024 * 1024 {
        return Err("文件超过 512 MB".to_string());
    }

    let part = reqwest::multipart::Part::bytes(bytes).file_name(filename);
    let mut form = reqwest::multipart::Form::new()
        .part("file", part)
        .text("version", version)
        .text("doc_type", doc_type);
    if let Some(date) = effective_date {
        let trimmed = date.trim().to_string();
        if !trimmed.is_empty() {
            form = form.text("effective_date", trimmed);
        }
    }

    let (url, settings) = engine_target(&app, "/api/v1/ingest")?;
    let response = apply_identity(
        reqwest::Client::new()
            .post(url)
            .timeout(Duration::from_secs(600))
            .multipart(form),
        &settings,
    )
    .send()
    .await
    .map_err(|error| format!("上传失败: {error}"))?;
    json_response(response).await
}

#[tauri::command]
async fn list_jobs(app: AppHandle, limit: Option<u32>) -> Result<Value, String> {
    let limit = limit.unwrap_or(20).clamp(1, 100);
    let (url, settings) = engine_target(&app, &format!("/api/v1/jobs?limit={limit}"))?;
    let response = apply_identity(
        reqwest::Client::new()
            .get(url)
            .timeout(Duration::from_secs(10)),
        &settings,
    )
    .send()
    .await
    .map_err(|error| format!("请求失败: {error}"))?;
    json_response(response).await
}

#[tauri::command]
async fn get_job(app: AppHandle, job_id: String) -> Result<Value, String> {
    let job_id = job_id.trim();
    if !valid_identifier(job_id) {
        return Err("非法 job_id".to_string());
    }
    let (url, settings) = engine_target(&app, &format!("/api/v1/jobs/{job_id}"))?;
    let response = apply_identity(
        reqwest::Client::new()
            .get(url)
            .timeout(Duration::from_secs(10)),
        &settings,
    )
    .send()
    .await
    .map_err(|error| format!("请求失败: {error}"))?;
    json_response(response).await
}

#[tauri::command]
async fn list_documents(app: AppHandle, max_points: Option<u32>) -> Result<Value, String> {
    let max_points = max_points.unwrap_or(5000).clamp(1, 50000);
    let (url, settings) =
        engine_target(&app, &format!("/api/v1/documents?max_points={max_points}"))?;
    let response = apply_identity(
        reqwest::Client::new()
            .get(url)
            .timeout(Duration::from_secs(30)),
        &settings,
    )
    .send()
    .await
    .map_err(|error| format!("请求失败: {error}"))?;
    json_response(response).await
}

#[tauri::command]
async fn delete_document(app: AppHandle, doc_id: String) -> Result<Value, String> {
    let doc_id = doc_id.trim();
    if !valid_identifier(doc_id) {
        return Err("非法 doc_id".to_string());
    }
    let (url, settings) = engine_target(&app, &format!("/api/v1/documents/{doc_id}"))?;
    let response = apply_identity(
        reqwest::Client::new()
            .delete(url)
            .timeout(Duration::from_secs(30)),
        &settings,
    )
    .send()
    .await
    .map_err(|error| format!("请求失败: {error}"))?;
    json_response(response).await
}

/* -------------------------------------------------------------------- LLM */

const KEYRING_SERVICE: &str = "arg-knowledge-desktop";
const KEYRING_USER: &str = "llm-api-key";

fn read_llm_key() -> Option<String> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .ok()?
        .get_password()
        .ok()
        .filter(|value| !value.trim().is_empty())
}

fn write_llm_key(key: &str) -> Result<(), String> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|error| format!("凭据管理器不可用: {error}"))?
        .set_password(key)
        .map_err(|error| format!("保存 API Key 失败: {error}"))
}

fn delete_llm_key() -> Result<(), String> {
    let entry = keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|error| format!("凭据管理器不可用: {error}"))?;
    match entry.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(error) => Err(format!("删除 API Key 失败: {error}")),
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LlmSettingsView {
    base_url: String,
    model_name: String,
    model_revision: String,
    temperature: f64,
    max_tokens: u32,
    mock: bool,
    api_key_set: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct LlmSettingsUpdate {
    base_url: String,
    model_name: String,
    model_revision: Option<String>,
    temperature: f64,
    max_tokens: u32,
    mock: bool,
    api_key: Option<String>,
    clear_key: bool,
}

fn llm_view(settings: &AppSettings) -> LlmSettingsView {
    LlmSettingsView {
        base_url: settings.llm_base_url.clone(),
        model_name: settings.llm_model_name.clone(),
        model_revision: settings.llm_model_revision.clone(),
        temperature: settings.llm_temperature,
        max_tokens: settings.llm_max_tokens,
        mock: settings.llm_mock,
        api_key_set: read_llm_key().is_some(),
    }
}

#[tauri::command]
fn get_llm_settings(app: AppHandle) -> Result<LlmSettingsView, String> {
    Ok(llm_view(&read_settings(&app)))
}

#[tauri::command]
async fn save_llm_settings(
    app: AppHandle,
    settings: LlmSettingsUpdate,
) -> Result<LlmSettingsView, String> {
    let mut current = read_settings(&app);
    current.llm_base_url = settings.base_url.trim().to_string();
    current.llm_model_name = settings.model_name.trim().to_string();
    current.llm_model_revision = settings
        .model_revision
        .unwrap_or_default()
        .trim()
        .to_string();
    current.llm_temperature = settings.temperature.clamp(0.0, 2.0);
    current.llm_max_tokens = settings.max_tokens.clamp(1, 32768);
    current.llm_mock = settings.mock;
    write_settings(&app, &current)?;

    let new_key = settings
        .api_key
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    if settings.clear_key {
        delete_llm_key()?;
    } else if let Some(key) = new_key.as_deref() {
        write_llm_key(key)?;
    }

    // Apply to a running local engine immediately. Never send the key to a
    // remote endpoint over this path; the engine loads it at startup instead.
    if is_loopback(&current.base_url) && port_open(current.engine_port) {
        if let Ok(base) = normalize_base_url(&current.base_url) {
            let mut body = json!({
                "base_url": current.llm_base_url,
                "model_name": current.llm_model_name,
                "model_revision": current.llm_model_revision,
                "temperature": current.llm_temperature,
                "max_tokens": current.llm_max_tokens,
                "mock": current.llm_mock,
            });
            if let Some(key) = new_key.as_deref() {
                body["api_key"] = json!(key);
            }
            let _ = reqwest::Client::new()
                .put(format!("{base}/api/v1/dev/llm"))
                .json(&body)
                .timeout(Duration::from_secs(5))
                .send()
                .await;
        }
    }

    Ok(llm_view(&current))
}

#[tauri::command]
async fn test_llm(app: AppHandle) -> Result<Value, String> {
    let (url, settings) = engine_target(&app, "/api/v1/dev/llm/test")?;
    let response = apply_identity(
        reqwest::Client::new()
            .post(url)
            .timeout(Duration::from_secs(30)),
        &settings,
    )
    .send()
    .await
    .map_err(|error| format!("请求失败: {error}"))?;
    json_response(response).await
}

/* -------------------------------------------------------------- installer */

fn emit_log(app: &AppHandle, step: &str, line: impl Into<String>) {
    let _ = app.emit("setup-log", json!({ "step": step, "line": line.into() }));
}

async fn run_stream(
    app: &AppHandle,
    step: &str,
    program: &str,
    args: &[String],
    cwd: Option<&Path>,
) -> Result<(), String> {
    emit_log(app, step, format!("$ {program} {}", args.join(" ")));
    let mut command = tokio::process::Command::new(program);
    command.args(args);
    if let Some(dir) = cwd {
        command.current_dir(dir);
    }
    command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .stdin(Stdio::null());
    #[cfg(windows)]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("无法启动 {program}: {error}"))?;

    let stdout = child.stdout.take().ok_or("无法读取子进程输出")?;
    let stderr = child.stderr.take().ok_or("无法读取子进程错误")?;

    let app_out = app.clone();
    let step_out = step.to_string();
    let out_task = tokio::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            emit_log(&app_out, &step_out, line);
        }
    });
    let app_err = app.clone();
    let step_err = step.to_string();
    let err_task = tokio::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            emit_log(&app_err, &step_err, format!("stderr: {line}"));
        }
    });

    let status = child
        .wait()
        .await
        .map_err(|error| format!("等待 {program} 结束失败: {error}"))?;
    let _ = out_task.await;
    let _ = err_task.await;

    if !status.success() {
        return Err(format!(
            "{step} 失败，退出码 {:?}。请查看安装日志。",
            status.code()
        ));
    }
    Ok(())
}

#[tauri::command]
async fn install_runtime(
    app: AppHandle,
    python_path: String,
    torch_profile: String,
    index_url: Option<String>,
) -> Result<RuntimeReport, String> {
    let python = PathBuf::from(python_path.trim());
    if !python.is_file() {
        return Err(format!("Python 解释器不存在: {}", python.display()));
    }
    let home = app_home(&app)?;
    ensure_layout(&home)?;
    let engine = resolve_engine_root(&app, &read_settings(&app))
        .ok_or_else(|| "未找到引擎源码（app/main.py）。".to_string())?;

    let uv = if let Ok(value) = env::var("ARG_UV_BIN") {
        PathBuf::from(value)
    } else if home.join("bin").join("uv.exe").is_file() {
        home.join("bin").join("uv.exe")
    } else if let Some(path) = app.path().resource_dir().ok().and_then(|resources| {
        [
            resources.join("bin").join("uv.exe"),
            resources.join("resources").join("bin").join("uv.exe"),
        ]
        .into_iter()
        .find(|candidate| candidate.is_file())
    }) {
        path
    } else {
        which("uv").ok_or_else(|| {
            "未找到 uv.exe。请把 uv 放到应用资源 bin/ 目录，或安装到 PATH。".to_string()
        })?
    };
    let uv = display_path(&uv);

    let venv = venv_dir(&app)?;
    let venv_py = venv_python(&venv);
    let venv_arg = display_path(&venv);

    emit_log(&app, "venv", format!("使用 Python: {}", python.display()));
    run_stream(
        &app,
        "venv",
        &uv,
        &[
            "venv".to_string(),
            "--python".to_string(),
            display_path(&python),
            venv_arg.clone(),
        ],
        None,
    )
    .await?;

    let venv_py_arg = display_path(&venv_py);
    let mut torch_args = vec![
        "pip".to_string(),
        "install".to_string(),
        "--python".to_string(),
        venv_py_arg.clone(),
    ];
    if torch_profile == "cpu" {
        torch_args.push("torch".to_string());
    } else {
        torch_args.extend([
            "--index-url".to_string(),
            "https://download.pytorch.org/whl/cu126".to_string(),
            "torch".to_string(),
        ]);
    }
    run_stream(&app, "torch", &uv, &torch_args, None).await?;

    let mut deps_args = vec![
        "pip".to_string(),
        "install".to_string(),
        "--python".to_string(),
        venv_py_arg,
        "-r".to_string(),
        display_path(&engine.join("requirements.txt")),
    ];
    if let Some(mirror) = index_url {
        let trimmed = mirror.trim();
        if !trimmed.is_empty() {
            deps_args.extend(["--index-url".to_string(), trimmed.to_string()]);
        }
    }
    run_stream(&app, "deps", &uv, &deps_args, None).await?;

    let marker = json!({
        "python": display_path(&python),
        "torchProfile": torch_profile,
        "engine": display_path(&engine),
        "installedAt": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_secs())
            .unwrap_or(0),
    });
    fs::write(
        home.join("runtime").join("runtime.json"),
        serde_json::to_string_pretty(&marker).map_err(|error| error.to_string())?,
    )
    .map_err(|error| format!("写入运行时标记失败: {error}"))?;

    emit_log(&app, "deps", "依赖安装完成");
    runtime_report(&app)
}

/* ------------------------------------------------------------------- models */

#[tauri::command]
async fn download_models(app: AppHandle, mirror: Option<String>) -> Result<ModelReport, String> {
    let home = app_home(&app)?;
    ensure_layout(&home)?;
    let engine = resolve_engine_root(&app, &read_settings(&app))
        .ok_or_else(|| "未找到引擎源码（app/main.py）。".to_string())?;
    let python = venv_python(&venv_dir(&app)?);
    if !python.is_file() {
        return Err("虚拟环境尚未创建，请先完成“依赖”步骤。".to_string());
    }
    let script = engine.join("scripts").join("download_models.py");
    if !script.is_file() {
        return Err(format!("未找到下载脚本: {}", script.display()));
    }

    let models = home.join("models");
    let mut args = vec!["--models-dir".to_string(), display_path(&models)];
    if let Some(value) = mirror {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            args.push("--mirror".to_string());
            args.push(trimmed.to_string());
        }
    }
    run_stream(&app, "models", &display_path(&python), &args, Some(&engine)).await?;

    let mut settings = read_settings(&app);
    settings.model_root = None;
    write_settings(&app, &settings)?;
    probe_models(app)
}

#[tauri::command]
fn import_models(app: AppHandle, source: String) -> Result<ModelReport, String> {
    let root = PathBuf::from(source.trim());
    if !root.is_dir() {
        return Err(format!("模型目录不存在: {}", root.display()));
    }
    let report = build_model_report(&root);
    if !report.pass {
        // Return the detailed report so the wizard can show exactly what is missing.
        return Ok(report);
    }

    let home = app_home(&app)?;
    let same = root.canonicalize().ok() == home.join("models").canonicalize().ok();
    let mut settings = read_settings(&app);
    settings.model_root = if same {
        None
    } else {
        Some(display_path(&root))
    };
    write_settings(&app, &settings)?;
    Ok(report)
}

/* -------------------------------------------------------------------- run */

pub fn run() {
    // Local services are standalone: closing the client must not stop an
    // engine that other clients may still be using. Stop them explicitly.
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            paths,
            get_settings,
            save_settings,
            probe_connection,
            probe_system,
            probe_python,
            probe_runtime,
            probe_models,
            probe_services,
            install_runtime,
            start_qdrant,
            init_collection,
            start_engine,
            stop_service,
            read_log_tail,
            engine_health,
            ask_engine,
            submit_ingest,
            list_jobs,
            get_job,
            list_documents,
            delete_document,
            get_llm_settings,
            save_llm_settings,
            test_llm,
            download_models,
            import_models,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run the application");
}

#[cfg(test)]
mod tests {
    use super::python_version_supported;

    #[test]
    fn python_range_matches_project_requirement() {
        assert!(!python_version_supported("3.9.9"));
        assert!(python_version_supported("3.10.11"));
        assert!(python_version_supported("3.11.9"));
        assert!(python_version_supported("3.12.7"));
        assert!(!python_version_supported("3.13.0"));
        assert!(!python_version_supported("2.7.18"));
    }
}
