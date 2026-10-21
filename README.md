# 企业 RAG 知识库引擎

按 [需求.md](需求.md) 实现的无状态 RAG 引擎：混合检索（BM25 + dense）+ 重排 + 引用生成 + 拒答 + 入库 + 评估。

引擎只负责 RAG 能力，不实现用户、登录、API Key、SSO、角色权限、管理后台。调用方/网关负责认证，并把可信身份通过 `X-Tenant-Id` / `X-Acl` 注入。

项目约束：[AGENTS.md](AGENTS.md)｜架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)｜编码规范：[docs/CONVENTIONS.md](docs/CONVENTIONS.md)｜接口文档：[docs/API.md](docs/API.md)。

服务启动后 Swagger UI 在 `/docs`，OpenAPI 在 `/openapi.json`。

## 当前进度

- [x] 需求文档（引擎版 v1.0）
- [x] Python 3.12 64 位虚拟环境（`.venv`）
- [x] 本地模型：BGE-M3、BGE-Reranker、Qdrant/bm25（4.27 GiB，已校验）
- [x] FastAPI：`/health`、`/api/v1/ask`
- [x] Qdrant collection：dense + sparse + INT8 量化 + payload 索引
- [x] 检索链路：BGE-M3 dense + jieba/BM25 sparse + Qdrant RRF + BGE reranker
- [x] 生成：外部 OpenAI 兼容 API；引用校验、拒答、重试/熔断/降级
- [x] 基础入库：解析、切分、embedding、upsert（样例已入库 5 chunk）
- [x] Qdrant 1.19.2 本地跑通，`/health` 与 `/api/v1/ask` 已验证
- [ ] 完整表格/代码切分策略
- [ ] HTTP 入库/预览/job 接口
- [ ] Golden set、RAGAS、CI 门禁
- [ ] 文档更新/删除、缓存失效

## 环境

- Windows 10/11 + Git Bash
- Python 3.12（由 `uv` 管理）
- 可选 GPU：embedding/reranker 可用 6GB+ GPU 或 CPU；生成 LLM 不在本地部署
- Qdrant 1.19+、Redis 7
- 生成 LLM：外部 OpenAI 兼容 API（DeepSeek、通义 DashScope 兼容模式、Moonshot、OpenAI、Azure OpenAI 等）

## 快速开始

```bash
# 1. 虚拟环境
uv venv --python 3.12 .venv
# 必须装 CUDA 版 torch；PyPI 默认 Windows 轮子是 CPU 版，rerank 会慢到 5s+
uv pip install --python .venv/Scripts/python.exe \
  --index-url https://download.pytorch.org/whl/cu126 torch
.venv/Scripts/python.exe -c "import torch; print(torch.cuda.is_available())"
uv pip install --python .venv/Scripts/python.exe -r requirements.txt

# 2. 下载本地模型（约 4.3 GB）
bash scripts/download_models.sh
.venv/Scripts/python.exe scripts/verify_models.py

# 3. 启动 Qdrant + Redis（Docker）或用 Windows 版 Qdrant
docker compose up -d qdrant redis

# 4. 建 collection
.venv/Scripts/python.exe scripts/create_collection.py

# 5. 配置外部 LLM API
cp .env.example .env
# 编辑 .env：LLM_BASE_URL / LLM_API_KEY / LLM_MODEL_NAME / LLM_MODEL_REVISION

# 6. 启动引擎
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

**本地无 GPU / 无 Redis 联调**：

```bash
# 用 Windows 版 Qdrant 代替 Docker
QDRANT__STORAGE__STORAGE_PATH=./qdrant_storage tools/qdrant/qdrant.exe

# 关掉 Redis、用 mock LLM 跑通 API 全链路
CACHE_ENABLED=false LLM_MOCK=true \
  .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

`LLM_MOCK=true` 只用于联调，回答会带 `[MOCK]` 前缀；生产必须接真实 OpenAI 兼容 API。

## 调试台（Web）

内置一个零依赖的单页调试台，覆盖健康检查、问答、仅检索、上传入库、LLM 配置（Base URL / API Key / Model）与连通性测试。

```bash
# 1. 引擎开启调试接口
DEV_TOOLS_ENABLED=true CACHE_ENABLED=false \
  .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080

# 2. 另开一个终端：静态页 + /engine 代理（默认 http://127.0.0.1:8090）
.venv/Scripts/python.exe scripts/dev_web.py
```

