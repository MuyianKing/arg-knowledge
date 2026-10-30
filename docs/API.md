# API 接口文档

| 项目 | 内容 |
|---|---|
| 服务 | 企业 RAG 知识库引擎 |
| 版本 | v0.2（对应 `需求.md` 引擎版 v1.0） |
| Base URL | `http://127.0.0.1:8080` |
| Swagger UI | `http://127.0.0.1:8080/docs` |
| ReDoc | `http://127.0.0.1:8080/redoc` |
| OpenAPI JSON | `http://127.0.0.1:8080/openapi.json`（本目录 `openapi.json` 为导出副本） |

> 当前已实现 `/health`、`/api/v1/ask`、`/api/v1/ingest`、`/api/v1/jobs`、`/api/v1/documents`；`DEV_TOOLS_ENABLED=true` 时额外提供 `/api/v1/dev/*` 调试接口（见第 7 节）。

---

## 1. 可信身份头

引擎不做鉴权。调用方/网关完成用户认证后，注入：

```http
X-Tenant-Id: acme
X-Acl: internal,finance
X-Request-Id: optional-client-id
```

- `X-Tenant-Id` / `X-Acl` 必填；缺失或为空返回 400。
- `X-Acl` 支持逗号分隔字符串或 JSON 数组（如 `["internal","finance"]`）。
- 请求体中的 `tenant_id` / `acl` 会被忽略。
- 引擎只在内网监听，必须由网关转发；生产禁止直接公网访问。
- 如网关到引擎网络不可信，由网关/部署层加 mTLS 或 HMAC 签名。

---

## 2. GET /health

健康检查。返回模型目录、Qdrant 状态与模型预热状态。

**响应 200**

