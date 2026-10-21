# DOC_TEMPLATE.md

本文件是 [SKILL.md](./SKILL.md) Step 5 的配套参考：业务文档目录的镜像规则、模板、生成方式与校验脚本。生成时按本项目实际目录名替换 `<...>` 占位符。

## 1. 文档范围判定

按「是否承载业务逻辑」决定是否建文档，**先判定再动手**：

| 分类 | 示例 | 是否建文档 |
| --- | --- | --- |
| 业务页面 | 列表页、表单页、详情页、登录页 | 建 |
| 公共业务组件 | 状态标签、字典下拉、图片上传 | 建 |
| 页面私有弹窗组件 | 各模块 `components/EditDialog.vue` | 并入所属模块文档，不单独建 |
| 应用入口 / 根组件 | `main.*`、`index.*`、`App.*` | 不建 |
| 静态页 / 错误页 | 403、404、未注册路由的页面 | 不建 |
| 工具层 | api / server / model / store / hooks / utils / router / constant | 不建（真源是源码与本文件） |
| 依赖包内能力 | `packages/**`、`node_modules` 内的包 | 不建（真源在被引用包自带 README） |

判定依据只能是**实际存在的目录与文件**，不要为不存在的分层预留空目录。

## 2. 镜像规则

文档目录与代码目录**同名、同层级**：

| 代码 | 文档 | 粒度 |
| --- | --- | --- |
| `<业务根>/<模块>/`（含 `Index.vue` 与 `components/`） | `docs/<业务根>/<模块>/Index.md` | 页面模块（整目录一份） |
| `<业务根>/Login.vue` 等单文件页面 | `docs/<业务根>/Login.md` | 单文件页面 |
| `<公共组件目录>/<组件>.vue` | `docs/<公共组件目录>/<组件>.md` | 公共组件（逐组件一份） |
| `<公共组件目录>/` | `docs/<公共组件目录>/README.md` | 目录索引 |

补充约定：

- 索引分两层：`docs/README.md` 是**全局索引**，收录全部文档；公共组件目录另有一份 `README.md` 作**目录索引**，只放清单与共性规则，不重复各文件细节。页面模块不另建索引，统一收敛到全局索引表。
- 页面模块的私有弹窗组件规则写在模块文档内，不为单个弹窗另建文件——同一规则写两处必然漂移。
- 不新增与代码目录无关的分类目录（如按功能重新分组的 `docs/前端/`）。

## 3. 全局索引模板（`docs/README.md`）

```markdown
# 业务文档索引

<一句话说明本目录记录什么、给谁看>

## 1. 文档真源优先级

- **已存在文档的业务需求，以文档为主、代码为辅**：文档与代码不一致时，先判定是代码回归还是需求变更，不得直接按代码"修正"文档。
- 新增或修改业务逻辑时，**先改文档，再改代码**，保证两者同一次改动内一致。
- 接口出入参的真源是 <接口文档路径>，业务文档只记录"调了哪个接口、做什么用"，不复制出入参结构。
- 技术约束与落位规则的真源是仓库根目录 AGENTS.md；本目录只写业务规则，不重复技术规范。

## 2. 覆盖范围与目录镜像规则

<说明只覆盖哪些层、其余层以什么为准>

<镜像规则表>

## 3. 文档模板

<页面文档模板；说明目录索引模板>

## 4. 变更要求

- **每次代码改动必须同步修改对应文档**，并在该文档「变更记录」表追加一行（日期 + 变更内容）。
- 新增业务模块或公共组件：先建镜像文档，再写代码；文档缺失视为改动未完成。
- 删除代码同步删除文档并更新索引；重命名或迁移代码同步移动文档，保持镜像关系不破。
- 本索引新增/删除文档时必须同步维护索引表。

## 5. 文档索引

<按层分组的清单表：代码位置 | 文档 | 说明>

## 6. 已知待办

<扫描中发现的、需要人工确认的口径不一致；没有则删除本节>
```

## 4. 文档模板

**页面 / 单文件 / 组件文档**（三者共用同一结构）：

