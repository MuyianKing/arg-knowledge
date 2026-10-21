# Python / FastAPI 编码规范

## 1. 基本规则

- Python ≥ 3.10；文件头统一 `from __future__ import annotations`。
- 行宽 100；`ruff format` 负责格式，`ruff check` 负责 lint。
- 所有公共函数/方法写类型标注；禁止 `Any` 滥用，确实需要时注明原因。
- 使用绝对导入：`from app.core.llm import LLMClient`，禁止相对导入跨包。
- 禁止 `from x import *`。
- 命名：
  - 模块/函数/变量：`snake_case`
  - 类/Pydantic 模型：`PascalCase`
  - 常量：`UPPER_SNAKE_CASE`
  - 请求模型：`XxxRequest`；响应模型：`XxxResponse`；内部领域对象：`Xxx` 或 `XxxResult`
- 注释只解释“为什么/约束”，不解释“这行在干什么”。

## 2. 路由层（app/api）

- 一个领域一个 router；新业务接口统一放 `app/api/v1/`。
- 路由函数只做：读取可信上下文、参数校验、调用 service、返回 response model。
- 禁止在路由里直接：
  - 调 Qdrant / Redis / LLM SDK
  - 写文件、跑 embedding、做重排
  - 拼接 SQL/过滤器
- 必须声明 `response_model`、`status_code`、`summary`、`tags`。
- 业务接口统一前缀 `/api/v1`；`/health` 放根路径；`/docs`、`/openapi.json` 保留。
- 路由函数命名：`ask`、`preview_ingest`、`submit_ingest`、`get_job`。

```python
# 好
@router.post(
    "/api/v1/ask",
    response_model=AskResponse,
    status_code=status.HTTP_200_OK,
    summary="知识库问答",
    tags=["ask"],
)
async def ask(
    body: AskRequest,
    context: EngineContext = Depends(get_engine_context),
    service: RAGService = Depends(get_rag_service),
) -> AskResponse:
    return await service.answer(body, identity)
```

```python
# 坏：路由里直接调 Qdrant/LLM
@router.post("/api/v1/ask")
async def ask(body: dict):
    vector = embed(body["query"])
    points = qdrant.search(...)
    return llm.generate(...)
```

## 3. Schema 层（app/schemas）

- 请求/响应模型与领域对象分离；不要让 Qdrant payload、ORM 对象直接当 response。
- 使用 Pydantic v2：
  - `Field(..., min_length=1, max_length=4000)` 做边界校验
  - `model_config = ConfigDict(extra="ignore")` 用于兼容旧字段；需要严格拒绝未知字段时用 `"forbid"`
  - 响应模型默认 `extra="ignore"`，避免内部字段泄漏
- 枚举用 `str, Enum`；日期用 `date`/`datetime`，不要用裸字符串。
- 字段命名与 API 文档一致；内部字段不要暴露（如原始向量、完整 prompt）。

```python
class AskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
```

## 4. 依赖注入

- 可信上下文、service、配置通过 `Depends` 注入，不在路由里 new。
- 单例（Qdrant client、LLM client、job manager）在 `lifespan` 初始化，挂到 `app.state`。
- 依赖函数放 `app/api/deps.py`，命名 `get_xxx`。
- 禁止在依赖里做重初始化（每次请求加载模型）。

```python
async def get_rag_service(request: Request) -> RAGService:
    return request.app.state.rag
```

## 5. 异步规则

- 路由、service 默认 `async def`。
- 任何阻塞调用必须放到 `asyncio.to_thread` / `run_in_executor`：
  - 模型加载、embedding、rerank、同步 Qdrant 客户端
  - 文件读写（大文件）
- I/O 客户端优先用异步版本：`AsyncQdrantClient`、`redis.asyncio`、`httpx.AsyncClient`。
- 禁止在 async 函数里调用 `time.sleep`、同步 `requests`、同步 `QdrantClient`。
- 并发用 `asyncio.gather` / `Semaphore`；不要无界创建 task。
- 入库这类 CPU 密集长任务：提交到 job manager，串行/有界执行，不阻塞请求。

## 6. 错误处理

