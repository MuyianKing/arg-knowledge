# 架构与目录结构

## 1. 目标

- 前后端分离：后端只提供 JSON API，不托管前端静态页。
- 引擎只做 RAG：不实现用户、登录、API Key、SSO、管理后台。
- 检索、重排、生成、入库四条链路解耦，便于替换模型/向量库。
- 生成 LLM 通过外部 OpenAI 兼容 API 调用；embedding/reranker 本地。
- 身份由网关注入 `X-Tenant-Id` / `X-Acl`；引擎负责数据隔离，不做鉴权。

## 2. 分层

```text
HTTP 层 (app/api)
  - 路由、读取可信身份头、参数校验、状态码、响应模型
  - 不写业务逻辑，不直接访问 Qdrant/LLM

服务层 (app/services)
  - RAG 编排、入库任务、缓存、降级
  - 事务边界、并发控制、进度上报

基础设施层 (app/core)
  - LLM 客户端、检索、重排、缓存、脱敏、可信上下文
  - 只做“能力”，不感知 HTTP

数据/流水线层 (app/ingest)
  - 解析、清洗、切分、embedding、upsert
```

依赖方向：`api → services → core/ingest`，禁止反向依赖。

## 3. 目标目录

```text
app/
  main.py
  config.py
  api/
    deps.py              # get_engine_context、get_rag_service、get_ingest_manager
    errors.py            # AppError、错误响应 envelope、exception handler
    middleware.py        # request_id、访问日志
    v1/
      __init__.py
      router.py          # 汇总 v1 路由
      ask.py             # POST /api/v1/ask
      ingest.py          # POST /api/v1/ingest/preview、POST /api/v1/ingest、GET /api/v1/jobs/{id}
      health.py          # GET /health（根路径，供 LB/探针）
  schemas/
    common.py            # ErrorResponse、Pagination
    ask.py               # AskRequest/AskResponse/Citation/Filters
    ingest.py            # IngestJobResponse、PreviewResponse
  services/
    rag.py
    ingest_jobs.py       # 内存 job store + 串行 worker
  core/
    context.py           # X-Tenant-Id / X-Acl 可信上下文
    cache.py
    llm.py
    retrieval.py
    redact.py
  ingest/
    parsers.py
    chunking.py
    pipeline.py
  eval/
    golden.py
    ragas_eval.py
tests/
  unit/
  integration/
  conftest.py
scripts/
docs/
data/
models/
```

## 4. 请求流

### 4.1 问答

```text
POST /api/v1/ask
  → get_engine_context (X-Tenant-Id / X-Acl)
  → AskRequest 校验
  → RAGService.answer
      → Cache.get
      → RetrievalService.search (dense + sparse + RRF)
      → RetrievalService.rerank
      → 拒答判断
      → LLMClient.generate (外部 OpenAI 兼容 API)
      → 引用校验、脱敏、降级
  → AskResponse
```

### 4.2 入库

```text
POST /api/v1/ingest
  → get_engine_context
  → 校验文件后缀/大小/文件名
  → 保存到 data/uploads/{job_id}/
  → IngestJobManager.submit
      → 串行 worker (asyncio.Lock)
      → asyncio.to_thread(IngestPipeline.ingest)
          → load_documents
          → chunk_documents
          → BGE-M3 dense + BM25 sparse
          → Qdrant upsert
  → 返回 job_id
GET /api/v1/jobs/{job_id}
  → 返回 status / stage / current / total / result / error
```

预览：

```text
POST /api/v1/ingest/preview
  → 保存临时文件
  → load_documents + chunk_documents（不加载模型、不写库）
  → 返回文档数、chunk 数、前 N 个 chunk
  → 清理临时目录
```

## 5. 数据模型

Qdrant collection `kb`：

- `dense`：1024 维 COSINE，INT8 标量量化，原始向量 `Memory.COLD`，量化向量 `Memory.PINNED`
- `sparse`：BM25，`modifier=IDF`
- payload：`text`、`doc_id`、`chunk_id`、`tenant_id`、`acl`、`doc_type`、`version`、`is_current`、`source`、`page_label`、`effective_date`、`chunk_index`、`content_hash`

详见 `需求.md` 9.1。

## 6. 前后端分离

- 后端不提供 `static/`、不返回 HTML；只提供 `/api/v1/*` 与 `/health`。
- CORS 通过 `CORS_ORIGINS` 白名单配置，生产禁止 `*`。
- 前端/调用方不直接面向引擎做用户认证；网关认证后注入 `X-Tenant-Id` / `X-Acl`。
- 上传接口使用 `multipart/form-data`；前端不要手动设置 `Content-Type`。
- 长任务返回 `job_id`，前端轮询 `GET /api/v1/jobs/{job_id}`。

## 7. 当前实现与目标差异

| 项目 | 当前 v0.1 | 目标 |
|---|---|---|
| 路由 | `app/api/routes.py` 的 `/health` + `app/api/v1/ask.py` 的 `/api/v1/ask` | 业务接口统一 `/api/v1/*`，`/health` 在根路径 |
| Schema | `app/api/schemas.py` 单文件 | `app/schemas/` 按领域拆分 |
| 错误响应 | FastAPI 默认 `{"detail": ...}` | 统一 `{"error": {"code", "message", "request_id"}}` |
| 请求 ID | 仅 `/api/v1/ask` 读 `X-Request-Id` | 中间件统一生成/透传 |
| 入库 | 仅 CLI `scripts/ingest.py` | `POST /api/v1/ingest` + job 轮询 |
| 前端 | 无 | 独立前端项目，后端只给 API |

迁移原则：**新功能按目标结构写；旧文件在独立重构中迁移，不和功能 PR 混合。**

## 8. 非目标

- 用户体系、登录、API Key、SSO、角色权限、管理后台
- 本地部署生成 LLM 推理框架
- 后端渲染页面 / 模板引擎
- 在 API 进程内跑长期任务队列（当前内存 job store 只适合单实例；生产接 Celery/RQ/Arq）
- 多轮对话、Agentic 多跳、GraphRAG（见 `需求.md` 1.4）
