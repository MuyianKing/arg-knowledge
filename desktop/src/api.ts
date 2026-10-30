import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { ask, open } from "@tauri-apps/plugin-dialog";
import { openUrl } from "@tauri-apps/plugin-opener";

import type {
  AppSettings,
  AskResponse,
  ConnectionReport,
  DocumentList,
  IngestJob,
  JobList,
  LlmSettings,
  ModelReport,
  Paths,
  PythonReport,
  RuntimeReport,
  ServiceStatus,
  SetupLog,
  SystemReport,
} from "./types";

/**
 * Client side: everything here treats the engine as a remote HTTP service.
 * It knows nothing about how (or where) the engine is deployed.
 */
export const clientApi = {
  probeConnection: (baseUrl?: string, tenantId?: string, acl?: string) =>
    invoke<ConnectionReport>("probe_connection", {
      baseUrl: baseUrl ?? null,
      tenantId: tenantId ?? null,
      acl: acl ?? null,
    }),
  health: () => invoke<unknown>("engine_health"),
  ask: (
    query: string,
    topK: number,
    useCache: boolean,
    filters?: Record<string, unknown> | null,
  ) =>
    invoke<AskResponse>("ask_engine", {
      query,
      topK,
      useCache,
      filters: filters ?? null,
    }),
  submitIngest: (
    filePath: string,
    version: string,
    docType: string,
    effectiveDate: string | null,
  ) =>
    invoke<{ job_id: string; status: string }>("submit_ingest", {
      filePath,
      version,
      docType,
      effectiveDate,
    }),
  listJobs: (limit = 20) => invoke<JobList>("list_jobs", { limit }),
  getJob: (jobId: string) => invoke<IngestJob>("get_job", { jobId }),
  listDocuments: (maxPoints = 5000) => invoke<DocumentList>("list_documents", { maxPoints }),
  deleteDocument: (docId: string) =>
    invoke<{ doc_id: string; deleted_chunks: number }>("delete_document", { docId }),
};

export const llmApi = {
  get: () => invoke<LlmSettings>("get_llm_settings"),
  save: (settings: {
    baseUrl: string;
    modelName: string;
    modelRevision: string;
    temperature: number;
    maxTokens: number;
    mock: boolean;
    apiKey: string | null;
    clearKey: boolean;
  }) => invoke<LlmSettings>("save_llm_settings", { settings }),
  test: () => invoke<Record<string, unknown>>("test_llm"),
};

/**
 * Deployment assistant: probes the local machine, installs the runtime and
 * supervises the local engine. Only used by the "deploy backend locally" flow.
 */
export const deployApi = {
  paths: () => invoke<Paths>("paths"),
  probeSystem: () => invoke<SystemReport>("probe_system"),
  probePython: (customPath?: string | null) =>
    invoke<PythonReport>("probe_python", { customPath: customPath ?? null }),
  probeRuntime: () => invoke<RuntimeReport>("probe_runtime"),
  probeModels: () => invoke<ModelReport>("probe_models"),
  probeServices: () => invoke<ServiceStatus>("probe_services"),
  installRuntime: (pythonPath: string, torchProfile: "cuda" | "cpu", indexUrl?: string) =>
    invoke<RuntimeReport>("install_runtime", {
      pythonPath,
      torchProfile,
      indexUrl: indexUrl ?? null,
    }),
  startQdrant: () => invoke<ServiceStatus>("start_qdrant"),
  initCollection: () => invoke<string>("init_collection"),
  startEngine: () => invoke<ServiceStatus>("start_engine"),
  stopService: (service: "qdrant" | "engine") => invoke<ServiceStatus>("stop_service", { service }),
  logTail: (service: "qdrant" | "engine", lines = 80) =>
    invoke<string>("read_log_tail", { service, lines }),
  downloadModels: (mirror?: string | null) =>
    invoke<ModelReport>("download_models", { mirror: mirror ?? null }),
  importModels: (source: string) => invoke<ModelReport>("import_models", { source }),
  onLog: (handler: (log: SetupLog) => void): Promise<UnlistenFn> =>
    listen<SetupLog>("setup-log", (event) => handler(event.payload)),
};

export const settingsApi = {
  get: () => invoke<AppSettings>("get_settings"),
  save: (settings: AppSettings) => invoke<AppSettings>("save_settings", { settings }),
};

export function openExternal(url: string): Promise<void> {
  return openUrl(url);
}

export async function pickDocumentFile(): Promise<string | null> {
  const selected = await open({
    multiple: false,
    directory: false,
    filters: [
      {
        name: "知识库文档",
        extensions: ["md", "txt", "pdf", "docx", "html", "csv", "xlsx", "pptx"],
      },
    ],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickDirectory(): Promise<string | null> {
  const selected = await open({ multiple: false, directory: true });
  return typeof selected === "string" ? selected : null;
}

export function confirmAction(message: string, title = "确认"): Promise<boolean> {
  return ask(message, { title, kind: "warning" });
}
