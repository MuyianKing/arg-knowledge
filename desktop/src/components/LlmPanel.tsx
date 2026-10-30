import { useEffect, useState } from "react";

import { llmApi } from "../api";
import type { LlmSettings } from "../types";
import { Actions, Banner, Spinner, errorText } from "./ui";

export default function LlmPanel({ connected }: { connected: boolean }) {
  const [view, setView] = useState<LlmSettings | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [modelRevision, setModelRevision] = useState("");
  const [temperature, setTemperature] = useState(0.1);
  const [maxTokens, setMaxTokens] = useState(512);
  const [mock, setMock] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null);

  const applyView = (value: LlmSettings) => {
    setView(value);
    setBaseUrl(value.baseUrl);
    setModelName(value.modelName);
    setModelRevision(value.modelRevision);
    setTemperature(value.temperature);
    setMaxTokens(value.maxTokens);
    setMock(value.mock);
    setApiKey("");
    setClearKey(false);
  };

  useEffect(() => {
    llmApi
      .get()
      .then(applyView)
      .catch((err) => setError(errorText(err)));
  }, []);

  const save = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const value = await llmApi.save({
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        modelRevision: modelRevision.trim(),
        temperature,
        maxTokens,
        mock,
        apiKey: apiKey.trim() ? apiKey.trim() : null,
        clearKey,
      });
      applyView(value);
      setNotice("已保存。本机引擎会自动应用；远程引擎在重启后读取配置。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      setTestResult(await llmApi.test());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="card">
      <h2>LLM 配置</h2>
      <p className="muted">
        API Key 存进 Windows 凭据管理器，不写入 settings.json，也不会出现在日志里。
      </p>

      <div className="form-grid">
        <label className="field">
          <span>Base URL</span>
          <input
            value={baseUrl}
            spellCheck={false}
            placeholder="https://api.deepseek.com/v1"
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </label>
        <label className="field">
          <span>模型名</span>
          <input
            value={modelName}
            spellCheck={false}
            placeholder="deepseek-chat"
            onChange={(event) => setModelName(event.target.value)}
          />
        </label>
        <label className="field">
          <span>模型版本标识</span>
          <input
            value={modelRevision}
            spellCheck={false}
            placeholder="deepseek-chat@2026-01"
            onChange={(event) => setModelRevision(event.target.value)}
          />
        </label>
        <label className="field">
          <span>API Key</span>
          <input
            type="password"
            value={apiKey}
            placeholder={view?.apiKeySet ? "已保存，留空表示不修改" : "sk-..."}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        <label className="field">
          <span>temperature</span>
          <input
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            onChange={(event) => setTemperature(Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span>max_tokens</span>
          <input
            type="number"
            min={1}
            max={32768}
            value={maxTokens}
            onChange={(event) => setMaxTokens(Number(event.target.value))}
          />
        </label>
      </div>

      <div className="row wrap">
        <label className="check">
          <input type="checkbox" checked={mock} onChange={(event) => setMock(event.target.checked)} />
          使用 mock 回答（联调）
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={clearKey}
            onChange={(event) => setClearKey(event.target.checked)}
          />
          删除已保存的 Key
        </label>
        <span className="grow" />
        <span className={`pill ${view?.apiKeySet ? "ok" : "warn"}`}>
          {view?.apiKeySet ? "Key 已保存" : "未保存 Key"}
        </span>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}
      {testResult && (
        <Banner kind={testResult.ok ? "ok" : "error"}>
          {testResult.ok
            ? `连接正常 · ${String(testResult.reply ?? "")} · ${String(
                testResult.latency_ms ?? "",
              )} ms`
            : `连接失败：${String(testResult.error ?? "未知错误")}`}
        </Banner>
      )}

      <Actions>
        <button onClick={() => void save()} disabled={busy}>
          {busy ? "保存中…" : "保存"}
        </button>
        <button className="ghost" onClick={() => void test()} disabled={testing || !connected}>
          {testing ? "测试中…" : "测试连接"}
        </button>
        <span className="grow" />
        {!connected && <span className="muted">引擎未连接，测试不可用</span>}
      </Actions>
      {(busy || testing) && <Spinner label="正在与 LLM 配置交互…" />}
      <p className="hint">
        测试调用引擎的 /api/v1/dev/llm/test，只在 DEV_TOOLS_ENABLED=true 的本机部署中可用。
      </p>
      <p className="hint">
        mock 模式只用于联调，回答会带 [MOCK] 前缀；生产环境请关闭。
      </p>
      <p className="hint">
        修改或删除 Key 后，本机引擎会尽力即时应用；若引擎已在运行且未生效，请在部署助手里重启引擎。
      </p>
    </section>
  );
}
