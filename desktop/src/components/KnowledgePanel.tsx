import { useCallback, useEffect, useState } from "react";

import { clientApi, confirmAction, pickDocumentFile } from "../api";
import type { DocumentItem, IngestJob } from "../types";
import { Banner, Spinner, errorText } from "./ui";

const STATUS_LABEL: Record<IngestJob["status"], string> = {
  queued: "排队中",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败",
};

function statusClass(status: IngestJob["status"]): string {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "error";
  if (status === "running") return "warn";
  return "";
}

export default function KnowledgePanel({
  connected,
  onConnect,
}: {
  connected: boolean;
  onConnect: () => void;
}) {
  const [filePath, setFilePath] = useState<string | null>(null);
  const [version, setVersion] = useState("v1");
  const [docType, setDocType] = useState("auto");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [jobs, setJobs] = useState<IngestJob[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!connected) return;
    try {
      const [jobList, documentList] = await Promise.all([
        clientApi.listJobs(30),
        clientApi.listDocuments(),
      ]);
      setJobs(jobList.items);
      setDocuments(documentList.items);
    } catch (err) {
      setError(errorText(err));
    }
  }, [connected]);

  useEffect(() => {
    void refresh();
    if (!connected) return;
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [connected, refresh]);

  const chooseFile = async () => {
    const selected = await pickDocumentFile();
    if (selected) setFilePath(selected);
  };

  const upload = async () => {
    if (!filePath) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const job = await clientApi.submitIngest(
        filePath,
        version.trim() || "v1",
        docType.trim() || "auto",
        effectiveDate.trim() || null,
      );
      setNotice(`已提交入库任务 ${job.job_id.slice(0, 8)}…`);
      setFilePath(null);
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (doc: DocumentItem) => {
    const label = doc.source ?? doc.doc_id;
    const confirmed = await confirmAction(
      `删除文档「${label}」及其全部 chunk？`,
      "确认删除",
    );
    if (!confirmed) return;
    setDeleting(doc.doc_id);
    setError(null);
    try {
      const result = await clientApi.deleteDocument(doc.doc_id);
      setNotice(`已删除 ${label}，共 ${result.deleted_chunks} 个 chunk`);
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>知识库</h1>
          <p>上传文档、查看入库任务、删除文档。所有操作都通过引擎 HTTP 接口完成。</p>
        </div>
        <button className="ghost small" onClick={() => void refresh()} disabled={!connected}>
          刷新
        </button>
      </header>

      {!connected && (
        <Banner kind="warn">
          当前没有连接到引擎，知识库不可用。
          <button className="link inline" onClick={onConnect} type="button">
            配置连接
          </button>
        </Banner>
      )}

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      <section className="card">
        <h2>上传文档</h2>
        <p className="muted">
          支持 md / txt / pdf / docx / html / csv / xlsx / pptx。上传后由后台异步解析、切分、向量化。
        </p>
        <div className="upload-row">
          <button className="ghost" onClick={() => void chooseFile()} disabled={!connected || busy}>
            选择文件
          </button>
          <code className="file-path">{filePath ?? "未选择文件"}</code>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>version</span>
            <input value={version} onChange={(event) => setVersion(event.target.value)} />
          </label>
          <label className="field">
            <span>doc_type</span>
            <input
              value={docType}
              placeholder="auto"
              onChange={(event) => setDocType(event.target.value)}
            />
          </label>
          <label className="field">
            <span>生效日期（可选）</span>
            <input
              type="date"
              value={effectiveDate}
              onChange={(event) => setEffectiveDate(event.target.value)}
            />
          </label>
        </div>
        <div className="actions">
          <button onClick={() => void upload()} disabled={!connected || busy || !filePath}>
            {busy ? "提交中…" : "上传并入库"}
          </button>
          {busy && <Spinner label="正在上传…" />}
        </div>
      </section>

      <section className="card">
        <h2>入库任务</h2>
        {jobs.length === 0 ? (
          <p className="muted">还没有任务。</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件</th>
                  <th>状态</th>
                  <th>阶段</th>
                  <th>chunk</th>
                  <th>耗时</th>
                  <th>错误</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{job.filename}</td>
                    <td>
                      <span className={`pill ${statusClass(job.status)}`}>
                        {STATUS_LABEL[job.status]}
                      </span>
                    </td>
                    <td>
                      {job.progress
                        ? `${job.progress.stage} ${job.progress.current}/${job.progress.total}`
                        : job.stage}
                    </td>
                    <td>{job.chunks}</td>
                    <td>{job.finished_at ? new Date(job.finished_at).toLocaleTimeString() : "—"}</td>
                    <td className="danger-text">{job.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h2>文档列表</h2>
        {documents.length === 0 ? (
          <p className="muted">知识库为空，先上传一份文档。</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>来源</th>
                  <th>版本</th>
                  <th>类型</th>
                  <th>ACL</th>
                  <th>chunk</th>
                  <th>生效日期</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.doc_id}>
                    <td title={doc.doc_id}>{doc.source ?? doc.doc_id}</td>
                    <td>{doc.version ?? "—"}</td>
                    <td>{doc.doc_type ?? "—"}</td>
                    <td>{doc.acl.join(", ")}</td>
                    <td>{doc.chunks}</td>
                    <td>{doc.effective_date?.slice(0, 10) ?? "—"}</td>
                    <td>
                      <button
                        className="danger-link"
                        onClick={() => void remove(doc)}
                        disabled={deleting === doc.doc_id}
                      >
                        {deleting === doc.doc_id ? "删除中…" : "删除"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
