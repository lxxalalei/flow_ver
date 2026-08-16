---
name: learning-resource-flow
description: 学习资源（图书、课程、视频、文章、教材、音频、练习等）的搜索、比较、下载和归档入口。模型负责理解需求、规划搜索、判断结果与分类；education-resources MCP 只提供实际能力。
---

# Learning Resource Research

首要职责是**找到真正能帮助用户完成目标的学习资源**，不是走完某个后端状态机。

`education-resources` 是能力工具箱：搜索、按创作者浏览、检查资源、下载、查看/取消下载任务、归档文件。

## 1. 分工

Main Agent 负责：

- 理解用户真正要完成什么；
- 必要时澄清；
- 形成搜索角度、选择来源和 query；
- 判断候选是否有用；
- 决定是否补搜、Inspect、展示或下载；
- 下载后判断资料应归入哪个学习领域和主题；
- 向用户解释结果。

MCP 负责：

- 调用真实搜索脚本；
- 返回资源候选和 `resource_id`；
- 必要时调用真实 Inspect；
- 调用对应下载器；
- 返回下载 Job 的进度、文件和失败；
- 把成功下载的文件移动到资料库目录。

MCP 不负责保存“用户已经看过第几版候选”“选择版本”“Plan digest”等对话状态。Agent 直接依据当前会话里的真实候选和用户表达继续工作。

## 2. 搜索前先理解真正需求

不要把用户原话直接翻译成关键词。先判断：

1. 用户最终想完成什么：理解、观察、练习、实践、比较、备课、找版本、找具体文件，还是别的？
2. 资源实际给谁用？已有背景是否会明显改变内容尺度？
3. 什么样的结果才真正有用？
4. 哪些 must / prefer / exclude 会改变候选范围？
5. 是否存在会让搜索路线完全不同的关键歧义？

未知信息如果不影响路线，不问。只有不同回答会显著改变搜索方向、内容尺度、教材版本或筛选标准时才澄清。

## 3. 从目标形成互补搜索角度

先想用户需要获得什么价值，再想平台。常见角度：

- 理解：概念解释、图解、系统讲解；
- 观察：真实过程、动画、纪录片、实验现象；
- 练习：题卡、习题、可打印任务；
- 实践：实验、手工、项目、活动方案；
- 沉浸：故事、朗读、人物叙事；
- 比较/判断：方法、版本差异、经验、原始证据；
- 获取具体资源：书名、版本、ISBN、文件或详情页线索。

这些不是固定 taxonomy，也不需要凑齐。窄任务一个角度即可；较宽任务通常 1–3 个真正互补的角度。

## 4. 来源由内容需求驱动

- 视觉讲解、动画、实验、纪录片 → 视频来源；
- 系统课程、教材体系 → 教育平台；
- 故事、朗读、听书 → 音频来源；
- 方法、经验、比较 → 问答/社区/专业网页；
- 专业科普、官方材料 → 官方/专业 Web；
- 图书、版本、古籍 → 图书/古籍来源；
- PDF、讲义、课件、练习 → 文档来源或 Generic Web；
- 未单独接入的长尾站点 → Generic Web。

具体平台生态见 [`references/source-routing.md`](references/source-routing.md)。不要为了平台覆盖率机械扩散。

## 5. Query 要像真实搜索

Query 应体现“主题 + 当前要解决的切面”，只在确实影响召回时加入年级、版本、格式、语言等条件。书名类检索把书名放进《》（如《毛泽东选集》 人民出版社）——generic 引擎会把书名号转成精确短语匹配，避免长中文书名退化为“首字字典”噪音；图书类候选优先来自 nlc / annas-archive / shuge 等图书平台。

不要靠“优质、精品、高赞、权威、适合孩子”等评价词替代后续判断。同一来源首轮通常只发最有价值的一条 query，先看真实结果再决定是否补搜。

## 6. 搜完判断“有用”，不是判断“有结果”

对准备推荐的候选重点判断：

- 是否真正相关；
- 是否能帮助用户完成目标；
- 是否适合实际使用者；
- 是否满足 must / exclude；
- 是否有实质内容而非聚合、广告、空壳详情；
- 当前任务所需的可信度是否足够；
- 多个候选是否互补而非重复。

允许“不确定/尚未核验”。只有存在有意义的缺口，而且下一条明显不同的路线有机会补上时，才继续搜索。

## 7. Inspect 只服务于决策

Search 提供候选线索。只有某个事实会改变推荐或下载决策时才调用 `resource_inspect(resource_id)`，例如：

- 用户要求公开、无需登录；
- 需要确认真实文件/媒体格式；
- 要区分资源本体与 landing page；
- 标题和摘要不足以判断；
- 下载前需要确定当前实际可下载表示。

不要为了“流程完整” Inspect 全部候选。下载工具本身会在真正执行前 fresh Inspect。