```markdown
# <模块中文名>

> 代码位置：`<代码相对路径>`
> 最后更新：<YYYY-MM-DD>
> 接口出入参以 <接口文档相对路径链接> 为准；该文档未收录的接口以后端实际定义为准

## 概要

<1-3 句说明该模块解决什么业务问题>

## 代码位置

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 页面 / 组件 | `...` | ... |
| 弹窗组件 | `...` | ... |
| 请求方法 | `...` | ... |
| 接口地址 | `...` | ... |
| 数据模型 | `...` | ... |
| 路由 | `/xxx` | 见 `<路由文件>`，标题「...」 |

## 业务规则

<逐条列出源码可验证的规则：字段含义、校验与长度限制、枚举取值与展示、控件选择、联动、唯一性、特殊操作的前置条件。每条标注来源文件>

## 数据流

<列表查询 / 新增 / 编辑 / 删除 / 特殊操作各自：页面 → 请求方法 → 接口 → 模型 → 刷新方式>

## 依赖接口

| 请求方法 | 接口路径 | 用途 |
| --- | --- | --- |

## 变更记录

| 日期 | 变更内容 |
| --- | --- |
| <YYYY-MM-DD> | 首次创建 |
```

**目录索引**（如 `docs/<公共组件目录>/README.md`）：「概要 / 清单表 / 目录约定 / 共性规则 / 变更记录」。清单表每行指向一个文档文件。

写作要求：

- 只写源码可验证的事实，不允许推测；无法确认的写"以源码为准"并给出文件路径。
- 不粘贴大段源码，不复制接口文档的出入参 JSON。
- 相对链接层级逐文件核对（`docs/a/b/c.md` 到 `docs/api.json` 是 `../../../api.json`），不要凭感觉写。

## 5. 生成方式：并行子 Agent

模块较多时用并行子 Agent 分摊，每个 Agent 负责一组模块。提示词必须包含：

1. 仓库根目录与"只允许在 `docs/` 下创建文件，禁止修改业务代码"的红线。
2. 镜像路径规则（含完整示例）与本次要生成的文件清单（绝对路径）。
3. 必读源码清单：模块页面 + 其私有组件 + 请求方法 + 接口地址 + 数据模型 + 路由文件 + 常量/选项文件。
4. 本文档第 4 节的模板原文，以及写作要求（含链接层级要自行核对）。
5. 要求回报：生成文件清单 + 每个文件一句话说明 + **无法从源码确认、需要人工确认的点**。

最后一轮必须把各 Agent 回报的疑点汇总进全局索引的「已知待办」，不要丢弃。

## 6. 校验脚本

生成后**必须用脚本核对**，不要凭感觉判断。以下脚本从仓库根目录运行：

```python
import io, os, re

repo = os.getcwd()
docs = os.path.join(repo, 'docs')
SCOPE = ('docs/<业务根>/', 'docs/<公共组件目录>/')  # 按实际替换

def rel(p):
    return os.path.relpath(p, repo).replace(os.sep, '/')

doc_files = [os.path.join(dp, f) for dp, _d, fs in os.walk(docs) for f in fs if f.endswith('.md')]

# 1) 范围：不得出现范围外的文档
out = [rel(d) for d in doc_files if rel(d) != 'docs/README.md' and not rel(d).startswith(SCOPE)]
print('out-of-scope docs:', out)

# 2) 每个文档必须映射回真实代码路径
miss = []
for d in doc_files:
    r = rel(d)
    if r == 'docs/README.md':
        continue
    inner = r[len('docs/'):]
    code = os.path.join(repo, os.path.dirname(inner)) if inner.endswith('/README.md') else os.path.join(repo, inner[:-3])
    if not (os.path.isdir(code) or os.path.exists(code + '.vue') or os.path.exists(code + '.js')):
        miss.append((r, rel(code)))
print('unmapped docs:', miss)

# 3) 相对链接可达（跳过代码块，避免模板占位符误报）
#    注意：FENCE 用拼接构造，避免在本文档中出现连续三个反引号而截断代码围栏
FENCE = '`' * 3
link_re = re.compile(r'\]\((?!https?://|#)([^)]+)\)')
broken = []
for d in doc_files:
    text = re.sub(FENCE + r'[\s\S]*?' + FENCE, '', io.open(d, encoding='utf-8').read())
    for m in link_re.finditer(text):
        t = m.group(1).split('#')[0]
        if t and not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(d), t))):
            broken.append((rel(d), t))
print('broken links:', broken)

# 4) 全局索引可达性：每个文档都要能在 docs/README.md 中找到
idx = io.open(os.path.join(docs, 'README.md'), encoding='utf-8').read()
print('unreachable from index:', [rel(d) for d in doc_files
                                 if rel(d) != 'docs/README.md' and os.path.basename(d) not in idx])
```

四个输出必须全部为空。任一非空就修到为空再报告，不要带着断链或漏登记的文档交付。
