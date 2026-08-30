---
name: learning-resource-flow
description: 学习资源搜索与获取的语义决策 Skill。负责理解用户目标、设计互补搜索路线、判断候选与缺口、决定继续或停止、理解用户选择；OpenClaw web_search 负责开放互联网发现，education-resources MCP 负责专门资源能力和文件副作用。
---

# Learning Resource Research

这个 Skill 只负责一件事：让 Agent 在学习资源任务里做正确的语义决策。

> **Agent 负责目标、路线、判断与选择；工具负责事实与执行。**

每一轮基于当前上下文形成以下即时判断：

```text
Task      现在是 Research / Locate / Browse / Enumerate / Acquire / Transform 中哪类任务？
Goal      用户真正要完成什么；must / prefer / exclude 是什么？
Coverage  为完成 Goal，还需要哪些不同学习价值或证据角色？
Sources   哪些来源对当前 Coverage 有直接价值匹配？
Evidence  当前候选实际证明了什么？
Gap       还缺什么具体价值或会改变决策的关键事实？
Next      下一步能新增什么价值；没有新增价值时 Stop。
```

这些判断只服务当前对话。根据 Goal、Evidence 和 Gap 选择当前真正需要的能力，工具组合由任务自然产生。

## 1. Goal：还原任务，再形成检索表达

先理解：

- 用户最终想理解、观察、练习、实践、比较、备课、找版本、获取文件还是转换内容；
- 资源实际给谁使用，哪些背景会明显改变内容尺度；
- 哪些条件是真正的 must / prefer / exclude；
- 什么样的结果才算对这个用户有用。

探索策略只作用于当前任务；must / prefer / exclude 保持用户原有强度。

### 只有答案会改变路线时才澄清

提问前判断：**不同答案是否会让我去找明显不同的东西？**

当答案会实质改变路线，且已有上下文无法可靠确定时，优先问一个信息增益最高的问题。例如“一年级数学资料”中的同步讲解 / 基础练习 / 趣味拓展会导向明显不同材料，此时先确认主要方向。

当答案不会实质改变路线时，由 Agent 根据已有上下文做合理选择并继续行动。用户已经说“你决定”“都可以”“先看看”时，由 Agent 承担对应选择。

详见 [`references/conversation.md`](references/conversation.md)。

## 2. Coverage：按学习价值拆路线

搜索路线来自用户需要的不同价值，例如：

- 理解：概念、原理、系统讲解；
- 观察：真实过程、动画、纪录片、实验现象；
- 练习：习题、题卡、worksheet、可打印任务；
- 实践：实验、手工、项目、活动方案；
- 沉浸：故事、朗读、人物叙事；
- 比较：方法、版本、观点、原始证据；
- 获取：明确书名、版本、ISBN、文件或详情页。

“火山科普 / 火山知识 / 儿童火山知识”通常属于同一搜索空间；“喷发原理理解 / 真实喷发观察 / 可打印实验单”属于不同 Coverage。

路线数量由尚未满足的实质学习价值决定：窄任务一条路线即可覆盖时直接推进；复合任务存在不同价值缺口时分别探索；新增路线无法带来新的实质价值时进入 Stop 判断。

## 3. Sources：Direct Value Match + Reasoned Fan-out

来源优势作为召回先验，用于判断某个来源何时值得参与、适合怎样查询；候选质量由真实结果决定。

派发时判断：

1. 当前 Coverage 需要什么内容形态或证据；
2. 哪些来源对此存在直接、具体的价值匹配；
3. 应走 OpenClaw `web_search`、MCP `resource_search`，还是两者都参与；
4. 在对应来源里，人会怎么搜。

规则：

- 一个来源与当前 Coverage 存在直接价值匹配即可参与召回；
- 多个来源可以竞争同一个 Coverage；
- 平台已接入、用户身份和理论可用性只作为背景信息，具体派发由当前 Coverage 的价值匹配决定；
- 相近价值可以在同一来源中使用一条自然 query 覆盖，实质不同的搜索空间再拆分路线；
- query 使用“主题 + 当前切面”，候选质量在结果返回后根据真实证据判断；
- Gap 由尚未满足的用户价值或决策事实定义。

### Web 与 MCP 是并列召回能力

OpenClaw `web_search` 负责开放互联网跨站发现；MCP `resource_search` 负责已接入的专门资源生态。二者根据当前 Coverage 并列参与召回。

开放式、来源不限、需要官方/专业/图文/文档/长尾网页时，Web 往往有直接价值。用户明确限定平台、已经给出具体 URL，或窄任务已被专门生态直接覆盖时，可以直接使用对应专门能力。通用 Web 发现由宿主 `web_search` 承担，MCP 保持专门资源能力边界。

具体平台先验与 trigger / non-trigger 见 [`references/source-routing.md`](references/source-routing.md)。

## 4. Evidence：按真实证据判断候选

搜索阶段偏 Recall，评估阶段偏 Precision。具体候选的评价只由当前真实证据决定；来源先验只用于召回。

候选区分为：

```text
Reject         当前证据表明无法解决 Goal
Hold           可能有用，但仍缺一个会改变决策的关键事实
Recommendable  当前证据已经足够说明为什么值得给用户看
```

重点看 relevance、usefulness、target fit、constraint fit、substantive、credibility、complementarity。

证据不足的事实保持 unknown；候选描述严格停留在工具实际提供的标题、元数据、摘要、页面事实和可验证信息范围内。

### Web 结果保持 Web Candidate 身份

`web_search` 返回的 URL、标题、摘要/片段、域名、日期构成当前 Web Candidate 的证据。snippet 只支持其实际显示的事实。

具体 URL 在以下场景进入 MCP：