## 8. MCP 调用

### 搜索

```json
resource_search({
  "search_tasks": [
    {"platform": "bilibili", "queries": ["火山喷发 原理 动画"]},
    {"platform": "generic",  "queries": ["火山形成 科普 儿童图文"]}
  ],
  "limit": 8
})
```

每个 task = 一个平台 + 一组搜索短语（字符串数组）。platform 是平台 id（bilibili / douyin / smartedu / ximalaya / generic 等）。注意没有顶层 `query` 字段——搜索单独一条也是放进 `queries` 数组。

返回候选后直接在当前对话里判断、比较和展示。`resource_id` 只是当前 MCP 进程里的资源句柄。补搜直接再次 Search，没有 ResultSet lineage、extend version、Flow version。

### 创作者内容

```text
resource_browse_creator(platform=..., creator_id=..., limit=...)
```

用于“列出这个账号的作品”这类枚举任务。

要**全量**枚举一个主页（几十到几百个作品）时，不要调大 browse 的 limit，改用批量模式：结果落盘不进对话，用分页读按需取。

```text
resource_batch_collect(platform=..., creator_id=..., mode="creator_full", max_items=...)
resource_batch_read(job_id=..., offset=..., limit=20)
```

批量任务和下载 Job 同一套句柄：`resource_job_status` 看进度、`resource_job_cancel` 取消、重启后存活。

### 用户选择

用户说“第 1、3 个”“这两个”“全部下载”时，直接根据当前对话里刚展示的候选确定对应 `resource_id`。不保存 Presentation/Selection，也不生成选择版本。

### 下载

**只有用户已经明确表达下载/获取意图后**，才调用：

```text
resource_download(
  resource_ids=[...],
  preferred_container="original"
)
```

这一次调用就是下载动作，不再经过 `prepare -> token -> start`。下载服务会在真正执行每个资源前 fresh Inspect，再调用实际下载器。

### Job

```text
resource_job_status(job_id=...)
resource_job_cancel(job_id=...)
```

只依据真实 `status / progress / files / failures` 判断结果。

### 归档

下载 Job 到达 `succeeded` 或 `partial` 且产生真实文件后，默认继续归档成功文件；除非用户明确表示只要临时下载、不需要整理进资料库。

Agent 根据资源内容选择 `domain_id` 和 `topic`，然后调用：

```text
resource_archive(
  job_id=...,
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

分类确实不确定时不要为了归档追问用户，可将 `domain_id` 留空进入“待分类”。归档只是移动真实文件并返回最终路径，不创建 Archive/Asset/Bundle 状态链。

领域表和目录规则见 [`references/archive.md`](references/archive.md)。

### MCP 重启

`resource_id` 和 Job 状态是进程内状态。MCP 进程重启后旧句柄可能失效，重新搜索即可。不要为低频恢复场景构造 Flow、SQLite 状态机或源码恢复流程。

## 9. 数据面边界

资源候选、可访问性、下载和归档事实使用 `education-resources` 工具。不要为了恢复内部状态去读项目源码，也不要猜测不存在的 Provider、URL 或资源 ID。

需要登录时按真实 `AUTH_REQUIRED` 处理，不伪装成功，也不静默切换不等价下载器。

## 10. Few-shot

### A. 火山科普

用户：“帮孩子找一些火山科普资料，形式你看着办。”

更好的理解：需要“为什么喷发”的原理理解 + “喷发是什么样”的过程观察。

```text
角度1 原理理解 → 专业科普/教育来源 → 火山形成 喷发原理 科普
角度2 过程观察 → 视频来源 → 火山喷发 原理 动画 实验演示
```

### B. 信息已经足够

用户：“找适合小学三年级自己看的中文太阳系图文，先不要下载。”

对象、主题、语言、载体都明确。直接搜索、审查、展示，不调用 Download。

### C. 用户明确下载

用户看完候选后说：“第 2 和第 4 个帮我下下来。”

直接把对应 `resource_id` 交给 `resource_download`。Job 完成后将成功文件归档到合理领域/主题，不再额外创建 Plan 或要求用户确认一次。

## 11. Advanced references

需要时再读：

- 对话与背景边界：[`references/conversation.md`](references/conversation.md)
- 平台生态/长尾来源：[`references/source-routing.md`](references/source-routing.md)
- 多轮检索：[`references/retrieval.md`](references/retrieval.md)
- Inspect：[`references/inspection.md`](references/inspection.md)
- 下载：[`references/acquisition.md`](references/acquisition.md)
- 归档：[`references/archive.md`](references/archive.md)
- 多 Agent 搜索规划实验：[`references/multi-agent.md`](references/multi-agent.md)

普通搜索默认由 Main Agent 自己完成需求理解、来源选择和 query 规划。不要因为存在 multi-agent 能力就自动 spawn child。
