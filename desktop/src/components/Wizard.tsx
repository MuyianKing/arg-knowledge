import { useCallback, useEffect, useState } from "react";

import { deployApi, openExternal, pickDirectory } from "../api";
import type {
  AppSettings,
  ModelReport,
  PythonCandidate,
  PythonReport,
  RuntimeReport,
  ServiceStatus,
  SystemReport,
} from "../types";
import { Actions, Banner, CheckList, errorText, Spinner, StepHeader } from "./ui";

type StepId = "system" | "python" | "runtime" | "models" | "services" | "done";

const STEPS: { id: StepId; title: string; hint: string }[] = [
  { id: "system", title: "系统检查", hint: "Windows、内存、磁盘、显卡" },
  { id: "python", title: "Python", hint: "检测 3.12 64 位解释器" },
  { id: "runtime", title: "依赖", hint: "创建虚拟环境并安装依赖" },
  { id: "models", title: "模型", hint: "校验 BGE-M3 / Reranker / BM25" },
  { id: "services", title: "启动服务", hint: "Qdrant 与引擎" },
  { id: "done", title: "完成", hint: "登记本机引擎地址" },
];

export default function Wizard({
  settings,
  patchSettings,
  onFinish,
  onCancel,
}: {
  settings: AppSettings;
  patchSettings: (patch: Partial<AppSettings>) => Promise<void>;
  onFinish: () => void;
  onCancel: () => void;
}) {
  const [current, setCurrent] = useState<StepId>("system");
  const [done, setDone] = useState<Record<StepId, boolean>>({
    system: false,
    python: false,
    runtime: false,
    models: false,
    services: false,
    done: false,
  });

  const markDone = useCallback((step: StepId, ok: boolean) => {
    setDone((prev) => (prev[step] === ok ? prev : { ...prev, [step]: ok }));
  }, []);

  const index = STEPS.findIndex((step) => step.id === current);
  const canNext = done[current] || current === "done";

  return (
    <div className="wizard">
      <aside className="rail">
        <div className="brand">
          <span className="logo">ARG</span>
          <div>
            <strong>本地部署助手</strong>
            <p>独立于客户端连接</p>
          </div>
        </div>
        <nav>
          {STEPS.map((step, i) => (
            <button
              key={step.id}
              className={`rail-item ${current === step.id ? "active" : ""} ${
                done[step.id] ? "done" : ""
              }`}
              onClick={() => setCurrent(step.id)}
            >
              <span className="rail-index">{done[step.id] ? "✓" : i + 1}</span>
              <span>
                <strong>{step.title}</strong>
                <small>{step.hint}</small>
              </span>
            </button>
          ))}
        </nav>
        <div className="rail-note">
          <p>部署助手只负责把后台装到本机。客户端连接哪个引擎，仍由设置里的地址决定。</p>
          <button className="link" onClick={onCancel} type="button">
            返回连接页面
          </button>
        </div>
      </aside>

      <main className="wizard-main">
        <div className="wizard-body">
          {current === "system" && <SystemStep onDone={(ok) => markDone("system", ok)} />}
          {current === "python" && (
            <PythonStep
              settings={settings}
              patchSettings={patchSettings}
              onDone={(ok) => markDone("python", ok)}
            />
          )}
          {current === "runtime" && (
            <RuntimeStep settings={settings} onDone={(ok) => markDone("runtime", ok)} />
          )}
          {current === "models" && <ModelsStep onDone={(ok) => markDone("models", ok)} />}
          {current === "services" && (
            <ServicesStep settings={settings} onDone={(ok) => markDone("services", ok)} />
          )}
          {current === "done" && (
            <DoneStep
              settings={settings}
              patchSettings={patchSettings}
              onFinish={onFinish}
            />
          )}
        </div>

        <footer className="wizard-footer">
          <button
            className="ghost"
            disabled={index <= 0}
            onClick={() => setCurrent(STEPS[Math.max(0, index - 1)].id)}
          >
            上一步
          </button>
          <span className="grow" />
          {current !== "done" && (
            <>
              <span className="step-state">
                {done[current] ? "本步骤已通过" : "完成本步骤后可继续"}
              </span>
              <button
                disabled={!canNext}
                onClick={() => setCurrent(STEPS[Math.min(STEPS.length - 1, index + 1)].id)}
              >
                下一步
              </button>
            </>
          )}
        </footer>
      </main>
    </div>
  );
}

