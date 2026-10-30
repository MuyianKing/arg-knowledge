import { useState } from "react";

import { clientApi } from "../api";
import type { AppSettings, ConnectionReport } from "../types";
import { Actions, Banner, errorText, Spinner } from "./ui";

export default function Connect({
  settings,
  patchSettings,
  onConnected,
  onOpenWizard,
  onSkip,
}: {
  settings: AppSettings;
  patchSettings: (patch: Partial<AppSettings>) => Promise<void>;
  onConnected: () => void;
  onOpenWizard: () => void;
  onSkip: () => void;
}) {
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl);
  const [tenantId, setTenantId] = useState(settings.tenantId);
  const [acl, setAcl] = useState(settings.acl);
  const [report, setReport] = useState<ConnectionReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const probe = async (): Promise<ConnectionReport | null> => {
    setBusy(true);
    setError(null);
    try {
      const value = await clientApi.probeConnection(baseUrl, tenantId, acl);
      setReport(value);
      return value;
    } catch (err) {
      setError(errorText(err));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const saveAndEnter = async () => {
    await patchSettings({ baseUrl: baseUrl.trim(), tenantId, acl });
    const value = await probe();
    if (value?.ok) {
      onConnected();
    }
  };

  return (
    <div className="connect">
      <header className="connect-head">
        <span className="logo large">ARG</span>
        <h1>连接知识库引擎</h1>
        <p>
          客户端只通过 HTTP 访问引擎。引擎可以部署在本机，也可以部署在内网服务器——连接方式完全一样。
        </p>
      </header>

      <div className="connect-grid">
        <section className="connect-card">
          <h2>连接已有后台</h2>
          <p className="muted">填写引擎地址和网关注入的身份头。</p>
          <label className="field">
            <span>引擎地址</span>
            <input
              value={baseUrl}
              spellCheck={false}
              placeholder="http://127.0.0.1:8080"
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </label>
          <div className="two-col">
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
                ? `连接成功 · ${report.latencyMs} ms · 状态 ${report.status ?? "ok"}${
                    report.ready ? " · 模型已预热" : " · 模型未预热"
                  }`
                : report.reachable
                  ? `引擎可达但返回异常：${report.error ?? "未知错误"}`
                  : `无法连接 ${report.baseUrl}：${report.error ?? "连接失败"}`}
            </Banner>
          )}

          <Actions>
            <button onClick={saveAndEnter} disabled={busy}>
              保存并进入
            </button>
            <button className="ghost" onClick={() => void probe()} disabled={busy}>
              测试连接
            </button>
            <span className="grow" />
            <button className="link" onClick={onSkip} type="button">
              暂不连接
            </button>
          </Actions>
          {busy && <Spinner label="正在连接引擎…" />}
        </section>

        <section className="connect-card deploy">
          <h2>在本机部署后台</h2>
          <p className="muted">
            如果这台机器还没有可用的引擎，可以让部署助手检测环境、安装 Python
            依赖、校验模型并启动本地服务。部署完成后会自动填入本机地址。
          </p>
          <ul className="plain-list">
            <li>检测 Windows、内存、磁盘、显卡和 WebView2</li>
            <li>使用你已安装的 Python 3.12 创建独立虚拟环境</li>
            <li>校验 BGE-M3 / Reranker / BM25 模型文件</li>
            <li>托管 Qdrant 与引擎进程，退出客户端时一并停止</li>
          </ul>
          <Actions>
            <button onClick={onOpenWizard}>进入本地部署</button>
          </Actions>
          <p className="hint">
            本地部署只是可选路径。之后仍可在设置里把客户端指向内网或其他服务器上的引擎。
          </p>
        </section>
      </div>
    </div>
  );
}
