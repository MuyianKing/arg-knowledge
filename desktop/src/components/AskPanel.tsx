import { useState } from "react";

import { clientApi } from "../api";
import type { AskResponse } from "../types";
import { Banner, Spinner, errorText } from "./ui";

export default function AskPanel({
  connected,
  onConnect,
}: {
  connected: boolean;
  onConnect: () => void;
}) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [useCache, setUseCache] = useState(true);
  const [docType, setDocType] = useState("");
  const [version, setVersion] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AskResponse | null>(null);

  const submit = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const filters: Record<string, unknown> = {};
      if (docType.trim()) filters.doc_type = [docType.trim()];
      if (version.trim()) filters.version = version.trim();
      const value = await clientApi.ask(
        query.trim(),
        topK,
        useCache,
        Object.keys(filters).length > 0 ? filters : null,
      );
      setResponse(value);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>知识库问答</h1>
          <p>混合检索 → 重排 → 引用生成。回答中的 [Sx] 对应下方引用。</p>
        </div>
      </header>

      {!connected && (
        <Banner kind="warn">
          当前没有连接到引擎，问答不可用。
          <button className="link inline" onClick={onConnect} type="button">
            配置连接
          </button>
        </Banner>
      )}

      <section className="card">
        <label className="field">
          <span>问题</span>
          <textarea
            rows={3}
            value={query}
            placeholder="例如：差旅报销标准是多少？"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                void submit();
              }
            }}
          />
        </label>
        <div className="row">
          <label className="field tiny">
            <span>top_k</span>
            <input
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value) || 5)}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={useCache}
              onChange={(event) => setUseCache(event.target.checked)}
            />
            使用缓存
          </label>
          <button className="link" onClick={() => setAdvanced((value) => !value)} type="button">
            {advanced ? "收起过滤" : "高级过滤"}
          </button>
          <span className="grow" />
          <button
            onClick={() => void submit()}
            disabled={busy || !connected || !query.trim()}
          >
            {busy ? "生成中…" : "提问"}
          </button>
        </div>

        {advanced && (
          <div className="two-col">
            <label className="field">
              <span>doc_type</span>
              <input
                value={docType}
                placeholder="policy"
                onChange={(event) => setDocType(event.target.value)}
              />
            </label>
            <label className="field">
              <span>version</span>
              <input
                value={version}
                placeholder="v1"
                onChange={(event) => setVersion(event.target.value)}
              />
            </label>
          </div>
        )}

        {error && <Banner kind="error">{error}</Banner>}
        {busy && <Spinner label="检索、重排并生成回答…" />}
      </section>

      {response && (
        <section className="card answer-card">
          <div className="answer-meta">
            <span className={`pill ${response.refused ? "warn" : "ok"}`}>
              {response.refused ? "已拒答" : response.degraded ? "降级回答" : "已回答"}
            </span>
            {response.cached && <span className="pill">缓存命中</span>}
            <span className="muted">
              总耗时 {response.latency_ms} ms · 检索 {response.retrieval_ms} ms · 重排{" "}
              {response.rerank_ms} ms · 生成 {response.generation_ms} ms
            </span>
          </div>
          <div className={`answer ${response.degraded ? "degraded" : ""}`}>
            {response.answer}
          </div>
          {response.citations.length > 0 && (
            <div className="citations">
              <h3>引用</h3>
              {response.citations.map((citation) => (
                <article className="citation" key={citation.id}>
                  <div className="citation-head">
                    <strong>[{citation.id}]</strong>
                    <span>{citation.source ?? "未知来源"}</span>
                    {citation.page && <span className="muted">第 {citation.page} 页</span>}
                    {citation.version && <span className="muted">{citation.version}</span>}
                    <span className="grow" />
                    <span className="muted">{citation.score.toFixed(4)}</span>
                  </div>
                  <p>{citation.text}</p>
                </article>
              ))}
            </div>
          )}
          <p className="hint">
            prompt {response.prompt_version} · model {response.model_revision} · request{" "}
            {response.request_id}
          </p>
        </section>
      )}
    </div>
  );
}
