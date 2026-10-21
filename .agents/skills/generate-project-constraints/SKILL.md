---
name: "generate-project-constraints"
version: "0.3.1"
description: '详细分析项目并生成 AGENTS.md 约束文件与业务文档目录（docs 与代码目录镜像 + README.md 索引），以提高 AI 缓存命中率。当用户说"帮我给项目建立约束文件"、"生成项目约束"、"建立 agent 规则"、"建立业务文档 / 生成文档索引"等类似意图时立即触发。'
---
# Generate Project Constraints (生成项目约束文件)

本 Skill 用于对当前工作区进行**系统性项目扫描**，产出两件交付物：(1) 以本目录下的通用约束模板 [AGENT_COMMON.md](./AGENT_COMMON.md) 为基础，生成（或更新）仓库根目录下简洁版 `AGENTS.md` 约束文件；(2) 按 [DOC_TEMPLATE.md](./DOC_TEMPLATE.md) 建立与代码目录镜像的**业务文档目录**及其索引。两者共同作为 AI Coding Agent 的稳定上下文，可显著提高生成代码的一致性与提示词缓存命中率。

> 说明：业务文档是**强约束**而非可选产物——没有它，"每次代码改动必须同步更新文档"这类规则无法落地。Skill 运行时必须同时产出 `AGENTS.md` 与 `docs/` 两部分。

## 触发条件

当用户输入以下或语义等价的指令时，**立即且完整**执行本流程：

- 帮我给项目建立约束文件
- 生成项目约束 / 生成 AGENTS.md / 建立 agent 规则
- 详细的过一遍项目……生成约束文件，提高缓存命中率
- 给项目加一份 AI 上下文规则
- 建立业务文档 / 生成文档目录与索引 / 把文档按代码目录建立起来

## 执行步骤（必须严格依次执行）

### Step 1 · 项目结构扫描

1. 使用 `LS` 列出仓库根目录与 `src/` 的一级结构。
2. 使用 `Glob` 检索以下关键文件是否存在（判定技术栈与既有约束）：
   - 包管理：`package.json`、`pnpm-lock.yaml`、`yarn.lock`、`package-lock.json`、`.npmrc`、`.nvmrc`
   - 构建：`vite.config.*`、`webpack.config.*`、`vue.config.*`、`next.config.*`、`nuxt.config.*`、`taro.config.*`、`app.json`、`manifest.json`、`pages.json`
   - 语言：`tsconfig.json`、`jsconfig.json`
   - Lint/Format：`eslint.config.*`、`.eslintrc*`、`.prettierrc*`、`prettier.config.*`、`.editorconfig`、`stylelint.config.*`
   - 原子化 CSS：`uno.config.*`、`tailwind.config.*`、`postcss.config.*`
   - 测试 / CI：`vitest.config.*`、`jest.config.*`、`.github/workflows/*`
   - 其他：`.gitignore`、`README*`、`.vscode/settings.json`

### Step 2 · 关键文件深读

对存在的文件**逐一使用 `Read` 读取完整内容**（不要只读片段），重点收集：

- `package.json`：`name` / `version` / `type` / `scripts` / `dependencies` / `devDependencies` / `engines` / `packageManager`
- 构建配置：插件列表、alias、自动导入与组件解析器
- Lint/Prettier：基础预设、override 规则、是否启用 Prettier
- 原子化 CSS：preset / transformer / shortcuts
- 框架入口：`main.*` / `App.*` / 路由配置 / 状态管理注册
- `tsconfig.json` / `jsconfig.json`：路径别名、types
- `.vscode/settings.json`：保存动作、格式化器、ESLint validate 列表
- `.npmrc` / workspace 配置

### Step 3 · 建立技术栈画像

整理出以下事实清单（用于写入 AGENTS.md 项目专属章节）：

- **项目类型判定**（决定 Step 4 的章节取舍）：是否含页面 / 组件 / 样式与 UI 框架依赖 —— UI/应用项目，或只有函数、类型与构建逻辑的无 UI 项目（工具库 / SDK / CLI / Node 服务）
- 项目定位：应用类型（Web/小程序/桌面/Node/Monorepo）与业务领域
- 语言与版本：JS/TS/Vue SFC 等
- 主框架、状态管理、路由、UI 库、图标方案
- 原子化 CSS、预处理器（Sass/Less/Stylus/PostCSS）
- 数据请求：axios / uni.request / fetch wrapper
- 自动导入、Lint、Format、包管理器
- 构建工具、测试、CI
- 既有约束文件：根目录是否已有 `AGENTS.md` / `AGENT_COMMON.md`

### Step 4 · 生成 AGENTS.md（以通用约束模板为基础）

1. 先 `Read` 本 Skill 目录下的模板文件 [AGENT_COMMON.md](./AGENT_COMMON.md)（跨项目通用约束，作为生成基础）。
2. 在仓库**根目录**创建或覆盖 `AGENTS.md`（若已存在，先 `Read` 比较后再 `Write` 覆盖），结构如下：

   - **「0. 通用约束」章节**：采用模板 `AGENT_COMMON.md` 的内容，并按 Step 3 判定的项目类型取舍 —— UI/应用项目并入全部章节；无 UI 项目（工具库 / SDK / CLI / Node 服务）并入「修改原则」「业务文档」「验证与 Git」，**删除**「组件设计」「UI 与样式」两节，不保留空标题、不写"本项目不涉及"。说明已并入本文件。
   - **项目专属章节**：在通用约束之后，用简洁的条目式写法补充，每节 3~10 条，只写**已存在的事实与强约束**，不写教程；下面的分组是**按项目类型取用的清单**，不适用的整节删除：
     1. **项目边界**：技术栈（语言 / 框架 / 构建 / 包管理器）与禁止引入的技术、库
     2. **文件落位**：页面 / 私有组件 / 公共组件 / API / store / util / 资源目录规则
     3. **编码规范**：框架版本边界、组件写法（如 `<script setup>` / Options）、弹窗表单模式、命名规则
     4. **UI 与样式**：UI 复用优先级、样式语言与作用域、样式穿透写法、原子化 CSS 约束、图标方案
     5. **请求 / 状态 / 配置**：请求封装、API 返回约定、环境变量管理、路由维护、Vuex、平台桥接
     6. **Agent 操作与验证**：可用的 npm 脚本（如 lint）、禁止事项、敏感配置保护
     7. **业务文档**：文档目录与索引位置、文档范围与镜像规则、改动同步要求、"文档为主、代码为辅"（与 Step 5 生成的实际结构一致）
