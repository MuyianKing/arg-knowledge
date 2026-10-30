export type CheckStatus = "ok" | "warn" | "error";

export interface Check {
  key: string;
  label: string;
  status: CheckStatus;
  detail: string;
  required: boolean;
}

export interface ConnectionReport {
  baseUrl: string;
  ok: boolean;
  reachable: boolean;
  status: string | null;
  ready: boolean | null;
  warmupMs: number | null;
  latencyMs: number;
  error: string | null;
  health: unknown | null;
}

export interface SystemReport {
  os: string;
  arch: string;
  osVersion: string;
  ramTotalMb: number;
  diskFreeMb: number;
  webview2: string;
  gpus: GpuInfo[];
  checks: Check[];
  pass: boolean;
}

export interface GpuInfo {
  name: string;
  driver: string;
  memoryMb: number;
}

export interface PythonCandidate {
  command: string;
  path: string;
  version: string;
  bits: number;
  ok: boolean;
  error: string | null;
}

export interface PythonReport {
  candidates: PythonCandidate[];
  selected: string | null;
  checks: Check[];
  pass: boolean;
}

export interface RuntimeReport {
  venvPython: string;
  venvExists: boolean;
  torch: string | null;
  cuda: boolean;
  cudaDevice: string | null;
  depsOk: boolean;
  depsError: string | null;
  checks: Check[];
  pass: boolean;
}

export interface ModelIssue {
  path: string;
  size: number;
  minimum: number;
}

export interface ModelReport {
  modelRoot: string;
  checked: number;
  totalBytes: number;
  missing: string[];
  truncated: ModelIssue[];
  checks: Check[];
  pass: boolean;
}

export interface ServiceStatus {
  qdrantBinary: string | null;
  qdrantRunning: boolean;
  qdrantPort: number;
  engineRunning: boolean;
  enginePort: number;
  engineHealth: unknown | null;
  checks: Check[];
}

export interface AppSettings {
  /** Client -> engine HTTP endpoint. Decoupled from where the engine runs. */
  baseUrl: string;
  tenantId: string;
  acl: string;
  /** Local deployment assistant settings. Unused when connecting to a remote engine. */
  engineRoot: string | null;
  pythonPath: string | null;
  modelRoot: string | null;
  enginePort: number;
  qdrantHttpPort: number;
  qdrantGrpcPort: number;
  setupCompleted: boolean;
  llmBaseUrl: string;
  llmModelName: string;
  llmModelRevision: string;
  llmTemperature: number;
  llmMaxTokens: number;
  llmMock: boolean;
}

export interface Citation {
  id: string;
  score: number;
  source: string | null;
  page: string | null;
  version: string | null;
  text: string;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  refused: boolean;
  degraded: boolean;
  top_score: number | null;
  latency_ms: number;
  retrieval_ms: number;
  rerank_ms: number;
  generation_ms: number;
  prompt_version: string;
  model_revision: string;
  cached: boolean;
  request_id: string;
}

export interface JobProgress {
  stage: string;
  current: number;
  total: number;
}

export interface IngestJob {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  filename: string;
  tenant_id: string;
  acl: string[];
  version: string;
  doc_type: string;
  effective_date: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  documents: number;
  chunks: number;
  upserted: number;
  error: string | null;
  progress: JobProgress | null;
}

export interface JobList {
  items: IngestJob[];
}

export interface DocumentItem {
  doc_id: string;
  source: string | null;
  version: string | null;
  doc_type: string | null;
  effective_date: string | null;
  is_current: boolean;
  acl: string[];
  chunks: number;
}

export interface DocumentList {
  items: DocumentItem[];
  scanned_chunks: number;
  truncated: boolean;
}

export interface LlmSettings {
  baseUrl: string;
  modelName: string;
  modelRevision: string;
  temperature: number;
  maxTokens: number;
  mock: boolean;
  apiKeySet: boolean;
}

export interface Paths {
  home: string;
  engine: string | null;
  venv: string;
  models: string;
  logs: string;
  qdrantStorage: string;
}

export interface SetupLog {
  step: string;
  line: string;
}
