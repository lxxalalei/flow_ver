# Learning Resource Flow

让 AI 搜索、比较、获取并整理学习资源。

Learning Resource Flow 是一套面向 **OpenClaw** 的学习资源能力，由 `learning-resource-flow` Skill 和 `education-resources` MCP 组成。

用户只需要用自然语言描述学习目标。Agent 负责理解需求、规划搜索、判断候选质量和搜索是否充分；MCP 负责真实的平台搜索、资源检查、下载、网页离线化、归档和必要的登录态能力。

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

> **Agent 负责语义判断，MCP 负责真实能力、IO 和必要的运行状态。**

## 核心能力

- **自然语言找资料**：按主题、年级、学习目标、使用场景和资源形式理解需求。
- **多来源搜索**：结合宿主 Web Search 与已接入的专门资源平台，不固定走同一套搜索流程。
- **多轮补充搜索**：根据当前 Coverage 和 Gap 判断是否继续搜索，而不是固定搜索轮数。
- **资源检查与展开**：按需确认课程、合集、网页、书籍等资源的真实内容与可获取形态。
- **下载与长任务管理**：下载和大规模展开通过 Job 执行，可查询状态、取消和分页读取结果。
- **网页离线化**：保存原始 HTML，并生成清洗后的 Markdown 与单文件离线阅读页。
- **学习资料归档**：将最终资源按学习主题和资源类型整理到资料库。
- **按需登录**：只有真实资源操作明确需要登录时才进入 Session 流程。

## 安装与开始使用

### Windows 发行包

当前发行目标为 **Windows 10 / 11 + OpenClaw**。

解压发行包后，目录应包含：

```text
README.md
install.cmd
install.ps1
mcp/
skill/
```

直接运行：

```text
install.cmd
```

或在 PowerShell 中运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

安装脚本会处理：

- OpenClaw 检查与安装；
- Python 3.12+ 检查与安装；
- FFmpeg 检查与安装；
- `education-resources` 独立 Python 环境；
- `learning-resource-flow` Skill 全局安装；
- `education-resources` MCP 注册；
- MCP live probe；
- OpenClaw Gateway 重载或重启。

如果 OpenClaw 是第一次安装，按 OpenClaw 自身提示完成模型 Provider 配置即可。资源平台不需要在安装阶段逐个登录。

安装完成后可检查：

```powershell
openclaw doctor
openclaw mcp doctor education-resources --probe
```

发行包的完整安装说明见 [`packaging/windows/README.md`](packaging/windows/README.md)。

### 开始使用

新建 OpenClaw 对话，直接描述需要的学习资源：

```text
帮我找适合小学三年级学习太阳系的中文图文资源，先搜索，不要下载。
```

继续选择已有候选：

```text
把第二个下载下来。
```

不需要记忆 Skill 名称或 MCP Tool 名称。

### 从开发仓库启动

已完成本地 OpenClaw 和项目开发环境配置时，可从仓库运行：

```bash
openclaw chat --local
```

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

已接入的平台可以直接使用专门资源能力；开放互联网的长尾资源由宿主 Web Search 负责发现。

### 导入网页

```text
把这个网页保存成方便离线阅读的资料：https://example.com/article
```

Generic Web 会保留原始响应，并生成可读派生文件：

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

下载与归档按实际用户意图调用，不需要额外的持久化工作流状态。

## 工作方式

Learning Resource Flow 不把研究过程固化成后端 Flow。

Agent 在当前对话中持续判断：

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

## 已接入搜索来源

`resource_search` 当前默认注册以下专门来源，并另外提供 Generic Web 搜索能力：

| 来源 | 主要资源 |
| --- | --- |
| Bilibili | 视频、UP 主、合集 |
| Douyin | 视频、创作者、合集 |
| Ximalaya | 音频、专辑、创作者 |
| CCTV | 栏目、视频 |
| 一席（Yixi） | 演讲视频 |
| 网易公开课（Open163） | 公开课、课程视频 |
| SmartEdu | 教材、课程等国家智慧教育资源 |
| Zjer | 课程资源 |
| 科普中国（Kepu） | 科普文章 |
| 百度文库（Baidu Wenku） | 文档资料 |
| 菜鸟教程（Runoob） | 编程教程 |
| LibGen | 书籍 |
| Z-Library | 书籍 |
| 书格（Shuge） | 古籍、公开文件 |
| Zhihu | 回答、文章等页面内容 |
| Weibo | 微博内容 |
| WeChat | 微信公众号内容 |
| Generic Web | 开放互联网网页与长尾资源 |

这里表示“已经接入搜索发现”，不代表所有来源拥有完全相同的 Inspect、Expand 或 Download 深度。具体资源是否需要进一步检查、能否直接获取，以及是否需要登录，由对应平台实现和当前真实结果决定。

其中一席和书格都已经有专门搜索 Adapter，并已接入 `resource_inspect`。一席搜索会解析公开可用的视频资源；书格直接搜索其公开存储中的古籍文件。

开放互联网的资源发现也可由宿主 Web Search 承担。选中具体 URL 后可通过 `resource_import_url` 进入专门平台或 Generic Web 的后续处理。

## MCP 能力

`education-resources` 当前提供 12 个 Tool。

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
skills/                              # Agent 语义决策 Skill
mcp/education-resources/             # active stdio MCP
packaging/windows/                   # Windows 发行包安装入口
scripts/                             # Release 构建和项目级脚本
docs/                                # 当前架构与开发文档
.agent/plans/                        # 具体执行计划
legacy/                              # 只读历史实现
```

核心运行代码只有两部分：

- `skills/`：决定应该做什么；
- `mcp/education-resources/`：执行真实资源操作。

## 构建 Windows 发行包

在 Windows PowerShell 中从仓库根目录运行：

```powershell
.\scripts\build-release.ps1
```

构建脚本使用 allowlist 生成发行 ZIP，只包含运行和安装需要的文件，不包含 `.agent/`、`legacy/`、测试套件和开发过程文件。

默认输出到：

```text
dist/
```

发行包根目录的 `README.md` 来自：

```text
packaging/windows/README.md
```

## 开发文档

1. [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md) — 当前架构与运行事实
2. [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md) — 开发路线
3. [`.agent/plans/README.md`](.agent/plans/README.md) — 专项计划索引
4. [`AGENTS.md`](AGENTS.md) — 工程实现约束

历史架构和废弃实现只用于追溯，不作为当前实现依据。

## 设计原则

- 不用后端状态机替代正常 Agent 对话；
- 不把语义判断硬编码成固定评分或固定搜索轮数；
- 不为了完整性引入第二套平台 Registry、Resolver 或工作流框架；
- 不静默截断已经取得的数据；
- Inspect 只在未知事实会改变推荐或获取决策时调用；
- 登录、下载和归档都以真实用户任务为触发条件。

项目目标不是覆盖所有互联网资源的通用爬虫，而是稳定完成 **“理解需求 → 找到资料 → 判断是否足够 → 获取资源 → 整理交付”** 这条真实用户链路。
