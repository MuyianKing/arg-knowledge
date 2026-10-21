/* Local RAG engine debug console. No build step, no third-party dependencies. */

const $ = (id) => document.getElementById(id);

const STORE = {
  engine: "rag.engine",
  tenant: "rag.tenant",
  acl: "rag.acl",
};

const isFileMode = window.location.protocol === "file:";

const conn = {
  engine:
    localStorage.getItem(STORE.engine) ||
    (isFileMode ? "http://127.0.0.1:8080" : "/engine"),
  tenant: localStorage.getItem(STORE.tenant) || "acme",
  acl: localStorage.getItem(STORE.acl) || "internal",
};

let ingestFile = null;

/* ---------------------------------------------------------------- helpers */

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch],
  );
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function toast(message, kind = "") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  $("toasts").appendChild(node);
  setTimeout(() => node.remove(), kind === "error" ? 7000 : 3500);
}

function errorMessage(error) {
  const text = error && error.message ? error.message : String(error);
  if (text.includes("404") && text.includes("Not Found")) {
    return "接口不存在：请确认引擎以 DEV_TOOLS_ENABLED=true 启动";
  }
  return text;
}

async function api(path, { method = "GET", body, formData } = {}) {
  const base = conn.engine.replace(/\/+$/, "");
  const url = base + path;
  const options = { method, headers: {} };

  if (conn.tenant) options.headers["X-Tenant-Id"] = conn.tenant;
  if (conn.acl) options.headers["X-Acl"] = conn.acl;

  if (formData) {
    options.body = formData;
  } else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error(`无法连接引擎（${url}）：${error.message}`);
  }

  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  if (!response.ok) {
    let detail = data.detail ?? data.raw ?? `HTTP ${response.status}`;
    if (typeof detail !== "string") detail = JSON.stringify(detail, null, 2);
    throw new Error(`${detail}（HTTP ${response.status}）`);
  }
  return data;
}

async function withBusy(button, label, task) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function numberOf(input) {
  const value = input.value.trim();
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function itemsOf(object, orderedKeys) {
  const keys = orderedKeys || Object.keys(object);
  return keys
    .map((key) => {
      if (!(key in object)) return "";
      let value = object[key];
      if (typeof value === "boolean") value = value ? "是" : "否";
      if (value === null || value === undefined || value === "") value = "—";
      return `<div class="item"><b>${esc(key)}</b><span>${esc(value)}</span></div>`;
    })
    .join("");
}

/* ------------------------------------------------------------- connection */

function syncConn() {
  conn.engine = ($("engine-base").value || "/engine").trim().replace(/\/+$/, "");
  conn.tenant = $("tenant-id").value.trim();
  conn.acl = $("acl").value.trim();
  localStorage.setItem(STORE.engine, conn.engine);
  localStorage.setItem(STORE.tenant, conn.tenant);
  localStorage.setItem(STORE.acl, conn.acl);

  const docs = conn.engine.endsWith("/engine")
    ? conn.engine.replace(/\/engine$/, "") + "/docs"
    : conn.engine + "/docs";
  $("swagger-link").href = docs;
}

function initConn() {
  $("engine-base").value = conn.engine;
  $("tenant-id").value = conn.tenant;
  $("acl").value = conn.acl;
  syncConn();

  $("save-conn").addEventListener("click", async () => {
    syncConn();
    toast("连接设置已保存", "success");
    await refreshHealth();
  });

  for (const id of ["engine-base", "tenant-id", "acl"]) {
    $(id).addEventListener("change", syncConn);
  }
}

/* ------------------------------------------------------------------ tabs */

function initTabs() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $(`panel-${tab.dataset.tab}`).classList.add("active");
      if (tab.dataset.tab === "llm") loadLLM();
      if (tab.dataset.tab === "health") refreshHealth();
    });
  }
}

/* ---------------------------------------------------------------- health */

function healthItem(label, value, level) {
  return `<div class="health-item"><b>${esc(label)}</b><span class="${level}">${esc(value)}</span></div>`;
}

