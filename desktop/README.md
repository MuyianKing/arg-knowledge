# ARG Knowledge 桌面客户端

Tauri v2 + React + TypeScript。应用里有两块**互相独立**的能力：

```text
┌─────────────────────────────┐
│ 客户端（永远只走 HTTP）      │
│  baseUrl + X-Tenant-Id/Acl  │──┐
└─────────────────────────────┘  │
                                 ▼
                        ┌──────────────────┐
                        │ RAG 引擎（任意位置）│
                        │ 本机 / 内网 / 网关 │
                        └──────────────────┘
                                 ▲
┌─────────────────────────────┐  │
│ 本地部署助手（可选）          │──┘
│ 检测环境 / 装依赖 / 起进程    │
└─────────────────────────────┘
```

- **客户端**不关心引擎部署在哪里，只读取设置里的 `baseUrl`。
- **部署助手**只负责把后台装到本机；它完成后只是把 `baseUrl` 填成
  `http://127.0.0.1:<enginePort>`，之后可以随时改成别的地址。
- 本机引擎是**独立服务**：关闭客户端不会停止 Qdrant/uvicorn；需要在设置页
  显式停止。已经由外部启动的实例，客户端只识别端口、不会强行结束。

## 开发

前置：Node 20+、Rust 1.77+、WebView2（Windows 11 自带）。

```bash
cd desktop
npm install
npm run tauri dev
```

只构建前端：

```bash
npm run build
```

只检查 Rust：

```bash
cd src-tauri && cargo check
```

## 开发模式复用仓库环境

默认 `APP_HOME` 是 `%LOCALAPPDATA%\ARG-Knowledge`。如果不想重新安装
一套依赖和模型，用环境变量指回仓库：

```bash
# 从仓库根目录一键启动（会自动带上这些环境变量）
../run.sh --mock-llm

# 或手动：
cd desktop
ARG_ENGINE_ROOT="E:/muyian/ARG-knowledge" \
ARG_VENV_DIR="E:/muyian/ARG-knowledge/.venv" \
ARG_MODELS_DIR="E:/muyian/ARG-knowledge/runtime/models" \
ARG_QDRANT_BIN="E:/muyian/ARG-knowledge/runtime/tools/qdrant/qdrant.exe" \
npm run tauri dev
```

| 变量 | 作用 |
|---|---|
| `APP_HOME` | 应用数据根目录（日志、Qdrant 存储、上传） |
| `ARG_ENGINE_ROOT` | 引擎源码目录（含 `app/main.py`） |
| `ARG_VENV_DIR` | 复用已有虚拟环境 |
| `ARG_MODELS_DIR` | 模型根目录 |
| `ARG_QDRANT_BIN` | Qdrant 可执行文件 |
| `ARG_UV_BIN` | uv 可执行文件 |

## 发布时需要放进资源目录

部署助手从 `src-tauri/resources/` 读取随包工具（`bundle.resources` 已配置）：

```text
src-tauri/resources/
├─ bin/uv.exe
└─ qdrant/qdrant.exe
```

Python 由用户自行安装（3.10–3.12，64 位，推荐 3.12），不打进安装包。模型默认 4.3 GB，
支持在线下载（HF 镜像可配）或选择已有模型目录导入。

Qdrant 使用官方 Windows 版（1.19+），由部署助手以
`QDRANT__SERVICE__HOST=127.0.0.1` 启动，只监听本机 6333/6334 端口，
存储目录为 `%LOCALAPPDATA%\ARG-Knowledge\qdrant_storage`。Qdrant 就绪后
部署助手会调用 `scripts/create_collection.py` 建 collection（幂等）。
可以从 <https://github.com/qdrant/qdrant/releases> 下载 Windows zip。

### 引擎代码

本地部署助手需要引擎的 `app/`、`scripts/`、`requirements.txt`、`pyproject.toml`：
它用这份代码安装依赖、启动 uvicorn、创建 collection。开发模式通过
`ARG_ENGINE_ROOT` 或向上查找仓库根目录定位；打包时 `bundle.resources` 会把
它们复制到安装资源目录的 `engine/` 下，运行时优先使用 `resource_dir()/engine`，
不依赖用户克隆的仓库。

只连接远程引擎时不需要这份代码，部署助手也不会运行。

## 已实现

- 启动时探测 `baseUrl/health`，连接失败进入连接页，不强制本地部署。
- 连接设置：引擎地址、`X-Tenant-Id`、`X-Acl`，支持测试连接。
- **问答**：调用 `/api/v1/ask`，展示回答、引用、拒答/降级、耗时和缓存命中。
- **知识库**：文件上传 → 异步入库任务轮询 → 文档列表 → 删除文档。
- **LLM 配置**：Base URL / 模型 / 温度 / max_tokens / mock；API Key 存
  Windows 凭据管理器，启动引擎时注入环境变量。
- 部署助手向导：系统检查、Python 检测（3.10–3.12 64 位）、依赖安装、
  模型校验、启动 Qdrant/引擎、自动建 collection、登记本机地址。
- 模型分发：在线下载（可配 HF 镜像）或导入已有模型目录。
- Rust 侧检测：OS/架构/内存/磁盘/WebView2/GPU、Python 候选、venv/torch/CUDA/
  依赖导入、模型文件大小校验。
- 进程托管：启动/停止、日志落盘、端口检测；服务独立于客户端生命周期。
- 安装包会把引擎源码打进 `resources/engine`，打包版不依赖用户克隆的仓库。

## 待接入

- SSE/流式回答（当前为一次性返回）。
- 安装包签名与自动更新（需要发布证书和更新源）。
- 入库预览、任务取消/重试。
- 大规模知识库的分页与独立文档元数据表（当前 `/documents` 最多扫描
  `max_points` 个 chunk）。

## 约定

- 客户端代码不允许直接读本地进程状态来判断「引擎是否在线」，一律以
  `baseUrl/health` 为准。
- 部署助手不得改变客户端语义：它只写 `baseUrl` 和本地部署参数。
- 引擎始终只监听 `127.0.0.1`（本机部署时）；远程部署由服务端负责。