3. 生成结果必须与模板风格一致：**简洁、条目式、无冗余**，整体控制在 80~150 行。

### Step 5 · 生成业务文档骨架（docs 与代码目录镜像）

先生成 `AGENTS.md`（Step 4），再生成业务文档目录；**两部分都要落地**，不要只做其一。完整镜像规则、模板、并行生成提示词与校验脚本见本目录 [DOC_TEMPLATE.md](./DOC_TEMPLATE.md)，**执行前先 `Read` 该文件**。

1. **判定范围**：扫描业务层目录，按 DOC_TEMPLATE 第 1 节的表判定哪些文件建文档——业务页面与公共组件建；应用入口、根组件、静态/错误页、未注册页面、工具层（api/server/model/store/hooks/utils/router/constant）与依赖包不建。只依据**实际存在**的目录，不为不存在的分层预留空目录。
2. **建镜像目录**：在 `docs/` 下按代码相对路径建立同名目录，保持同名、同层级。
3. **逐业务文件写文档**：页面模块（整目录）一份 `Index.md`；单文件页面一份同名 `.md`；公共组件逐组件一份 `.md`；公共组件目录另出一份 `README.md` 作目录索引。
4. **写全局索引 `docs/README.md`**：真源优先级、覆盖范围与镜像规则、文档模板、变更要求、文档清单表、已知待办。所有文档都必须能从该索引到达。
5. **模块多时并行生成**：用并行子 Agent 分摊，提示词要素见 DOC_TEMPLATE 第 5 节；必须要求每个 Agent 回报"无法从源码确认、需要人工确认的点"，并把这些疑点汇总进索引的「已知待办」，不要丢弃。
6. **生成后必须校验**：运行 DOC_TEMPLATE 第 6 节的脚本，确认「范围外文档 / 未映射文档 / 断链 / 索引不可达」四项输出全空；非空则修到为空再交付。
7. **回填 AGENTS.md**：确认 `AGENTS.md` 的「业务文档」章节与实际生成的目录结构一致（含目录索引位置与镜像规则），避免约束与产物不符。

### Step 6 · 写作质量要求

- 所有文件引用必须使用 `相对路径` ；链接文本禁止用反引号包裹。
- 技术栈版本号必须与 `package.json` 完全一致，不得估计；不要编造未安装的依赖。
- 未引入的能力应在"项目边界"中明确"禁止引入"。
- 中文项目使用中文写作；保持与用户沟通语言一致。
- 不要写"待补充 / TBD / 占位"内容；不适用的章节直接删除，不写"本项目不涉及"。

### Step 7 · 完成后报告

向用户输出**简短摘要**：

1. 判定出的项目类型（UI/应用项目 或 无 UI 项目）与核心技术栈（语言 / 框架 / 构建 / 包管理 / Lint / UI 库）
2. 生成的文件路径（点击链接）：`AGENTS.md` 与 `docs/README.md` 索引
3. `AGENTS.md` 包含的章节标题列表
4. 业务文档产出统计：文档数量、覆盖的目录范围、被排除的文件及排除依据
5. 校验结果：范围外文档 / 未映射文档 / 断链 / 索引不可达四项的检查结论（应全为空）
6. 任何需要用户后续确认的不确定点（如缺失 lint 配置、接口文档未收录业务接口等），并与索引「已知待办」一致

## 反模式（务必避免）

- ❌ 仅读 `package.json` 就生成约束（必须走完 Step 1-2）
- ❌ 把"建议"写成约束（如"建议使用 TS"），约束必须基于**已存在的事实**
- ❌ 把 AGENTS.md 写成教程文档，应是**事实清单 + 强约束**
- ❌ 忽略 `.vscode/settings.json` 中的 `prettier.enable`、`editor.codeActionsOnSave` 等关键信号
- ❌ 生成冗长的多章节模板文档，背离基础模板 `AGENT_COMMON.md` 的简洁风格
- ❌ 只产出 `AGENTS.md` 而跳过 `docs/`：文档约束没有对应产物就是空规则
- ❌ **给工具层（api/server/model/store/utils 等）也建业务文档**，制造大量低价值、易漂移的文件
- ❌ 为每个页面私有弹窗单独建文档，导致同一份表单规则写在两处
- ❌ 只凭感觉判断文档结构正确，不跑 Step 5.6 的校验脚本（断链与漏登记必然出现）
- ❌ 丢弃子 Agent 回报的疑点，导致「已知待办」为空而实际存在口径不一致

## 输出长度参考

- 完整 AGENTS.md 建议 **80~150 行**，与基础模板同样简洁；过短无法构成有效约束，过长会被截断且降低命中率。
- 业务文档按模块/组件一个文件，单文件聚焦一个业务单元；不要把所有模块塞进一个巨型文档。
