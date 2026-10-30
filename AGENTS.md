# 项目约束与协作说明

本文件是项目级约束。改代码前先读：

1. `需求.md` — 产品与验收标准
2. `docs/ARCHITECTURE.md` — 分层、目录、数据流
3. `docs/CONVENTIONS.md` — Python/FastAPI 编码规范
4. `docs/API.md` — 已实现接口

## 1. 项目定位

企业 RAG 知识库**引擎**（无状态，不实现用户/登录/API Key/SSO/管理后台）：

- 检索：BGE-M3 dense + jieba/BM25 sparse + Qdrant RRF + BGE reranker
- 生成：外部 OpenAI 兼容 API（不在本地部署推理框架）
- 身份：网关注入 `X-Tenant-Id` / `X-Acl`；引擎只做数据隔离，不做鉴权
- 服务：FastAPI，前后端分离，后端只返回 JSON，不托管前端静态页
- 存储：Qdrant 1.19+、Redis 7
- 评估：golden set + RAGAS + CI 门禁（待实现）

## 2. 环境与命令

```bash
# 创建环境
uv venv --python 3.12 .venv
# Windows 上 PyPI 默认的 torch 是 CPU 轮子，embedding/rerank 会退化为 CPU。
# 必须装 CUDA 轮子（驱动 561.x 对应 cu126），装完验证输出 True。
uv pip install --python .venv/Scripts/python.exe \
  --index-url https://download.pytorch.org/whl/cu126 torch
.venv/Scripts/python.exe -c "import torch; print(torch.cuda.is_available())"
uv pip install --python .venv/Scripts/python.exe -r requirements.txt

# 测试
.venv/Scripts/python.exe -m pytest

# 静态检查
.venv/Scripts/python.exe -m ruff check app tests scripts
.venv/Scripts/python.exe -m ruff format --check app tests scripts

# 启动 Qdrant（本机 Windows 版）
QDRANT__STORAGE__STORAGE_PATH=./runtime/qdrant_storage runtime/tools/qdrant/qdrant.exe

# 建库
.venv/Scripts/python.exe scripts/create_collection.py

# 启动 API
CACHE_ENABLED=false LLM_MOCK=true \
  .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080

# 一键启动 Qdrant + 引擎 + 桌面端（推荐）
./run.sh --mock-llm

# 桌面客户端（Tauri）
cd desktop && npm install && npm run tauri dev
cd desktop && npx tsc --noEmit && npm run build
cd desktop/src-tauri && cargo check
```

## 3. 硬性约束

- **不得提交** `.venv/`、`runtime/`、`models/`、`data/`、`tools/`、`logs/`、`qdrant_storage/`、`.env`。
- **不得把密钥写进代码/镜像/日志**；外部 LLM API Key 走环境变量或密钥管理。
- **不得默认调用公网 embedding/rerank API**。生成 LLM 走外部 OpenAI 兼容 API，按 `需求.md` 7.1：
  - 只发送 query + top-k chunk，不发送完整文档/向量；
  - `LLM_REDACT_PII=true`；
  - 出口网关白名单 + TLS；
  - 涉密/受监管数据禁用。
- **tenant_id / acl 只能来自网关注入的 `X-Tenant-Id` / `X-Acl`**，不得信任请求体。
- **引擎只在内网监听**，不得直接暴露公网；认证、API Key、限流、审计由网关负责。
- **上传文件**：限制后缀、大小、文件名，禁止路径穿越；入库任务必须可追踪（job_id）。
- **异步路由里不得调用阻塞 I/O**：CPU 密集/同步客户端用 `asyncio.to_thread`；Qdrant 用 `AsyncQdrantClient`，Redis 用 `redis.asyncio`。
- **不得绕过** `app/core/context.py` 直接读请求头里的租户。
- **改 API 必须同步更新** `docs/API.md` 和 OpenAPI 示例。
- **改数据模型/collection 必须同步更新** `需求.md` 9.1 和 `scripts/create_collection.py`。
- **不要修改** `runtime/models/` 下的权重文件；模型版本变更走 `需求.md` 的变更评审。

## 4. 目录约定

```text
app/
  main.py              # 应用入口、lifespan、中间件、router 注册
  config.py            # pydantic-settings
  api/                 # 路由与 HTTP 适配
    deps.py            # 依赖注入（auth、service）
    errors.py          # 异常与统一错误响应
    middleware.py      # request_id、日志
    v1/                # 新业务接口统一 /api/v1
  schemas/             # Pydantic 请求/响应模型（按领域拆分）
  services/            # 业务编排（RAG、ingest jobs）
  core/                # 基础设施（llm、retrieval、cache、redact、auth）
  ingest/              # 解析、切分、入库流水线
  eval/                # golden set、RAGAS（待实现）
tests/
  unit/
  integration/
scripts/               # CLI：一键启动、下载、建库、入库、冒烟
desktop/               # Tauri 客户端 + 本地部署助手（与引擎解耦）
docs/                  # API、架构、规范
runtime/               # 运行时数据：models/qdrant_storage/data/logs/tools（gitignore）
data/                  # 兼容旧路径（gitignore）
models/                # 兼容旧路径（gitignore）
```

当前代码是 v0.1 结构：`app/api/routes.py`、`app/api/schemas.py` 尚未拆分。**新接口必须按目标结构落到 `app/api/v1/` 和 `app/schemas/`**；旧文件在独立重构 PR 中迁移，不和功能改动混在一起。

`desktop/` 的硬性约束：

- 客户端只能通过 `baseUrl` 访问引擎，**不得**用本地进程状态推断引擎是否在线。
- 本地部署助手（检测、安装、启停进程）是独立能力，只写 `baseUrl` 和本地部署参数，不得变成客户端通信的前置条件。
- 本机后台是独立服务：关闭客户端不得停止 Qdrant/引擎；停止必须显式操作。
- 开发复用仓库环境用 `ARG_ENGINE_ROOT` / `ARG_VENV_DIR` / `ARG_MODELS_DIR` / `ARG_QDRANT_BIN`，不要把这些路径写死。

## 5. 完成定义（DoD）

一个改动完成前必须：

- [ ] `pytest` 通过
- [ ] `ruff check` / `ruff format --check` 通过
- [ ] 新接口有请求/响应模型、错误码、OpenAPI 描述
- [ ] `docs/API.md` 已更新
- [ ] 没有新增密钥、模型、数据文件
- [ ] 没有在异步路由里引入阻塞调用
- [ ] 涉及权限/上传/第三方 API 的改动已过安全 checklist
