# Learning Resource Flow

让 AI 帮用户搜索、比较、获取并整理学习资源。

Learning Resource Flow 是一套面向 **OpenClaw** 的学习资源能力，由一个负责语义决策的 Skill 和一个负责真实资源操作的 MCP 组成。用户只需要用自然语言描述学习目标，Agent 会根据当前任务决定去哪里搜索、是否继续补充、何时检查具体资源，以及在用户确认后完成下载和归档。

```text
用户自然语言
   ↓
learning-resource-flow Skill
   ├─ 理解目标与约束
   ├─ 设计搜索路线
   ├─ 判断候选质量与 Coverage / Gap
   ├─ 决定继续搜索或停止
   └─ 理解用户选择与获取意图
   ↓
Host Web Search + education-resources MCP
   ↓
Search / Expand / Import / Inspect / Download / Archive
```

> 核心边界：**Agent 负责语义判断，MCP 负责真实能力、IO 和必要的运行状态。**

## 核心能力

- **自然语言找资料**：按主题、年级、学习目标、使用场景和资源形式理解用户需求。
- **多来源搜索**：结合宿主 Web Search 与已接入的专门资源平台，不固定走同一套搜索流程。
- **多轮补充搜索**：由 Agent 根据 Coverage 和 Gap 判断是否还需要继续搜，而不是固定搜索轮数。
- **资源检查与展开**：需要时进一步确认课程、合集、网页、书籍等资源的真实内容与可获取形态。
- **下载与长任务管理**：下载和大规模展开通过 Job 执行，可查询状态、取消和分页读取结果。
- **网页离线化**：普通网页可以保存原始 HTML，并生成清洗后的 Markdown 与单文件离线阅读页。
- **学习资料归档**：下载完成后可按学习主题和资源类型整理到用户资料库。
- **按需登录**：只有真实资源操作明确需要登录时才进入 Session 流程，不把登录当成所有操作的固定前置步骤。

## 快速开始

### 给最终用户

当前官方分发目标为 **Windows 10 / 11 + OpenClaw**。

最终发行包会包含：

```text
README.md
install.cmd
install.ps1
mcp/
skill/
```

普通用户解压后直接双击：

```text
install.cmd
```

如果用户把发行包交给具备终端能力的 AI，也可以直接让 AI 阅读发行包根目录的 `README.md` 并完成安装。安装脚本会处理 OpenClaw、Python、FFmpeg、Skill、MCP 注册和 MCP probe 等主要步骤。

发行包安装说明维护在：

- [`packaging/windows/README.md`](packaging/windows/README.md)

### 从开发仓库启动

仓库用于项目开发和真实 Agent 验证。当前运行入口仍然是 OpenClaw：

```bash
openclaw chat --local
```

然后直接使用自然语言，例如：

```text
帮我找适合小学三年级学习太阳系的中文图文资源，先搜索，不要下载。
```

Agent 可以先搜索和比较候选。如果用户随后说：

```text
把第二个下载下来。
```

Agent 会直接理解这个选择并调用对应资源能力，不再经过额外的 Selection / Prepare / Token / Start 状态链。

## 使用示例

### 找一组学习资料

```text
帮我找适合初中生理解火山形成过程的资料，视频、图文和练习题都可以。
```

Agent 会根据当前结果判断是否还存在明显缺口，再决定是否继续搜索其他来源。

### 查找指定平台资源

```text
帮我找 Bilibili 上讲高中函数单调性的优质视频。
```

对于已经接入的平台，Agent 可以直接使用专门资源能力；对于开放互联网长尾资源，则优先使用宿主 Web Search。

### 导入一个网页

```text
把这个网页保存成方便离线阅读的资料：https://example.com/article
```

普通网页当前会保留原始 `source.html`，并使用 Trafilatura 生成清洗正文和单文件 Reader：

```text
source.html
content.md
index.html
metadata.json
```

### 下载并整理

```text
把第二个下载下来，整理到我的物理资料里。
```

资源获取和归档是两个真实能力；Agent 根据用户意图调用，不把它们包装成持久化工作流状态机。

## 工作方式