/* ------------------------------------------------------------------ system */

function SystemStep({ onDone }: { onDone: (ok: boolean) => void }) {
  const [report, setReport] = useState<SystemReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const value = await deployApi.probeSystem();
      setReport(value);
      onDone(value.pass);
    } catch (err) {
      setError(errorText(err));
      onDone(false);
    } finally {
      setBusy(false);
    }
  }, [onDone]);

  useEffect(() => {
    void run();
  }, [run]);

  return (
    <>
      <StepHeader
        title="系统检查"
        desc="确认这台机器能跑本地向量检索。显存不足时可以继续，但重排会退化到 CPU。"
      />
      {busy && !report && <Spinner label="正在检测硬件与系统…" />}
      {error && <Banner kind="error">{error}</Banner>}
      {report && (
        <>
          <CheckList items={report.checks} />
          <Actions>
            <button className="ghost" onClick={run} disabled={busy}>
              重新检测
            </button>
            <span className="grow" />
            <span className={`pill ${report.pass ? "ok" : "warn"}`}>
              {report.pass ? "可以继续" : "存在必须解决的问题"}
            </span>
          </Actions>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ python */

function PythonStep({
  settings,
  patchSettings,
  onDone,
}: {
  settings: AppSettings;
  patchSettings: (patch: Partial<AppSettings>) => Promise<void>;
  onDone: (ok: boolean) => void;
}) {
  const [report, setReport] = useState<PythonReport | null>(null);
  const [customPath, setCustomPath] = useState(settings.pythonPath ?? "");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (path?: string) => {
      setBusy(true);
      setError(null);
      try {
        const value = await deployApi.probePython(path ?? customPath ?? null);
        setReport(value);
        if (value.selected) {
          await patchSettings({ pythonPath: value.selected });
        }
        onDone(value.pass);
      } catch (err) {
        setError(errorText(err));
        onDone(false);
      } finally {
        setBusy(false);
      }
    },
    [customPath, onDone, patchSettings],
  );

  useEffect(() => {
    void run(settings.pythonPath ?? undefined);
    // Probe once on entry; later runs are explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <StepHeader
        title="Python 运行时"
        desc="需要 Python 3.10–3.12 的 64 位版本（推荐 3.12）。应用不会替你静默安装，检测不到时按提示安装后回来重新检测。"
      />
      {busy && !report && <Spinner label="正在查找 Python 解释器…" />}
      {error && <Banner kind="error">{error}</Banner>}
      {report && (
        <>
          <CheckList items={report.checks} />
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>解释器</th>
                  <th>路径</th>
                  <th>版本</th>
                  <th>位数</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {report.candidates.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      没有找到可用的 Python。
                    </td>
                  </tr>
                )}
                {report.candidates.map((candidate: PythonCandidate) => (
                  <tr key={`${candidate.command}-${candidate.path}`}>
                    <td>
                      <code>{candidate.command}</code>
                    </td>
                    <td className="path">{candidate.path || "—"}</td>
                    <td>{candidate.version || "—"}</td>
                    <td>{candidate.bits || "—"}</td>
                    <td>
                      {candidate.ok ? (
                        <span className="pill ok">可用</span>
                      ) : (
                        <span className="pill error">{candidate.error ?? "不可用"}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <label className="field">
            <span>手动指定 python.exe</span>
            <input
              value={customPath}
              placeholder="C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe"
              onChange={(event) => setCustomPath(event.target.value)}
            />
          </label>

          <Actions>
            <button className="ghost" onClick={() => void run(customPath)} disabled={busy}>
              重新检测
            </button>
            <button
              className="ghost"
              onClick={() => void openExternal("https://www.python.org/downloads/windows/")}
            >
              打开 Python 下载页
            </button>
            <span className="grow" />
            <span className={`pill ${report.pass ? "ok" : "warn"}`}>
              {report.pass ? "已找到受支持的 Python" : "需要 3.10–3.12 的 64 位版本"}
            </span>
          </Actions>
          <p className="hint">
            安装时勾选 “Add python.exe to PATH”，并确认是 64 位安装包；32 位
            Python 无法安装 PyTorch。不要使用 Microsoft Store 版本。
          </p>
        </>
      )}
    </>
  );
}

/* ----------------------------------------------------------------- runtime */

function RuntimeStep({
  settings,
  onDone,
}: {
  settings: AppSettings;
  onDone: (ok: boolean) => void;
}) {
  const [report, setReport] = useState<RuntimeReport | null>(null);
  const [busy, setBusy] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [profile, setProfile] = useState<"cuda" | "cpu">("cuda");
  const [pypiMirror, setPypiMirror] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);

  const probe = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const value = await deployApi.probeRuntime();
      setReport(value);
      onDone(value.pass);
    } catch (err) {
      setError(errorText(err));
      onDone(false);
    } finally {
      setBusy(false);
    }
  }, [onDone]);

  useEffect(() => {
    void probe();
  }, [probe]);

  const install = async () => {
    if (!settings.pythonPath) {
      setError("请先在“Python”步骤选择一个可用解释器。");
      return;
    }
    setInstalling(true);
    setError(null);
    setLogs([]);
    const unlisten = await deployApi.onLog((log) => {
      setLogs((prev) => [...prev.slice(-400), `${log.step} | ${log.line}`]);
    });
    try {
      const value = await deployApi.installRuntime(
        settings.pythonPath,
        profile,
        pypiMirror.trim() || undefined,
      );
      setReport(value);
      onDone(value.pass);
    } catch (err) {
      setError(errorText(err));
    } finally {
      unlisten();
      setInstalling(false);
    }
  };

  return (
    <>
      <StepHeader
        title="Python 依赖"
        desc="在应用数据目录创建独立虚拟环境，不会污染系统 Python。CUDA 版 torch 约 3~4 GB，CPU 版约 1.5 GB。这一步只属于本机部署；连接远程引擎时不需要。"
      />
      {busy && !report && <Spinner label="正在检查虚拟环境…" />}
      {error && <Banner kind="error">{error}</Banner>}
      {report && (
        <>
          <CheckList items={report.checks} />
          <div className="kv">
            <div>
              <span>虚拟环境</span>
              <code>{report.venvPython}</code>
            </div>
            <div>
              <span>torch</span>
              <code>{report.torch ?? "未安装"}</code>
            </div>
            <div>
              <span>CUDA</span>
              <code>{report.cuda ? report.cudaDevice ?? "可用" : "不可用"}</code>
            </div>
          </div>
        </>
      )}

      <div className="install-row">
        <label className="field tiny">
          <span>torch 版本</span>
          <select
            value={profile}
            onChange={(event) => setProfile(event.target.value as "cuda" | "cpu")}
          >
            <option value="cuda">CUDA (cu126)</option>
            <option value="cpu">CPU</option>
          </select>
        </label>
        <label className="field">
          <span>PyPI 镜像（可选）</span>
          <input
            value={pypiMirror}
            spellCheck={false}
            placeholder="https://pypi.tuna.tsinghua.edu.cn/simple"
            onChange={(event) => setPypiMirror(event.target.value)}
          />
        </label>
        <button onClick={install} disabled={installing || !settings.pythonPath}>
          {installing ? "安装中…" : report?.pass ? "重新安装依赖" : "安装依赖"}
        </button>
        <button className="ghost" onClick={probe} disabled={busy || installing}>
          重新检测
        </button>
      </div>
      {!settings.pythonPath && (
        <p className="hint">尚未选择 Python 解释器，请返回上一步完成检测。</p>
      )}
      {logs.length > 0 && <pre className="log">{logs.join("\n")}</pre>}
      {installing && <Spinner label="正在安装依赖，首次可能需要 5~15 分钟…" />}
    </>
  );
}

/* ------------------------------------------------------------------ models */

function ModelsStep({ onDone }: { onDone: (ok: boolean) => void }) {
  const [report, setReport] = useState<ModelReport | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mirror, setMirror] = useState("");
  const [working, setWorking] = useState<"download" | "import" | null>(null);
  const [logs, setLogs] = useState<string[]>([]);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const value = await deployApi.probeModels();
      setReport(value);
      onDone(value.pass);
    } catch (err) {
      setError(errorText(err));
      onDone(false);
    } finally {
      setBusy(false);
    }
  }, [onDone]);

  useEffect(() => {
    void run();
  }, [run]);

  const download = async () => {
    setWorking("download");
    setError(null);
    setLogs([]);
    const unlisten = await deployApi.onLog((log) => {
      setLogs((prev) => [...prev.slice(-300), `${log.step} | ${log.line}`]);
    });
    try {
      const value = await deployApi.downloadModels(mirror.trim() || null);
      setReport(value);
      onDone(value.pass);
    } catch (err) {
      setError(errorText(err));
    } finally {
      unlisten();
      setWorking(null);
    }
  };

  const importDirectory = async () => {
    const selected = await pickDirectory();
    if (!selected) return;
    setWorking("import");
    setError(null);
    try {
      const value = await deployApi.importModels(selected);
      setReport(value);
      onDone(value.pass);
      if (!value.pass) {
        setError(`目录不完整：缺少 ${value.missing.length} 个文件`);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setWorking(null);
    }
  };

  return (
    <>
      <StepHeader
        title="本地模型"
        desc="BGE-M3、BGE-Reranker-v2-m3 与 BM25 词典，共约 4.3 GB。可以在线下载，也可以导入已有模型目录。"
      />
      {busy && !report && <Spinner label="正在校验模型文件…" />}
      {error && <Banner kind="error">{error}</Banner>}
      {report && (
        <>
          <CheckList items={report.checks} />
          <div className="kv">
            <div>
              <span>模型目录</span>
              <code>{report.modelRoot}</code>
            </div>
            <div>
              <span>已检查</span>
              <code>{report.checked} 个文件</code>
            </div>
            <div>
              <span>总大小</span>
              <code>{(report.totalBytes / 1024 ** 3).toFixed(2)} GiB</code>
            </div>
          </div>
          {report.missing.length > 0 && (
            <Banner kind="error">
              缺少 {report.missing.length} 个文件：
              <code>{report.missing.join(", ")}</code>
            </Banner>
          )}
          {report.truncated.length > 0 && (
            <Banner kind="error">
              有 {report.truncated.length} 个文件大小异常，建议重新下载。
            </Banner>
          )}

          <div className="install-row">
            <label className="field">
              <span>HF 镜像（可选）</span>
              <input
                value={mirror}
                spellCheck={false}
                placeholder="https://hf-mirror.com"
                onChange={(event) => setMirror(event.target.value)}
              />
            </label>
            <button onClick={() => void download()} disabled={working !== null || busy}>
              {working === "download" ? "下载中…" : "在线下载"}
            </button>
            <button
              className="ghost"
              onClick={() => void importDirectory()}
              disabled={working !== null || busy}
            >
              {working === "import" ? "导入中…" : "导入本地目录"}
            </button>
            <button className="ghost" onClick={run} disabled={working !== null || busy}>
              重新检测
            </button>
            <span className="grow" />
            <span className={`pill ${report.pass ? "ok" : "warn"}`}>
              {report.pass ? "模型完整" : "模型不完整"}
            </span>
          </div>
          {working && <Spinner label="模型处理中，请勿关闭窗口…" />}
          {logs.length > 0 && <pre className="log">{logs.join("\n")}</pre>}
          <p className="hint">
            离线导入请选择包含 bge-m3、bge-reranker-v2-m3、bm25 三个子目录的父目录；压缩包需先解压。
          </p>
        </>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- services */

function ServicesStep({
  settings,
  onDone,
}: {
  settings: AppSettings;
  onDone: (ok: boolean) => void;
}) {
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState("");
  const [collection, setCollection] = useState<{ ok: boolean; message: string } | null>(null);
  const [collectionBusy, setCollectionBusy] = useState(false);

  const probe = useCallback(async () => {
    try {
      const value = await deployApi.probeServices();
      setStatus(value);
      onDone(value.engineRunning && value.qdrantRunning);
    } catch (err) {
      setError(errorText(err));
    }
  }, [onDone]);

  useEffect(() => {
    void probe();
    const timer = window.setInterval(() => void probe(), 3000);
    return () => window.clearInterval(timer);
  }, [probe]);

  const initCollection = useCallback(async () => {
    setCollectionBusy(true);
    try {
      let lastError = "未知错误";
      // Qdrant may need a moment after spawn before it accepts connections.
      for (let attempt = 0; attempt < 12; attempt += 1) {
        try {
          const message = await deployApi.initCollection();
          setCollection({ ok: true, message });
          return;
        } catch (err) {
          lastError = errorText(err);
          await new Promise((resolve) => window.setTimeout(resolve, 500));
        }
      }
      setCollection({ ok: false, message: lastError });
    } finally {
      setCollectionBusy(false);
    }
  }, []);

  useEffect(() => {
    if (status?.qdrantRunning && collection === null && !collectionBusy) {
      void initCollection();
    }
  }, [status?.qdrantRunning, collection, collectionBusy, initCollection]);

  const start = async (service: "qdrant" | "engine") => {
    setBusy(true);
    setError(null);
    try {
      const value =
        service === "qdrant" ? await deployApi.startQdrant() : await deployApi.startEngine();
      setStatus(value);
      setLog(await deployApi.logTail(service, 60));
      if (service === "qdrant") {
        await initCollection();
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const stop = async (service: "qdrant" | "engine") => {
    setBusy(true);
    try {
      setStatus(await deployApi.stopService(service));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <StepHeader
        title="启动本地服务"
        desc="先启动 Qdrant，再启动引擎。Qdrant 启动后会自动创建 collection（幂等）；引擎启动时会预热模型，首次可能需要 20~60 秒。"
      />
      {error && <Banner kind="error">{error}</Banner>}
      {status && (
        <>
          <CheckList items={status.checks} />
          <div className="kv">
            <div>
              <span>Qdrant</span>
              <code>{status.qdrantBinary ?? "未找到 qdrant.exe"}</code>
            </div>
            <div>
              <span>引擎端口</span>
              <code>{status.enginePort}</code>
            </div>
          </div>
          <Actions>
            <button onClick={() => void start("qdrant")} disabled={busy || status.qdrantRunning}>
              启动 Qdrant
            </button>
            <button
              className="ghost"
              onClick={() => void initCollection()}
              disabled={busy || collectionBusy || !status.qdrantRunning}
            >
              初始化知识库
            </button>
            <button onClick={() => void start("engine")} disabled={busy || status.engineRunning}>
              启动引擎
            </button>
            <button className="ghost" onClick={() => void stop("engine")} disabled={busy}>
              停止引擎
            </button>
            <button className="ghost" onClick={() => void stop("qdrant")} disabled={busy}>
              停止 Qdrant
            </button>
            <span className="grow" />
            <button
              className="ghost"
              onClick={() => void openExternal(`http://127.0.0.1:${settings.enginePort}/docs`)}
            >
              打开 Swagger
            </button>
          </Actions>
          {collectionBusy && <Spinner label="正在创建知识库 collection…" />}
          {collection && (
            <Banner kind={collection.ok ? "ok" : "error"}>
              {collection.ok ? "知识库已就绪：" : "知识库初始化失败："}
              <code>{collection.message}</code>
            </Banner>
          )}
        </>
      )}

      {status?.engineHealth != null && (
        <pre className="log health">{JSON.stringify(status.engineHealth, null, 2)}</pre>
      )}

      <div className="log-tools">
        <button className="link" onClick={() => void deployApi.logTail("engine", 80).then(setLog)}>
          刷新引擎日志
        </button>
        <button className="link" onClick={() => void deployApi.logTail("qdrant", 80).then(setLog)}>
          刷新 Qdrant 日志
        </button>
      </div>
      {log && <pre className="log">{log}</pre>}
    </>
  );
}

/* -------------------------------------------------------------------- done */

function DoneStep({
  settings,
  patchSettings,
  onFinish,
}: {
  settings: AppSettings;
  patchSettings: (patch: Partial<AppSettings>) => Promise<void>;
  onFinish: () => void;
}) {
  const localUrl = `http://127.0.0.1:${settings.enginePort}`;

  const finish = async () => {
    await patchSettings({
      baseUrl: localUrl,
      setupCompleted: true,
    });
    onFinish();
  };

  return (
    <>
      <StepHeader
        title="本地后台已就绪"
        desc="部署助手已经完成本机环境准备。客户端接下来通过 HTTP 连接这个引擎。"
      />
      <div className="done-grid">
        <div className="done-card">
          <span>将写入的连接地址</span>
          <strong className="ellipsis">{localUrl}</strong>
        </div>
        <div className="done-card">
          <span>Qdrant</span>
          <strong>127.0.0.1:{settings.qdrantHttpPort}</strong>
        </div>
        <div className="done-card">
          <span>Python</span>
          <strong className="ellipsis">{settings.pythonPath ?? "自动检测"}</strong>
        </div>
      </div>
      <Banner kind="ok">
        本地部署只是当前连接目标。之后可以在设置里改成任意内网引擎地址，客户端不需要重新部署。
      </Banner>
      <Actions>
        <button onClick={() => void finish()}>完成并连接本机引擎</button>
      </Actions>
    </>
  );
}
