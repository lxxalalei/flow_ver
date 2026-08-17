---
name: learning-resource-flow
description: 学习资源（图书、课程、视频、文章、教材、音频、练习等）的搜索、比较、下载和归档入口。模型负责理解需求、规划搜索、判断结果与分类；education-resources MCP 只提供实际能力。
---

# Learning Resource Research

首要职责是**找到真正能帮助用户完成目标的学习资源**，不是走完某个后端状态机。

`education-resources` 是能力工具箱：平台搜索、创作者浏览、外部 URL 导入、资源检查、下载、批量枚举、Job 状态和文件归档。

普通网页发现默认使用宿主 OpenClaw / anysearch 的 Web Search；选中具体网页后用 `resource_import_url(source_url)` 进入 MCP 的 Inspect → Download → Archive 管道。MCP 的 `platform="generic"` 只在宿主 Web Search 中文召回不足时补搜，不机械加入正常搜索任务。

## 1. 分工

Main Agent 负责：

- 理解用户真正要完成什么；
- 形成搜索角度、来源和 query；
- 判断相关性、质量、是否满足目标；
- 决定是否补搜、Inspect、展示或下载；
- 理解用户选中了哪个具体资源；
- 下载后决定归档领域和主题；
- 向用户解释结果。

MCP 负责：

- 调用真实平台搜索/浏览脚本；
- 把具体 URL 注册成临时 `resource_id`；
- Inspect 当前资源事实；
- 调用实际 Downloader；
- 执行长任务、进度和取消；
- 大规模枚举结果落盘并分页读取；
- 移动文件到资料库。

MCP 不保存“用户看过第几版候选”“用户选择版本”“Plan digest”等对话语义，也不为 `resource_id` 建长期数据库。

## 2. 搜索前先理解真正需求

不要把用户原话机械翻成关键词。先判断：

1. 用户最终要完成什么：理解、观察、练习、实践、比较、备课、找版本、找具体文件，还是别的？
2. 资源给谁用？已有背景是否明显改变内容尺度？
3. 什么样的结果才真正有用？
4. 哪些 must / prefer / exclude 会改变候选范围？
5. 是否存在会让搜索路线完全不同的关键歧义？

窄主题（如“火山喷发原理”“三年级数学口算”）可直接搜索。宽主题（如“历史”“科学”“文学名著”）如果不同子方向会明显改变搜索路线，应先收敛；用户明确说“你定/都行”时，可自行选一个代表性方向并说明，不必反复追问。

## 3. 从目标形成互补搜索角度

先想用户需要获得什么价值，再想平台。常见角度包括：

- 理解：概念解释、图解、系统讲解；
- 观察：真实过程、动画、纪录片、实验；
- 练习：题卡、习题、可打印任务；
- 实践：实验、手工、项目、活动方案；
- 沉浸：故事、朗读、人物叙事；
- 比较：方法、版本差异、经验、原始证据；
- 获取具体资源：书名、版本、ISBN、文件或详情页。

这些不是固定 taxonomy。窄任务一个角度即可；较宽任务通常 1–3 个真正互补的角度。

## 4. 来源由内容需求驱动

- 视觉讲解、动画、实验、纪录片 → 视频来源；
- 系统课程、教材体系 → 教育平台；
- 故事、朗读、听书 → 音频来源；
- 方法、经验、比较 → 问答/社区/专业网页；
- 专业科普、官方材料 → 官方/专业 Web；
- 图书、版本、古籍 → 图书/古籍来源；
- PDF、讲义、课件、练习 → 文档来源；
- 未单独接入的长尾站点 → 宿主 Web Search，选中后 `resource_import_url`。

具体平台生态见 [`references/source-routing.md`](references/source-routing.md)。不要为了平台覆盖率机械扩散。

## 5. Query 要像真实搜索

Query 应体现“主题 + 当前要解决的切面”。只在确实影响召回时加入年级、版本、格式、语言等条件。

不要用“优质、精品、高赞、权威、适合孩子”等评价词替代后续判断。同一来源首轮通常只发最有价值的一条 query，先看真实结果再决定是否补搜。

## 6. 搜完判断“有用”，不是判断“有结果”

对准备推荐的候选重点判断：

- 是否真正相关；
- 是否能帮助用户完成目标；
- 是否适合实际使用者；
- 是否满足 must / exclude；
- 是否有实质内容而非聚合、广告、空壳详情；
- 当前任务所需可信度是否足够；
- 多个候选是否互补而非重复。

允许“不确定/尚未核验”。只有存在有意义的缺口，而且下一条明显不同的路线有机会补上时，才继续搜索。

## 7. Inspect 只服务于决策

Search 提供候选线索。只有某个事实会改变推荐或下载决策时才调用：

```text
resource_inspect(resource_id=...)
```

例如需要确认真实格式、登录要求、资源本体还是 landing page、标题摘要不足以判断等。不要为了“流程完整” Inspect 全部候选。真正下载前 Download 会 fresh Inspect。

## 8. MCP 调用

### 平台搜索

```json
resource_search({
  "search_tasks": [
    {"platform": "bilibili", "queries": ["火山喷发 原理 动画"]},
    {"platform": "smartedu", "queries": ["火山形成 科普 图文"]}
  ],
  "limit": 8
})
```

