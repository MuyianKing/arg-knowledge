import { useCallback, useEffect, useState } from "react";

import { clientApi, deployApi } from "../api";
import type { AppSettings, ConnectionReport, Paths, ServiceStatus } from "../types";
import AskPanel from "./AskPanel";
import KnowledgePanel from "./KnowledgePanel";
import LlmPanel from "./LlmPanel";
import { Actions, Banner, CheckList, Spinner, errorText } from "./ui";

type Tab = "ask" | "knowledge" | "settings";

export default function Main({
  settings,
  patchSettings,
  onOpenWizard,
  onReconnect,
}: {
  settings: AppSettings;
  patchSettings: (patch: Partial<AppSettings>) => Promise<void>;
  onOpenWizard: () => void;
  onReconnect: () => void;
}) {
  const [tab, setTab] = useState<Tab>("ask");
  const [conn, setConn] = useState<ConnectionReport | null>(null);
  const [local, setLocal] = useState<ServiceStatus | null>(null);
  const [paths, setPaths] = useState<Paths | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const connection = await clientApi.probeConnection();
      setConn(connection);
      if (settings.setupCompleted) {
        const [service, pathValue] = await Promise.all([
          deployApi.probeServices(),
          deployApi.paths(),
        ]);
        setLocal(service);
        setPaths(pathValue);
      }
    } catch (err) {
      setError(errorText(err));
    }
  }, [settings.setupCompleted]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const connected = conn?.ok === true;

  return (
    <div className="main-shell">
      <header className="main-head">
        <div className="brand">
          <span className="logo">ARG</span>
          <div>
            <strong>知识库客户端</strong>
            <p>{settings.baseUrl}</p>
          </div>
        </div>
        <div className="head-status">
          <span className={`pill ${connected ? "ok" : "error"}`}>
            {connected ? "引擎已连接" : "引擎未连接"}
          </span>
          <nav className="main-tabs">
            <button
              className={`ghost small ${tab === "ask" ? "pressed" : ""}`}
              onClick={() => setTab("ask")}
            >
              问答
            </button>
            <button
              className={`ghost small ${tab === "knowledge" ? "pressed" : ""}`}
              onClick={() => setTab("knowledge")}
            >
              知识库
            </button>
            <button
              className={`ghost small ${tab === "settings" ? "pressed" : ""}`}
              onClick={() => setTab("settings")}
            >
              设置
            </button>
          </nav>
          <button className="ghost small" onClick={onReconnect}>
            连接设置
          </button>
        </div>
      </header>

      <main className="main-body">
        {error && <Banner kind="error">{error}</Banner>}
        {tab === "ask" && <AskPanel connected={connected} onConnect={onReconnect} />}
        {tab === "knowledge" && (
          <KnowledgePanel connected={connected} onConnect={onReconnect} />
        )}
        {tab === "settings" && (
          <SettingsPanel
            settings={settings}
            patchSettings={patchSettings}
            connected={connected}
            local={local}
            paths={paths}
            onOpenWizard={onOpenWizard}
            onRefresh={refresh}
          />
        )}
      </main>
    </div>
  );
}