浏览器打开 <http://127.0.0.1:8090>：

- **LLM 配置**页填写 Base URL / API Key / Model，点「保存并应用」，再点「测试连接」。
- **问答**页验证检索 → 重排 → 生成 → 引用；**检索**页只看召回与分数。
- **入库**页可直接上传文件（与 `scripts/ingest.py` 等价的同步入库）。
- 页面通过 `/engine/*` 代理访问引擎，无需配置 CORS。
- LLM 配置只在引擎内存生效，重启后回退 `.env`；Key 不写盘、不返回明文。
- 调试接口与页面仅限本地/内网，生产必须保持 `DEV_TOOLS_ENABLED=false`。

## 调用方式

身份由网关注入，引擎不鉴权：

```http
POST /api/v1/ask
X-Tenant-Id: acme
X-Acl: internal,finance
Content-Type: application/json

{"query":"差旅报销标准是多少","top_k":5}
```

```bash
.venv/Scripts/python.exe scripts/ask.py "差旅报销标准是多少"
```

缺少 `X-Tenant-Id` / `X-Acl` 时引擎返回 400。引擎仍然强制执行 tenant/acl 数据过滤。

## 入库

```bash
.venv/Scripts/python.exe scripts/ingest.py \
  --path ./data \
  --tenant acme \
  --acl internal \
  --version v1 \
  --doc-type auto
```

入库写入 `text`、`doc_id`、`chunk_id`、`tenant_id`、`acl`、`doc_type`、`version`、`is_current`、`page_label`、`effective_date`、`content_hash` 等 payload 字段。

HTTP 入库/预览/job 接口规划中，见 `需求.md` 10.3–10.5。

## 外部 LLM API

```bash
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL_NAME=deepseek-chat
LLM_MODEL_REVISION=deepseek-chat@2026-xx
LLM_REDACT_PII=true
```

**安全护栏**：

- 只发送 `query + top-k chunk`，不发送完整文档、向量或内部元数据。
- 调用前做 PII 脱敏（手机号/身份证/银行卡）；`LLM_REDACT_PII=true` 开启。
- 出口走网关白名单 + TLS；API Key 放密钥管理，不写入代码/镜像/日志。
- 失败自动重试 + 熔断；熔断后返回检索片段并标记 `degraded=true`。
- 涉密/受监管数据不得使用外部 API；接入前须完成数据分类与合规评审。

## 开发检查

```bash
bash scripts/check.sh    # ruff check + ruff format --check + pytest
bash scripts/format.sh   # 自动格式化并修复 lint
```

## 项目结构

```
app/
  config.py            # pydantic-settings 配置
  main.py              # FastAPI 入口
  api/
    routes.py          # /health
    v1/ask.py          # /api/v1/ask
    v1/dev.py          # /api/v1/dev/*（仅 DEV_TOOLS_ENABLED=true）
  core/
    context.py         # 读取网关注入的 X-Tenant-Id / X-Acl
    cache.py           # Redis 缓存，key 含 tenant/acl/filters
    llm.py             # 外部 OpenAI 兼容 API 调用、引用解析、拒答
    retrieval.py       # Qdrant 混合检索 + RRF + 重排
    redact.py          # PII 脱敏
  ingest/
    parsers.py         # 多格式解析
    chunking.py        # 切分策略
    pipeline.py        # 入库流水线
  services/rag.py      # 问答编排
scripts/
  download_models.sh
  verify_models.py
  create_collection.py
  ingest.py
  ask.py
  dev_web.py           # 调试台静态服务 + 引擎代理
  check.sh / format.sh
web/                   # 单页调试台（零构建、零依赖）
models/                # 本地 embedding/reranker/bm25（gitignore）
docker-compose.yml     # Qdrant + Redis
```

## 已知限制

- 表格整块保留，超大表格可能超过 embedding 长度；后续按行组切分并重复表头。
- 代码文件暂用通用递归切分，未按函数边界切分。
- 引用语义校验目前只做编号存在性校验，NLI/LLM judge 抽样待接入。
- 入库默认是 CLI 同步执行；`/api/v1/dev/ingest` 仅用于本地调试，生产异步 job 接口待实现。
- 文档更新/删除、缓存失效、golden set/RAGAS 待实现。