```json
{
  "status": "ok",
  "ts": 1792560189,
  "ready": true,
  "warmup_ms": 8421,
  "warmup_on_startup": true,
  "models": {
    "bge_m3": true,
    "bge_reranker": true,
    "bm25": true
  },
  "qdrant": true
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | `ok` / `degraded` |
| `ts` | integer | Unix 时间戳 |
| `ready` | boolean | BGE-M3、reranker、BM25 是否已加载进内存 |
| `warmup_ms` | integer/null | 启动预热耗时；未启用预热时为 `null` |
| `warmup_on_startup` | boolean | 是否配置了 `WARMUP_ON_STARTUP=true` |
| `models` | object | 各模型目录是否存在 |
| `qdrant` | boolean | Qdrant 是否可达 |

---

## 3. POST /api/v1/ask

问答接口：混合检索 → 重排 → LLM 生成 → 引用校验/拒答。

**请求头**

```http
Content-Type: application/json
X-Tenant-Id: acme
X-Acl: internal,finance
X-Request-Id: optional-client-id
```

**请求体**

```json
{
  "query": "差旅报销标准是多少",
  "filters": {
    "doc_type": ["policy"],
    "version": "v2.1",
    "is_current": true,
    "effective_date_from": "2025-01-01"
  },
  "top_k": 5,
  "use_cache": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 1~4000 字符 |
| `filters` | object | 否 | 检索过滤条件 |
| `filters.doc_type` | string[] | 否 | 文档类型，any-of |
| `filters.version` | string | 否 | 精确版本 |
| `filters.is_current` | boolean | 否 | 默认 `true`，只查当前生效版本 |
| `filters.effective_date_from` | string | 否 | ISO 8601，过滤生效日期 |
| `top_k` | integer | 否 | 1~20，默认取服务配置 5 |
| `use_cache` | boolean | 否 | 默认 `true` |

**响应 200**

```json
{
  "answer": "根据制度规定，市内交通费报销上限为每日 80 元 [S1]。",
  "citations": [
    {
      "id": "S1",
      "score": 0.8732,
      "source": "差旅管理制度.md",
      "page": "12-14",
      "version": "v2.1",
      "text": "市内交通费报销上限为每日 80 元。"
    }
  ],
  "refused": false,
  "degraded": false,
  "top_score": 0.8732,
  "latency_ms": 1240,
  "retrieval_ms": 180,
  "rerank_ms": 260,
  "generation_ms": 800,
  "prompt_version": "p1",
  "model_revision": "deepseek-chat@2026-xx",
  "cached": false,
  "request_id": "req-..."
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `answer` | string | 回答正文，事实句带 `[Sx]` 引用 |
| `citations` | array | 引用详情；`id` 对应 `[Sx]` |
| `citations[].score` | number | 重排分数 |
| `citations[].source` | string/null | 来源文件 |
| `citations[].page` | string/null | 页码范围 |
| `citations[].version` | string/null | 文档版本 |
| `citations[].text` | string | 原文片段 |
| `refused` | boolean | 是否拒答 |
| `degraded` | boolean | LLM 不可用，返回的是检索片段而非生成答案 |
| `top_score` | number/null | 重排最高分 |
| `latency_ms` | integer | 端到端耗时 |
| `retrieval_ms` | integer | 检索耗时（含 query embedding、dense/sparse、RRF） |
| `rerank_ms` | integer | 重排耗时 |
| `generation_ms` | integer | LLM 生成耗时 |
| `prompt_version` | string | Prompt 模板版本 |
| `model_revision` | string | 模型/供应商版本 |
| `cached` | boolean | 是否命中缓存 |
| `request_id` | string | 请求 ID，用于审计 |

### 3.1 拒答

以下情况返回 `refused=true`，`citations=[]`：

- 检索结果为空；
- 重排最高分低于阈值；
- 模型输出 `NO_ANSWER`；
- 上下文 token 预算不足。

```json
{
  "answer": "根据现有资料无法回答该问题。",
  "citations": [],
  "refused": true,
  "degraded": false,
  "top_score": 0.12,
  "latency_ms": 620,
  "retrieval_ms": 150,
  "rerank_ms": 240,
  "generation_ms": 0,
  "prompt_version": "p1",
  "model_revision": "deepseek-chat@2026-xx",
  "cached": false,
  "request_id": "req-..."
}
```

### 3.2 降级

第三方 LLM API 超时、5xx、熔断时，接口仍返回 200，但：

- `degraded=true`
- `answer` 为“LLM 服务暂时不可用，以下为检索到的相关片段，未生成答案。”
- `citations` 返回本次检索到的片段，供前端展示。

前端应识别 `degraded` 并提示“未生成答案”。

### 3.3 错误码

| 状态码 | 场景 | 响应 |
|---|---|---|
| 400 | 缺少/非法 `X-Tenant-Id` / `X-Acl`，或参数非法 | `{"detail": "..."}` |
| 404 | job / document 不存在或不属于当前租户 | `{"detail": "..."}` |
| 413 | 上传文件过大 | `{"detail": "..."}` |
| 422 | 请求体校验失败（query 为空、top_k 越界等） | FastAPI 标准校验错误 |
| 500 | 未处理异常 | `{"detail": "Internal Server Error"}` |
| 503 | 入库流水线未初始化 | `{"detail": "..."}` |
| 429 | 限流（规划中，尚未实现） | `{"detail": "..."}` |

---

## 4. 调用示例

### 4.1 curl（建议用文件传中文 body）

`request.json`：

```json
{
  "query": "差旅报销标准是多少",
  "top_k": 5
}
```

```bash
curl -X POST http://127.0.0.1:8080/api/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: acme" \
  -H "X-Acl: internal" \
  --data-binary @request.json
```

> 不建议在 Git Bash 里直接用 `-d '{"query":"中文"}'`，部分终端会破坏 UTF-8，导致 400/422。

### 4.2 Python

```bash
.venv/Scripts/python.exe scripts/ask.py "差旅报销标准是多少"
```

或：

```python
import httpx

response = httpx.post(
    "http://127.0.0.1:8080/api/v1/ask",
    headers={"X-Tenant-Id": "acme", "X-Acl": "internal"},
    json={"query": "差旅报销标准是多少", "top_k": 5},
    timeout=60,
)
print(response.json())
```

---

## 5. 入库与任务

### 5.1 POST /api/v1/ingest

上传文件并提交**异步入库任务**。接口立即返回 `job_id`，解析、切分、向量化、写入 Qdrant 在后台执行。

**请求头**

```http
X-Tenant-Id: acme
X-Acl: internal,finance
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 后缀必须在支持列表内，大小受 `MAX_UPLOAD_MB` 限制 |
| `version` | string | 否 | 默认 `v1` |
| `doc_type` | string | 否 | 默认 `auto` |
| `effective_date` | string | 否 | `YYYY-MM-DD` |

**响应 202**

```json
{"job_id": "8f3a...", "status": "queued"}
```

任务状态：`queued` → `running` → `succeeded` / `failed`。同一进程内串行执行入库，避免重复加载模型和并发写库。

### 5.2 GET /api/v1/jobs/{job_id}

需要可信身份头；只能查询本租户的任务，否则返回 404。

```json
{
  "id": "8f3a...",
  "status": "running",
  "stage": "embedding",
  "filename": "差旅管理制度.md",
  "tenant_id": "acme",
  "acl": ["internal"],
  "version": "v1",
  "doc_type": "policy",
  "effective_date": "2025-01-01",
  "created_at": "2026-10-29T08:00:00+00:00",
  "started_at": "2026-10-29T08:00:01+00:00",
  "finished_at": null,
  "documents": 0,
  "chunks": 0,
  "upserted": 0,
  "error": null,
  "progress": {"stage": "embedding", "current": 12, "total": 40}
}
```

`progress` 在任务结束后为 `null`。`error` 最多保留 500 字符。

### 5.3 GET /api/v1/jobs

最近任务列表，按提交时间倒序。查询参数 `limit`（1~100，默认 20）。只返回本租户任务。

```json
{"items": [{"id": "...", "status": "succeeded", "...": "..."}]}
```

> 任务历史在内存中，默认保留最近 100 条；引擎重启后历史丢失，但已入库数据不受影响。多实例部署需要把 job store 换成 Redis/数据库。

### 5.4 CLI 入库

也可以继续用命令行批量入库：

```bash
.venv/Scripts/python.exe scripts/ingest.py \
  --path ./data \
  --tenant acme \
  --acl internal \
  --version v1 \
  --doc-type auto
```

参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `--path` | 是 | 文件或目录 |
| `--tenant` | 是 | 租户 ID |
| `--acl` | 否 | 逗号分隔，默认 `internal` |
| `--version` | 否 | 默认 `v1` |
| `--effective-date` | 否 | `YYYY-MM-DD` |
| `--doc-type` | 否 | `auto` 或指定类型 |
| `--batch-size` | 否 | 默认 64 |
| `--dry-run` | 否 | 只解析/切分，不写 Qdrant |

---

## 6. 文档管理

### 6.1 GET /api/v1/documents

按 tenant/acl 过滤，把 chunk 聚合成文档行。需要可信身份头。

| 参数 | 默认 | 说明 |
|---|---|---|
| `version` | — | 精确版本 |
| `doc_type` | — | 文档类型 |
| `is_current` | 全部 | `true`/`false`；不传则包含历史版本 |
| `max_points` | 5000 | 最多扫描的 chunk 数，1~50000 |

```json
{
  "items": [
    {
      "doc_id": "3f9c...",
      "source": "差旅管理制度.md",
      "version": "v1",
      "doc_type": "policy",
      "effective_date": "2025-01-01T00:00:00",
      "is_current": true,
      "acl": ["internal"],
      "chunks": 12
    }
  ],
  "scanned_chunks": 12,
  "truncated": false
}
```

`truncated=true` 表示达到 `max_points` 后仍有未扫描数据；大规模知识库建议提高上限或改用分页/独立元数据表。

### 6.2 DELETE /api/v1/documents/{doc_id}

删除该文档在本租户、调用方 ACL 可见范围内的全部 chunk，并清理答案缓存。

```json
{"doc_id": "3f9c...", "deleted_chunks": 12}
```

不存在或不可见时返回 404。

### 6.3 缓存失效

入库任务成功和文档删除都会清理 `rag:answer:*` 缓存，避免旧答案在文档变更后继续返回。

---

## 7. 本地调试接口（仅 `DEV_TOOLS_ENABLED=true`）

以下接口用于本地联调，**不属于引擎对外契约**，生产环境必须保持 `DEV_TOOLS_ENABLED=false`（此时路由不会注册，OpenAPI 中也看不到）。桌面客户端（`desktop/`）的 LLM 配置、仅检索、上传入库页面在调试模式下使用这些接口。

### 7.1 GET /api/v1/dev/llm

查看当前 LLM 配置。API Key 只返回掩码。

```json
{
  "base_url": "https://api.deepseek.com/v1",
  "model_name": "deepseek-chat",
  "model_revision": "deepseek-chat@2026-10",
  "api_key_set": true,
  "api_key_masked": "sk-a...cdef",
  "mock": false,
  "temperature": 0.1,
  "top_p": 0.9,
  "max_tokens": 512,
  "timeout_seconds": 10,
  "circuit_open": false
}
```

### 7.2 PUT /api/v1/dev/llm

运行时更新 LLM 配置，立即重建客户端并重置熔断器。字段均可选，`api_key` 留空表示不修改。仅内存生效，重启后回退 `.env`。

```json
{
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-...",
  "model_name": "deepseek-chat",
  "model_revision": "deepseek-chat@2026-10",
  "temperature": 0.1,
  "top_p": 0.9,
  "max_tokens": 512,
  "timeout_seconds": 10,
  "mock": false
}
```

响应同 7.1。`base_url` 必须为 `http://` 或 `https://`。

### 7.3 POST /api/v1/dev/llm/test

发送一次最小真实请求（`max_tokens=16`）验证连通性；即使 `mock=true` 也会真实调用。

```json
{
  "ok": true,
  "reply": "pong",
  "finish_reason": "stop",
  "model": "deepseek-chat",
  "latency_ms": 420
}
```

失败时返回 HTTP 200，`ok=false` 且带 `error`。

### 7.4 POST /api/v1/dev/retrieve

只做召回 + 重排，不调用 LLM。需要可信身份头。

```json
{
  "query": "市内交通费上限",
  "top_k": 5,
  "filters": {"doc_type": ["policy"], "is_current": true}
}
```

响应：

```json
{
  "chunks": [
    {
      "id": "doc_...::12",
      "score": 0.8732,
      "source": "差旅管理制度.md",
      "page": null,
      "version": "v1",
      "text": "市内交通费报销上限为每日 80 元。"
    }
  ],
  "candidates": 50,
  "retrieval_ms": 180,
  "rerank_ms": 260,
  "latency_ms": 445
}
```

### 7.5 POST /api/v1/dev/ingest

同步上传并入库（`multipart/form-data`）。需要可信身份头；租户/ACL 只从请求头读取。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 后缀必须在支持列表内，大小受 `MAX_UPLOAD_MB` 限制 |
| `version` | string | 否 | 默认 `v1` |
| `doc_type` | string | 否 | 默认 `auto` |
| `effective_date` | string | 否 | `YYYY-MM-DD` |
| `dry_run` | boolean | 否 | 只解析/切分，不加载模型、不写库 |

```json
{
  "filename": "差旅管理制度.md",
  "tenant_id": "acme",
  "acl": ["internal"],
  "version": "v1",
  "doc_type": "auto",
  "dry_run": false,
  "documents": 1,
  "chunks": 5,
  "upserted": 5,
  "elapsed_ms": 4200
}
```

> 这是同步接口，用于本地调试；生产入库仍应使用 `需求.md` 定义的异步 job 接口。

---

## 8. 版本与兼容

- `prompt_version`：Prompt 模板版本，变更 prompt 必须递增。
- `model_revision`：模型/供应商版本；第三方 API 建议写 `provider/model@version`。
- 业务接口统一 `/api/v1`；`/health` 在根路径。
- 破坏性变更升级到 `/api/v2` 或保留兼容别名。