function SettingsPanel({
  settings,
  patchSettings,
  connected,
  local,
  paths,
  onOpenWizard,
  onRefresh,
}: {
  settings: AppSettings;
  patchSettings: (patch: Partial<AppSettings>) => Promise<void>;
  connected: boolean;
  local: ServiceStatus | null;
  paths: Paths | null;
  onOpenWizard: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl);
  const [tenantId, setTenantId] = useState(settings.tenantId);
  const [acl, setAcl] = useState(settings.acl);
  const [report, setReport] = useState<ConnectionReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState("");

  useEffect(() => {
    setBaseUrl(settings.baseUrl);
    setTenantId(settings.tenantId);
    setAcl(settings.acl);
  }, [settings.baseUrl, settings.tenantId, settings.acl]);

  const test = async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await clientApi.probeConnection(baseUrl, tenantId, acl));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    await patchSettings({ baseUrl: baseUrl.trim(), tenantId, acl });
    await onRefresh();
  };

  const startOrStop = async (service: "qdrant" | "engine") => {
    setBusy(true);
    setError(null);
    try {
      const running = service === "qdrant" ? local?.qdrantRunning : local?.engineRunning;
      if (running) {
        await deployApi.stopService(service);
      } else if (service === "qdrant") {
        await deployApi.startQdrant();
      } else {
        await deployApi.startEngine();
      }
      await onRefresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings">
      <section className="card">
        <h2>连接设置</h2>
        <p className="muted">
          客户端只认这个地址。指向本机、内网或网关都可以，不需要重新部署。
        </p>
        <div className="form-grid">
          <label className="field wide">
            <span>引擎地址</span>
            <input
              value={baseUrl}
              spellCheck={false}
              placeholder="http://127.0.0.1:8080"
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </label>
          <label className="field">
            <span>X-Tenant-Id</span>
            <input
              value={tenantId}
              spellCheck={false}
              onChange={(event) => setTenantId(event.target.value)}
            />
          </label>
          <label className="field">
            <span>X-Acl</span>
            <input
              value={acl}
              spellCheck={false}
              onChange={(event) => setAcl(event.target.value)}
            />
          </label>
        </div>
        {error && <Banner kind="error">{error}</Banner>}
        {report && (
          <Banner kind={report.ok ? "ok" : "error"}>
            {report.ok
              ? `连接成功 · ${report.latencyMs} ms · ${report.ready ? "模型已预热" : "模型未预热"}`
              : report.reachable
                ? `引擎可达但返回异常：${report.error ?? "未知错误"}`
                : `无法连接：${report.error ?? "连接失败"}`}
          </Banner>
        )}
        <Actions>
          <button onClick={() => void save()} disabled={busy}>
            保存
          </button>
          <button className="ghost" onClick={() => void test()} disabled={busy}>
            测试连接
          </button>
        </Actions>
        {busy && <Spinner label="正在处理…" />}
      </section>

      <LlmPanel connected={connected} />

      <section className="card">
        <div className="card-head">
          <div>
            <h2>本机后台部署</h2>
            <p className="muted">
              可选功能。部署助手负责安装依赖、校验模型和托管进程，不参与客户端通信。
            </p>
          </div>
          <button className="ghost small" onClick={onOpenWizard}>
            打开部署助手
          </button>
        </div>

        <div className="kv">
          <div>
            <span>安装目录</span>
            <code>{paths?.home ?? "—"}</code>
          </div>
          <div>
            <span>引擎程序</span>
            <code>{paths?.engine ?? "未找到"}</code>
          </div>
          <div>
            <span>Python</span>
            <code>{settings.pythonPath ?? "未配置"}</code>
          </div>
          <div>
            <span>本机端口</span>
            <code>
              引擎 {settings.enginePort} · Qdrant {settings.qdrantHttpPort}
            </code>
          </div>
        </div>

        {local && <CheckList items={local.checks} />}

        <Actions>
          <button onClick={() => void startOrStop("qdrant")} disabled={busy}>
            {local?.qdrantRunning ? "停止 Qdrant" : "启动 Qdrant"}
          </button>
          <button onClick={() => void startOrStop("engine")} disabled={busy}>
            {local?.engineRunning ? "停止引擎" : "启动引擎"}
          </button>
        </Actions>

        <div className="log-tools">
          <button
            className="link"
            onClick={() => void deployApi.logTail("engine", 100).then(setLog)}
          >
            查看引擎日志
          </button>
          <button
            className="link"
            onClick={() => void deployApi.logTail("qdrant", 100).then(setLog)}
          >
            查看 Qdrant 日志
          </button>
        </div>
        {log && <pre className="log">{log}</pre>}
      </section>
    </div>
  );
}