async function refreshHealth() {
  $("health-dot").className = "dot warn";
  $("health-text").textContent = "检测中…";
  try {
    const data = await api("/health");
    const ok = data.status === "ok";
    $("health-dot").className = `dot ${ok ? "ok" : "warn"}`;
    $("health-text").textContent = ok ? "引擎正常" : "引擎降级";

    $("health-grid").innerHTML = [
      healthItem("整体状态", data.status, ok ? "green" : "amber"),
      healthItem("Qdrant", data.qdrant ? "可达" : "不可达", data.qdrant ? "green" : "red"),
      healthItem("BGE-M3 目录", data.models?.bge_m3 ? "存在" : "缺失", data.models?.bge_m3 ? "green" : "red"),
      healthItem("Reranker 目录", data.models?.bge_reranker ? "存在" : "缺失", data.models?.bge_reranker ? "green" : "red"),
      healthItem("BM25 目录", data.models?.bm25 ? "存在" : "缺失", data.models?.bm25 ? "green" : "red"),
    ].join("");
    $("health-raw").textContent = pretty(data);
    $("health-time").textContent = `最后检测：${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $("health-dot").className = "dot bad";
    $("health-text").textContent = "连接失败";
    $("health-raw").textContent = errorMessage(error);
    $("health-grid").innerHTML = healthItem("错误", errorMessage(error), "red");
    $("health-time").textContent = "";
  }
}

/* ------------------------------------------------------------------- ask */

function filtersFrom(prefix, withDate) {
  const filters = {};

  const docType = $(`${prefix}-doctype`).value.trim();
  if (docType) {
    filters.doc_type = docType
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  }

  const version = $(`${prefix}-version`).value.trim();
  if (version) filters.version = version;

  const isCurrent = $(`${prefix}-iscurrent`).value;
  if (isCurrent) filters.is_current = isCurrent === "true";

  if (withDate) {
    const date = $(`${prefix}-effdate`).value;
    if (date) filters.effective_date_from = date;
  }

  return Object.keys(filters).length ? filters : null;
}

function statusBadge(response) {
  let cls = "ok";
  let text = "正常";
  if (response.refused) {
    cls = "bad";
    text = "拒答";
  } else if (response.degraded) {
    cls = "warn";
    text = "降级：未生成答案";
  } else if (response.cached) {
    cls = "info";
    text = "命中缓存";
  }
  return `<div class="metric status"><span class="badge ${cls}">${text}</span></div>`;
}

function metric(label, value) {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}

function renderAsk(response) {
  const shortId = response.request_id ? response.request_id.slice(0, 10) : "—";
  $("ask-metrics").innerHTML = [
    statusBadge(response),
    metric("总耗时", `${response.latency_ms} ms`),
    metric("检索", `${response.retrieval_ms} ms`),
    metric("重排", `${response.rerank_ms} ms`),
    metric("生成", `${response.generation_ms} ms`),
    metric("top_score", response.top_score == null ? "—" : Number(response.top_score).toFixed(4)),
    metric("prompt", response.prompt_version),
    metric("模型", response.model_revision),
    metric("request_id", shortId),
  ].join("");

  const citations = response.citations || [];
  const validIds = new Set(citations.map((citation) => citation.id));

  const answerHtml = esc(response.answer)
    .replace(/\[S(\d+)\]/g, (match, number) => {
      const id = `S${number}`;
      return validIds.has(id)
        ? `<span class="cite-ref" data-cid="${id}" role="button" tabindex="0">${match}</span>`
        : match;
    })
    .replace(/\n/g, "<br>");
  $("ask-answer").innerHTML = answerHtml || '<span class="hint">（空回答）</span>';

  $("ask-citations").innerHTML = citations
    .map(
      (citation) => `
      <article class="citation" data-cid="${esc(citation.id)}">
        <header>
          <span class="cid">${esc(citation.id)}</span>
          <span class="score">score ${Number(citation.score).toFixed(4)}</span>
        </header>
        <div class="meta">
          来源 ${esc(citation.source || "unknown")}
          · 页码 ${esc(citation.page || "—")}
          · 版本 ${esc(citation.version || "—")}
        </div>
        <p>${esc(citation.text)}</p>
      </article>`,
    )
    .join("");

  $("ask-raw").textContent = pretty(response);
  $("ask-result").classList.remove("hidden");
}

async function submitAsk() {
  const query = $("ask-query").value.trim();
  if (!query) {
    toast("请输入问题", "error");
    return;
  }

  const payload = {
    query,
    use_cache: $("ask-cache").checked,
  };
  const topK = numberOf($("ask-topk"));
  if (topK !== undefined) payload.top_k = topK;
  const filters = filtersFrom("ask", true);
  if (filters) payload.filters = filters;

  try {
    const response = await withBusy($("ask-submit"), "生成中…", () =>
      api("/api/v1/ask", { method: "POST", body: payload }),
    );
    renderAsk(response);
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

function initAsk() {
  $("ask-filters-toggle").addEventListener("click", () => {
    const box = $("ask-filters");
    const hidden = box.classList.toggle("hidden");
    $("ask-filters-toggle").textContent = hidden ? "高级过滤 ▾" : "高级过滤 ▴";
  });

  $("ask-submit").addEventListener("click", submitAsk);

  $("ask-clear").addEventListener("click", () => {
    $("ask-query").value = "";
    $("ask-result").classList.add("hidden");
  });

  $("ask-query").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submitAsk();
    }
  });

  $("ask-answer").addEventListener("click", (event) => {
    const ref = event.target.closest(".cite-ref");
    if (!ref) return;
    const card = document.querySelector(`.citation[data-cid="${ref.dataset.cid}"]`);
    if (!card) return;
    card.classList.add("flash");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => card.classList.remove("flash"), 1400);
  });
}

/* -------------------------------------------------------------- retrieve */

function renderRetrieve(response) {
  $("ret-metrics").innerHTML = [
    metric("候选数", response.candidates),
    metric("返回", response.chunks.length),
    metric("总耗时", `${response.latency_ms} ms`),
    metric("检索", `${response.retrieval_ms} ms`),
    metric("重排", `${response.rerank_ms} ms`),
  ].join("");

  $("ret-chunks").innerHTML = response.chunks
    .map(
      (chunk, index) => `
      <article class="card chunk">
        <div class="rank">${index + 1}</div>
        <div class="chunk-body">
          <div class="chunk-head">
            <span class="cid">${esc(chunk.id)}</span>
            <span>来源 ${esc(chunk.source || "unknown")}</span>
            <span>页码 ${esc(chunk.page || "—")}</span>
            <span>版本 ${esc(chunk.version || "—")}</span>
            <span class="score">score ${Number(chunk.score).toFixed(4)}</span>
          </div>
          <p>${esc(chunk.text)}</p>
        </div>
      </article>`,
    )
    .join("") || '<div class="card hint">没有召回结果：检查租户/ACL、过滤条件或是否已入库。</div>';

  $("ret-raw").textContent = pretty(response);
  $("ret-result").classList.remove("hidden");
}

async function submitRetrieve() {
  const query = $("ret-query").value.trim();
  if (!query) {
    toast("请输入查询内容", "error");
    return;
  }

  const payload = { query };
  const topK = numberOf($("ret-topk"));
  if (topK !== undefined) payload.top_k = topK;
  const filters = filtersFrom("ret", false);
  if (filters) payload.filters = filters;

  try {
    const response = await withBusy($("ret-submit"), "检索中…", () =>
      api("/api/v1/dev/retrieve", { method: "POST", body: payload }),
    );
    renderRetrieve(response);
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

function initRetrieve() {
  $("ret-submit").addEventListener("click", submitRetrieve);
  $("ret-query").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submitRetrieve();
    }
  });
}

/* ---------------------------------------------------------------- ingest */

function setIngestFile(file) {
  ingestFile = file || null;
  if (!file) {
    $("ingest-file-label").textContent = "点击选择文件，或拖拽到此处";
    return;
  }
  const sizeMb = (file.size / 1024 / 1024).toFixed(2);
  $("ingest-file-label").textContent = `${file.name}（${sizeMb} MB）`;
}

function renderIngest(response) {
  $("ingest-metrics").innerHTML = [
    metric("文件", response.filename),
    metric("文档数", response.documents),
    metric("分块数", response.chunks),
    metric("写入", response.dry_run ? "dry run" : response.upserted),
    metric("耗时", `${response.elapsed_ms} ms`),
    metric("租户", response.tenant_id),
    metric("ACL", (response.acl || []).join(", ")),
    metric("版本", response.version),
  ].join("");
  $("ingest-raw").textContent = pretty(response);
  $("ingest-result").classList.remove("hidden");
}

async function submitIngest(event) {
  event.preventDefault();
  const file = ingestFile || $("ingest-file").files[0];
  if (!file) {
    toast("请选择文件", "error");
    return;
  }

  const form = new FormData();
  form.append("file", file);
  form.append("version", $("ingest-version").value.trim() || "v1");
  form.append("doc_type", $("ingest-doctype").value.trim() || "auto");
  form.append("dry_run", $("ingest-dry").checked ? "true" : "false");
  if ($("ingest-effdate").value) form.append("effective_date", $("ingest-effdate").value);

  try {
    const response = await withBusy($("ingest-submit"), "入库中…（首次较慢）", () =>
      api("/api/v1/dev/ingest", { method: "POST", formData: form }),
    );
    renderIngest(response);
    toast("入库完成", "success");
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

function initIngest() {
  const dropzone = $("dropzone");
  const input = $("ingest-file");

  input.addEventListener("change", () => setIngestFile(input.files[0]));

  for (const type of ["dragenter", "dragover"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragover");
    });
  }
  dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];
    if (file) setIngestFile(file);
  });

  $("ingest-form").addEventListener("submit", submitIngest);
}

/* ------------------------------------------------------------------- llm */

function fillLLM(config) {
  $("llm-current").innerHTML = itemsOf(
    {
      "Base URL": config.base_url,
      Model: config.model_name,
      Revision: config.model_revision,
      "API Key": config.api_key_set ? config.api_key_masked : "未配置",
      Mock: config.mock,
      Temperature: config.temperature,
      "Top P": config.top_p,
      "Max Tokens": config.max_tokens,
      Timeout: `${config.timeout_seconds} s`,
      熔断器: config.circuit_open ? "已打开" : "关闭",
    },
    [
      "Base URL",
      "Model",
      "Revision",
      "API Key",
      "Mock",
      "Temperature",
      "Top P",
      "Max Tokens",
      "Timeout",
      "熔断器",
    ],
  );

  $("llm-base-url").value = config.base_url;
  $("llm-model").value = config.model_name;
  $("llm-revision").value = config.model_revision;
  $("llm-temperature").value = config.temperature;
  $("llm-top-p").value = config.top_p;
  $("llm-max-tokens").value = config.max_tokens;
  $("llm-timeout").value = config.timeout_seconds;
  $("llm-mock").checked = Boolean(config.mock);
  $("llm-api-key").value = "";
  $("llm-api-key").placeholder = config.api_key_set
    ? `已配置 ${config.api_key_masked}，留空则不修改`
    : "尚未配置，请输入 API Key";
}

async function loadLLM() {
  try {
    const config = await api("/api/v1/dev/llm");
    fillLLM(config);
  } catch (error) {
    $("llm-current").innerHTML = `<div class="item"><b>状态</b><span>${esc(
      errorMessage(error),
    )}</span></div>`;
  }
}

async function saveLLM(event) {
  event.preventDefault();

  const payload = {
    base_url: $("llm-base-url").value.trim(),
    model_name: $("llm-model").value.trim(),
    model_revision: $("llm-revision").value.trim(),
    mock: $("llm-mock").checked,
  };

  for (const [field, inputId] of [
    ["temperature", "llm-temperature"],
    ["top_p", "llm-top-p"],
    ["max_tokens", "llm-max-tokens"],
    ["timeout_seconds", "llm-timeout"],
  ]) {
    const value = numberOf($(inputId));
    if (value !== undefined) payload[field] = value;
  }

  const key = $("llm-api-key").value.trim();
  if (key) payload.api_key = key;

  if (!payload.base_url || !payload.model_name) {
    toast("Base URL 和 Model 不能为空", "error");
    return;
  }

  try {
    const config = await withBusy($("llm-save"), "应用中…", () =>
      api("/api/v1/dev/llm", { method: "PUT", body: payload }),
    );
    fillLLM(config);
    toast("LLM 配置已生效", "success");
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

async function testLLM() {
  try {
    const result = await withBusy($("llm-test"), "测试中…", () =>
      api("/api/v1/dev/llm/test", { method: "POST" }),
    );
    $("llm-test-card").classList.remove("hidden");
    $("llm-test-result").textContent = pretty(result);
    toast(result.ok ? `连接成功（${result.latency_ms} ms）` : `连接失败：${result.error}`, result.ok ? "success" : "error");
  } catch (error) {
    $("llm-test-card").classList.remove("hidden");
    $("llm-test-result").textContent = errorMessage(error);
    toast(errorMessage(error), "error");
  }
}

function initLLM() {
  $("llm-form").addEventListener("submit", saveLLM);
  $("llm-refresh").addEventListener("click", loadLLM);
  $("llm-test").addEventListener("click", testLLM);
  $("llm-mock").addEventListener("change", () => {
    toast("Mock 开关修改后需要点击“保存并应用”才生效");
  });
}

/* ------------------------------------------------------------------ boot */

initConn();
initTabs();
initAsk();
initRetrieve();
initIngest();
initLLM();
refreshHealth();

if (isFileMode) {
  toast("当前以 file:// 打开：浏览器会拦截跨域请求，建议运行 scripts/dev_web.py", "error");
}
