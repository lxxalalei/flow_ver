# TOOLS.md

运行时能力以 OpenClaw 实际暴露的 Tool `name / description / input schema / return` 为准；不要从历史 contracts、legacy 文件或旧计划猜测 Tool 参数和状态。

当前只有一个 active MCP：

- `education-resources`：资源搜索、创作者预览、URL 导入、Inspect、下载、Batch、Job、归档，以及四个辅助 Session Tool。

## 资源能力边界

Main Agent / Skill 负责理解需求、设计搜索任务、选择来源、判断候选、识别 Gap、理解用户选择和获取意图；MCP 负责实际平台调用与文件副作用。

当前资源 Tool：

```text
resource_search
resource_browse_creator
resource_import_url
resource_inspect
resource_download
resource_job_status
resource_job_cancel
resource_batch_collect
resource_batch_read
resource_archive
```

普通 Web 发现优先使用宿主 Web Search。选中具体 URL 后交给 `resource_import_url`；Import 会识别明确的 Bilibili / Zhihu / SmartEdu URL，无法明确识别的网页才按 `generic` 处理。

`resource_id` 是当前 MCP 进程内的临时操作句柄；URL、平台原生 ID 等才是稳定资源身份。`job_id` 只为真实长任务保存运行状态。

用户已经明确选中资源并要求下载/保存时，可以直接使用 `resource_download`，不创建 `prepare -> confirm -> start` 二次确认流程。

### Resource 与 File 不是一一对应

MCP 的资源级能力允许：

```text
1 Resource -> 0..N real files
```

`resource_inspect` 中的 `primary` 用来确定资源主表示和下载路由；`attachment` / `companion` 等表示可以描述同一逻辑资源自然附带的其他内容。它们不是要求 Agent 把一个课程拆成多个独立“资源”。

`resource_download(..., preferred_container="original")` 表示按资源本身的自然交付方式获取。自然交付可能是单文件，也可能是多文件，例如 SmartEdu 课程可以同时产生主视频、PDF 资料和伴随音频；Generic Web 也会产生 source/readable/metadata 等多个文件。

不要因为输入 URL 本身是 landing webpage 就判断“该资源不能下载”，也不要为了让它可下载而自行补 `mp4` / `pdf`。只有用户明确要求某个具体格式时才传 `preferred_container`；指定格式必须真实存在，不能找不到后静默退回其他格式。

## Session 是辅助能力，不是前置流程

当前 Session Tool 与资源 Tool 由同一个 MCP 暴露：

```text
resource_session_status
resource_session_login_guide
resource_session_save
resource_session_delete
```

不要在每次搜索或下载前先检查 Session。只有以下情况需要它：

- 某个真实资源能力返回 `AUTH_REQUIRED`；
- 用户明确要求登录、保存、检查或删除某个平台会话。

浏览器捕获结果直接交给 `resource_session_save`；MCP 自己按平台规则筛选，只保存真正需要的 Cookie / Token / storage key。Agent 不手工拼接 canonical Cookie/Token，也不要求用户把账号密码、验证码或 MFA 交给模型。

平台支持登录不等于所有操作都需要登录。`status=not_required` / `requires_login=false` 的平台不得发起登录流程。

### SmartEdu

SmartEdu 公共搜索和公共教材索引匿名访问，不自动携带已保存 token。公共搜索若返回 `NETWORK_BLOCKED` / `PLATFORM_UNAVAILABLE`，按当前网络出口/IP 风控/平台访问失败处理，不通过重新登录或补 token 自动重试。

具体 Inspect / Download 真实返回 `AUTH_REQUIRED` 时才进入 Session Tool。

SmartEdu 课程是逻辑复合资源：Inspect 应同时暴露当前自然交付中受支持的主视频/主文件以及附件、伴随内容；默认 `original` 交给 SmartEdu Downloader 按当前详情事实产生一个或多个文件，而不是让 Agent 从课程 URL 猜一个扩展名。

### Anna's Archive

`annas-archive` 当前是 Libgen 镜像支持的匿名图书发现/获取能力，不依赖 Anna 会员登录。不要为它调用登录引导，也不要因为展示名称是“安娜的档案”就访问会员下载页。

## Generic Web Resource

Generic 网页获取当前保存：

```text
source.html      # fetch 得到的原始 HTML
index.html       # Trafilatura 可读 HTML
content.md       # Trafilatura Markdown
metadata.json
webbundle.zip
```

正文抽取是衍生视图，不得把抽取预算变成原始网页资源截断。抽取失败可以返回 partial，但已经成功获取的 `source.html` 必须保留。

当前不使用 Monolith / SingleFile / ArchiveBox，也不恢复自研 `web_blocks.py` 作为生产主路径。

## 大结果与 Batch

创作者最近作品等交互预览使用预览能力；“全部作品 / 完整时间段 / 完整教材目录”等完整性任务使用 Batch。Batch Tool Result 分页只控制单次返回，不得成为采集上限；只有用户明确要求“最多 N 条”时才设置 `max_items`。

## OpenClaw 搜索协作

复杂检索可以使用宿主原生 sub-agent 做临时语义规划，但 child 只提出搜索角度、来源职责、query 和不确定性；Main Agent 必须重新判断。不要恢复 Flow、ResultSet、Selection、Plan 或固定 child 数量的持久架构。

当前语义规则见 `skills/learning-resource-flow/SKILL.md`；当前实现边界见 `docs/CURRENT_ARCHITECTURE.md`。