# TOOLS.md

运行时能力以 OpenClaw 实际暴露的 Tool `name / description / input schema / return` 为准；不要从历史 contracts、legacy 文件或源码实现猜测 Tool 参数和状态。

当前有两个 MCP：

- `education-resources`：真实资源能力，包括平台搜索、创作者预览、URL 导入、Inspect、下载、Batch、Job 状态/取消和归档。
- `session-manager`：辅助登录态能力，只负责登录引导、浏览器捕获后的最小会话保存、状态查询和删除。

## 资源能力边界

Main Agent / Skill 负责理解需求、设计搜索任务、选择来源、判断候选、识别 Gap、理解用户选择和获取意图；`education-resources` 负责实际平台调用与文件副作用。

普通 Web 发现优先使用宿主 Web Search。选中具体网页后，再把 URL 交给 `resource_import_url`。不要把 `platform="generic"` 当成默认全网搜索入口。

`resource_id` 是当前 MCP 进程内的临时操作句柄；URL、平台原生 ID 等才是资源的稳定语义身份。`job_id` 只为真实长任务保存运行状态。

用户已经明确选中资源并明确要求“下载 / 保存 / 获取下来”时，可以直接使用 `resource_download`，不创建 `prepare -> confirm -> start` 二次确认流程。归档接受真实下载 Job 的 `job_id`，不使用 `asset_id`。

## 登录态不是前置流程

不要在每次搜索或下载前先调用 `session-manager`。只有以下情况需要它：

- 某个真实资源能力返回了 `AUTH_REQUIRED`；
- 用户明确要求登录、保存、检查或删除某个平台会话。

平台支持登录不等于所有操作都需要登录。`requires_login=true` 表示该平台存在需要登录态的能力；不能据此推断当前搜索或下载一定需要认证。`status=not_required` / `requires_login=false` 的平台不得发起登录流程。

### SmartEdu

SmartEdu 的公共搜索和公共教材索引走匿名访问，不自动携带 session-manager 保存的浏览器 token。公共搜索若返回 `NETWORK_BLOCKED` / `PLATFORM_UNAVAILABLE`，应按当前网络出口、IP 风控或平台访问失败处理，不要通过“重新登录 / 补 token”自动重试。

具体资源的 Inspect / Download 如果真实返回 `AUTH_REQUIRED`，再进入 session-manager 登录态处理。

### Anna's Archive

`annas-archive` 在本项目中是 **Libgen 镜像后端的图书发现/获取能力**：使用兼容 MD5 标识，搜索和下载走公共 Libgen 镜像，不依赖 Anna's Archive 会员登录。

因此：

- 不要为 `annas-archive` 调用登录引导；
- 不要因为展示名称是“安娜的档案”就访问会员下载页；
- 以 `education-resources` 返回的镜像候选、Inspect 和 Download 结果为事实。

## 大结果与 Batch

创作者最近作品等交互预览使用预览能力；“全部作品 / 完整时间段 / 完整教材目录”等完整性任务使用 Batch。Batch 的 Tool Result 分页只控制单次返回，不得成为采集上限；只有用户明确要求“最多 N 条”时才设置 `max_items`。

## OpenClaw 搜索协作

复杂检索可以使用宿主原生 sub-agent 做临时语义规划，但 child 只提出搜索角度、来源职责、query 和不确定性；Main Agent 必须重新判断。不要为此恢复 Flow、ResultSet、Selection、Plan 或固定 child 数量的持久架构。

当前语义规则见 `skills/learning-resource-flow/SKILL.md` 及其 active references；当前实现边界见 `docs/CURRENT_ARCHITECTURE.md`。