- 统一错误响应：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "query must not be empty",
    "request_id": "req-..."
  }
}
```

- 定义异常层级：`AppError` → `ValidationError` / `AuthError` / `NotFoundError` / `ConflictError` / `ExternalServiceError`。
- 在 `app/api/errors.py` 注册 exception handler；不要在路由里到处 `try/except` 拼 JSON。
- 不向客户端泄漏堆栈、SQL、内部路径、密钥。
- 外部依赖失败：
  - LLM 超时/5xx → 重试 + 熔断；熔断后返回 `degraded=true` + 检索片段。
  - Qdrant 不可用 → 503 或缓存结果；不得返回空答案冒充成功。
- 日志记录 `request_id` + 异常类型；不记录完整 prompt/文档原文（除非已脱敏）。

## 7. 状态码

| 场景 | 状态码 |
|---|---|
| 成功查询/入库任务已创建 | 200 / 202 |
| 参数校验失败 | 422 |
| 未认证 | 401 |
| 无权限 | 403 |
| 资源不存在 | 404 |
| 冲突（重复任务/版本） | 409 |
| 上传过大 | 413 |
| 限流 | 429 |
| 外部依赖不可用 | 502/503（LLM 降级用 200 + `degraded=true`） |

## 8. 可信上下文与多租户

- 引擎**不做鉴权**：不实现用户、登录、JWT、API Key、SSO、管理后台。
- `tenant_id` / `acl` 只从网关注入的 `X-Tenant-Id` / `X-Acl` 读取；请求体同名字段忽略。
- 缺少 `X-Tenant-Id` / `X-Acl` 直接 400，不得默认放行。
- 引擎只在内网监听；认证、限流、审计由网关负责。
- 任何查询都必须带 tenant 过滤，ACL 用 any-of；禁止“先查全量再过滤”。
- 缓存 key 必须含 `tenant_id + acl + query + filters + top_k + prompt_version + model_revision`。
- 文件上传必须校验后缀、大小、文件名；禁止路径穿越（`Path(name).name`）。

## 9. 文件上传

- 使用 `UploadFile` + `Form`；依赖 `python-multipart`。
- 限制：
  - 后缀白名单（`app/ingest/parsers.py: SUPPORTED_EXTENSIONS`）
  - 单文件大小 `MAX_UPLOAD_MB`
  - 文件名 `Path(filename).name`
- 每个 job 一个目录：`data/uploads/{job_id}/`；任务结束按保留策略清理。
- 上传只负责落盘和创建 job；解析/切分/embedding 在后台 worker。
- 预览接口可以同步解析/切分，但不得加载模型或写 Qdrant。

## 10. 后台任务与 Job

- 当前使用内存 `IngestJobManager` + `asyncio.Lock` 串行执行；只适合单实例。
- 生产建议 Celery/RQ/Arq + Redis；接口契约不变。
- Job 状态：`queued` → `running` → `completed` / `failed`。
- 必须暴露：`job_id`、`status`、`stage`、`current`、`total`、`result`、`error`、时间戳。
- 任务异常必须落 `error`，不能只打印日志。

## 11. 日志与可观测

- 每个请求生成/透传 `X-Request-Id`，写入日志和错误响应。
- 结构化日志字段：`request_id`、`tenant_id`、`path`、`status_code`、`latency_ms`、`model_revision`、`prompt_version`。
- 不记录：完整文档原文、完整 prompt、凭证、未脱敏 PII。
- 关键指标：检索/重排/生成耗时、token 用量、拒答率、引用有效率、入库吞吐、job 失败率。

## 12. 配置

- 全部走 `app/config.py` 的 `Settings` + 环境变量；禁止散落 `os.getenv`。
- 新增配置必须同步 `.env.example`。
- 密钥只从环境变量/密钥管理读取；不得有默认生产密钥。
- 配置项命名：`UPPER_SNAKE_CASE` 环境变量，映射到 `snake_case` 字段。

## 13. 测试

- `tests/unit/`：纯函数、schema、错误处理、缓存 key、脱敏、chunking。
- `tests/integration/`：FastAPI + `httpx.ASGITransport`；mock LLM/Qdrant，不打真实网络。
- 外部依赖用 fake/协议类替换（参考 `tests/test_rag_degraded.py`）。
- 每个新接口至少覆盖：成功、参数错误、缺少 tenant/acl。
- 测试不得依赖本地模型、Qdrant、Redis 是否启动。
- 异步测试用 `pytest-asyncio`（`asyncio_mode = "auto"`）。

## 14. OpenAPI 与文档

- 新接口必须写 `summary`、`description`、`response_model`、错误码。
- `docs/API.md` 与代码同步；OpenAPI 由 FastAPI 自动生成，不要手写冲突的 schema。
- 破坏性变更必须升级路径版本（`/api/v2`）或保留兼容别名。

## 15. Git / PR

- 一个 PR 只做一件事；功能改动不和目录重构混合。
- 提交信息：`feat: ...`、`fix: ...`、`refactor: ...`、`docs: ...`、`test: ...`。
- PR 必须包含：
  - 变更说明与影响范围
  - 测试结果
  - API/文档更新
  - 安全影响（tenant/acl、上传、外部 LLM API）
- 不提交生成物：`models/`、`data/`、`logs/`、`qdrant_storage/`、`.venv/`、`tools/`。

## 16. 常用反模式

- ❌ 路由里直接 `QdrantClient(...)` / `openai.OpenAI(...)`
- ❌ 在 async 路由里 `time.sleep` / 同步 `requests`
- ❌ 用 `dict` 当请求/响应模型
- ❌ 在引擎里实现登录/API Key/用户体系
- ❌ 把 `tenant_id` 从 body 读取
- ❌ 上传文件名直接拼路径
- ❌ 外部依赖异常直接 500 且无日志
- ❌ 缓存 key 不含租户/ACL
- ❌ 把完整文档/向量发给第三方 LLM