- 用户已经选中并要求保存、下载、归档或转换；
- 页面本体存在一个会改变推荐/获取决策的关键事实需要进一步确认；
- 后续需要 Inspect / Download / HTML Design / Archive。

Web 与 MCP 命中同一个实际资源时，依据当前可见 URL、平台稳定标识、标题/作者等事实做语义去重；稳定资源身份继续沿用 URL 或平台稳定 ID。

## 5. Gap → Next → Stop：每一步都增加实质价值

Gap 由当前 Evidence 中仍未满足的用户价值或会改变决策的关键事实产生，例如：

- 用户要理解机制，而当前只有题目解析；
- 用户要练习，而当前只有讲解；
- 用户要可打印材料，而当前只有视频；
- 用户要版本事实，而当前只有泛化介绍；
- 开放式任务目前只有同质短视频，而可靠结构化解释仍明显缺失。

继续 Search / Inspect 前，明确下一步会进入什么实质不同的搜索空间，或补充什么会改变决策的事实。能够说明新增价值时继续；当前 Evidence 已足够支持用户进入选择或使用阶段时 Stop。

停止条件由 Goal 的实际覆盖程度决定。

详见 [`references/retrieval.md`](references/retrieval.md)。

## 6. Inspect：只补会改变决策的事实

当高潜候选存在一个未知事实，并且这个事实会改变推荐、选择或获取决策时使用 Inspect，例如：

- 是否真是资源本体而非 landing page；
- 版本、创作者、语言等关键事实是否明确；
- 用户要求的登录条件、格式或可获取性是否满足；
- Web snippet 是否足以支持当前关键判断。

Inspect 的范围由这个决策缺口决定。

详见 [`references/inspection.md`](references/inspection.md)。

## 7. Browse 与 Enumerate：预览和完整性对应不同完成条件

Browse 获取足够判断的代表性内容，并在这些内容已经足以刻画来源或支持选择时完成。

Browse / Preview 优先使用匿名可达路线。某一路线遇到认证或风控时，先寻找匿名可达的等价发现路线；当任务价值确实依赖认证能力且匿名路线无法满足时进入 Session。

Enumerate 面向数据完整性任务，例如：

- 某创作者全部作品；
- 某合集/专辑/教材全部子资源；
- 某明确时间范围完整结果。

完整枚举使用结构化 Expand / Job 能力直到来源真实结束。聊天分页只控制单次展示量；完整性由来源终止信号和 Expand Job 的完整结果决定。

## 8. Selection：用稳定资源身份承接用户选择

用户说“第 2 个”“这两个”“刚才那个作者的视频”时，把指代映射到用户已经实际看到且能够合理指代的候选。

当前对话中的稳定资源身份优先使用：

```text
URL
稳定平台 ID
标题
作者
来源
```

`resource_id` 只作为当前 MCP 进程内的操作句柄；跨轮恢复同一资源时使用上下文中真实存在的 URL、稳定平台 ID 及其他可验证身份事实。

可复用身份严格来自当前上下文真实出现过的事实。只有标题和作者时，就以标题和作者重新定位同一资源；已有 URL 时直接复用该 URL。

用户选中已经展示的 Web URL 后，直接以这个 URL 进入 `resource_import_url`。临时句柄失效时，先根据已知稳定身份恢复同一个资源；身份事实不足时重新进入发现阶段。

## 9. Acquire / Transform：明确意图驱动副作用

Download / Archive / Transform 只在用户已经表达对应意图且目标对象明确时执行。

- “先看看”“先别下载” → 保持发现、判断和选择阶段；
- “第 2 个帮我下载”“这个网页保存下来”且对象清楚 → 直接执行对应副作用；
- 下载、归档或转换的完成状态以真实 Tool / Job 终态和实际文件结果为准。

Web URL 的典型获取路径是：

```text
已选具体 URL
→ resource_import_url
→ 决策需要时 Inspect
→ Download
```

下载结果需要整理时进入 Archive；用户明确要求精美 HTML / 优化排版时进入 HTML Design。

详见 [`references/acquisition.md`](references/acquisition.md)、[`references/archive.md`](references/archive.md)、[`references/html-design.md`](references/html-design.md)。

## 10. 面向用户：呈现资源、真实链接和判断

通常展示：

- 真正必要的一个澄清问题；
- 少量真正值得选择的候选及差异；
- 每个候选的真实来源；
- 当前仍未确认、且会影响选择的重要事实；
- 用户要求副作用后，真实执行结果。

真实搜索或资源结果提供稳定、可访问 URL 时，候选同时展示该真实 URL；Web 与 MCP 候选采用同一规则。

具体资源链接只使用真实工具结果或当前上下文已经确认的稳定 URL。当前结果没有可用 URL 时，明确显示当前缺少可用链接。

用户至少能看到：

```text
标题 / 来源 / 真实链接 / 为什么值得选
```

Coverage、Gap、Dispatch、matched_queries、runs、内部评分等概念保留在内部判断中；用户看到与当前任务决策直接相关的结果。

## References

当前任务需要相应规则细节时读取对应 reference：

- 需求理解与澄清：[`references/conversation.md`](references/conversation.md)
- 多轮检索、Coverage / Gap / Stop：[`references/retrieval.md`](references/retrieval.md)
- 来源生态与路由：[`references/source-routing.md`](references/source-routing.md)
- 候选事实检查：[`references/inspection.md`](references/inspection.md)
- 获取意图与下载结果：[`references/acquisition.md`](references/acquisition.md)
- 内容感知的离线 HTML 设计：[`references/html-design.md`](references/html-design.md)
- 归档分类：[`references/archive.md`](references/archive.md)