Learning Resource Flow 不把研究过程固化成一套后端 Flow。

Agent 在当前对话中维护任务语义，并持续判断：

```text
Goal
  ↓
Coverage
  ↓
Search / Inspect
  ↓
Evidence
  ↓
Gap
  ├─ 仍有实质缺口 → 继续搜索
  └─ 已足够支持选择 → 停止并呈现候选
```

MCP 只保存执行真正需要的状态，例如：

- 当前 MCP 进程内的临时 `resource_id`；
- Expand / Download 的持久 `job_id`；
- 平台确实需要的 Session 登录态。

详细设计见 [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md)。

## 当前资源来源

专门平台能力目前覆盖：

| 来源 | 典型能力 |
| --- | --- |
| Bilibili | 视频、UP 主、合集 |
| Douyin | 视频、创作者、合集 |
| Ximalaya | 音频、专辑、创作者 |
| SmartEdu | 教材、课程等国家智慧教育资源 |
| Zjer | 课程资源 |
| CCTV | 栏目、视频 |
| LibGen | 书籍搜索与获取 |
| Z-Library | 登录后的书籍搜索与获取 |
| Zhihu | 页面导入与资源处理 |
| Generic Web | 普通网页导入、正文抽取和离线阅读 |

开放互联网的资源发现默认由宿主 Web Search 承担。选中具体 URL 后再通过：

```text
resource_import_url(source_url="https://...")
```

进入专门平台或 Generic Web 的后续处理。

## MCP 能力

`education-resources` 当前对 Agent 暴露 12 个 Tool。

资源能力：

```text
resource_search
resource_expand
resource_import_url
resource_inspect
resource_download
resource_job_status
resource_job_cancel
resource_job_read
resource_html_design
resource_archive
```

Session 辅助能力：

```text
resource_session_status
resource_session_manage
```

Session 只在真实资源能力返回需要登录，或用户主动要求管理登录态时使用。

## 项目结构

```text
skills/                              # Agent 的语义决策 Skill
mcp/education-resources/             # 唯一 active stdio MCP
packaging/windows/                   # Windows 最终用户安装入口
scripts/                             # Release 构建和项目级脚本
docs/                                # 当前架构与开发文档
.agent/plans/                        # 具体执行计划
legacy/                              # 只读历史实现
```

最重要的运行代码只有两部分：

- `skills/`：决定应该做什么；
- `mcp/education-resources/`：执行真实资源操作。

## 构建 Windows 发行包

在 Windows PowerShell 中从仓库根目录运行：

```powershell
.\scripts\build-release.ps1
```

构建脚本使用 allowlist 生成面向最终用户的 ZIP，只包含运行和安装需要的文件，不把 `.agent/`、`legacy/`、测试套件和开发过程文件带入发行包。

默认输出到：

```text
dist/
```

最终发行包中的根 `README.md` 来自：

```text
packaging/windows/README.md
```

因此开发仓库 README 与最终用户安装 README 可以分别维护，各自只承担一个职责。

## 开发文档

建议按以下顺序阅读：

1. [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md) — 当前 active 架构与运行事实
2. [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md) — 开发路线
3. [`.agent/plans/README.md`](.agent/plans/README.md) — 当前与历史专项计划索引
4. [`AGENTS.md`](AGENTS.md) — 本仓库的工程实现约束

历史架构和已经废弃的实现只用于追溯，不应作为当前实现依据。

## 设计原则

这个项目刻意保持职责边界简单：

- 不用后端状态机替代正常 Agent 对话；
- 不把语义判断硬编码成固定评分或固定搜索轮数；
- 不为了“完整”引入第二套平台 Registry、Resolver 或工作流框架；
- 不静默截断已经取得的数据；
- Inspect 只在未知事实会改变推荐或获取决策时调用；
- 登录、下载和归档都以真实用户任务为触发条件。

项目目标不是做一个覆盖所有互联网资源的通用爬虫，而是让 Agent 能够把 **“理解需求 → 找到资料 → 判断是否足够 → 获取资源 → 整理交付”** 这条真实用户链路稳定跑通。