`resource_id` 只是当前 MCP 进程里的临时资源句柄。

### 外部链接进管道

宿主 Web Search 找到并选中具体链接后：

```text
resource_import_url(source_url="https://...")
```

注册后可继续 `resource_inspect` / `resource_download` / `resource_archive`。

### 创作者预览与完整枚举

小规模预览：

```text
resource_browse_creator(platform=..., creator_id=..., limit=50)
```

完整主页不要把 browse 的 limit 调到几百上千，改用 Batch：

```text
resource_batch_collect(
  platform=...,
  creator_id=...,
  mode="creator_full"
)
resource_batch_read(job_id=..., offset=0, limit=20)
```

**完整枚举默认不传 `max_items`。** 让平台翻页直到真实结束。只有用户明确说“最多 N 条”时才传：

```text
max_items=N
```

`resource_batch_read` 单页最多 50 条只是控制一次 Tool Result 大小，不代表只保存 50 条，也不能据此提前结束完整枚举。

### 用户选择

用户说“第 1、3 个”“这两个”“全部下载”时，根据当前对话中已经展示的候选确定他真正选中的具体资源。Agent 应保留这个选择的语义：URL、平台、标题、作者、稳定平台 ID 等；不要把用户选择等同于某个永久 `resource_id`。

### 下载

只有用户已经明确表达下载/获取意图后才调用：

```text
resource_download(
  resource_ids=[...],
  preferred_container="original"
)
```

调用后完整资源快照会进入该 Job 的 `request.json`。后续 detached worker 不依赖原 `resource_id`。

### Job

```text
resource_job_status(job_id=...)
resource_job_cancel(job_id=...)
```

Download / Batch Job 是文件持久的真实执行任务，可以跨 MCP / Gateway 重启继续。worker 已死且 Job 尚未完成时会显示 `interrupted`；需要重新发起任务，不构造断点状态机。

### 归档

下载 Job 到达 `succeeded` 或 `partial` 且产生真实文件后，默认继续归档，除非用户明确表示只要临时下载。

```text
resource_archive(
  job_id=...,
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

Agent 决定领域/主题；分类确实不确定时可进入“待分类”。归档只移动真实文件，不创建 Archive/Asset/Bundle 状态链。

领域表见 [`references/archive.md`](references/archive.md)。

## 9. MCP 重启与句柄恢复

`resource_id` 是进程内句柄，MCP 重启后可能失效。**不要因此重新执行整套研究任务，也不要读源码尝试恢复内部状态。**

当调用返回 `RESOURCE_NOT_FOUND` 时，按以下顺序恢复已经选中的那个资源：

1. **已知原 URL**：直接 `resource_import_url(URL)`，获得新的 `resource_id`，继续原操作。
2. **已知平台稳定 ID**：按该平台唯一标识精确重新定位资源，再获得新句柄。
3. **只有标题 / 作者 / 平台**：只针对这个具体资源做一次最小精确搜索。
4. **连原资源都无法确定**：最后才回到原始搜索任务重新发现候选，并重新确认不要下载错对象。

这不是“重新研究一次”，而是“重新建立对已经选中资源的操作句柄”。

Job 与此不同：Job 是正在执行的真实副作用，因此使用 `job_id` + 文件状态跨重启保留。

## 10. 数据面边界

资源候选、可访问性、下载、Batch 和归档事实使用 `education-resources` 工具。不要猜测不存在的 Provider、URL、资源 ID，也不要为了内部状态恢复去读项目源码。

需要登录时按真实 `AUTH_REQUIRED` 处理，不伪装成功，也不静默切换不等价下载器。

## 11. Few-shot

### A. 宽主题

用户：“能帮我搜一些给孩子看的历史资料吗？”

主题太宽且不同方向会明显改变资源来源，先收敛年龄/方向；用户若明确让模型决定，则选一个代表性主题继续，不机械铺满所有平台。

### B. 火山科普

用户：“帮孩子找一些火山科普资料，形式你看着办。”

可以拆成“为什么喷发”的原理理解 + “喷发是什么样”的过程观察，再选择互补来源。

### C. 信息已经足够

用户：“找适合小学三年级自己看的中文太阳系图文，先不要下载。”

对象、主题、语言、载体都明确。直接搜索、判断、展示，不调用 Download。

### D. 用户明确下载

用户看完候选后说：“第 2 和第 4 个帮我下下来。”

直接下载对应资源。若此时 MCP 恰好重启导致旧 `resource_id` 失效，但当前对话仍有两个选中资源的 URL，则分别 `resource_import_url` 后继续下载，不重新跑整个搜索任务。

## 12. Advanced references

需要时再读：

- 对话与背景边界：[`references/conversation.md`](references/conversation.md)
- 平台生态/长尾来源：[`references/source-routing.md`](references/source-routing.md)
- 多轮检索：[`references/retrieval.md`](references/retrieval.md)
- Inspect：[`references/inspection.md`](references/inspection.md)
- 下载：[`references/acquisition.md`](references/acquisition.md)
- 归档：[`references/archive.md`](references/archive.md)
- 多 Agent 搜索规划实验：[`references/multi-agent.md`](references/multi-agent.md)

普通搜索默认由 Main Agent 自己完成需求理解、来源选择和 query 规划。不要因为存在 multi-agent 能力就自动 spawn child。
