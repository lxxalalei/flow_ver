---
name: learning-resource-flow
description: 学习资源搜索与获取的语义决策 Skill。负责理解用户目标、设计互补搜索路线、判断候选与缺口、决定继续或停止、理解用户选择；OpenClaw web_search 负责开放互联网发现，education-resources MCP 负责专门资源能力和文件副作用。
---

# Learning Resource Research

这个 Skill 只负责一件事：让 Agent 在学习资源任务里做正确的语义决策。

> **Agent 负责目标、路线、判断与选择；工具负责事实与执行。**

不要把 Search / Expand / Inspect / Download / Archive 组织成固定流水线，也不要创建 Flow、Plan、CoverageState、Selection、digest、canonical/projection 等持久语义状态。

每一轮只需要在当前上下文中回答：

```text
Task      现在是 Research / Locate / Browse / Enumerate / Acquire / Transform 中哪类任务？
Goal      用户真正要完成什么；must / prefer / exclude 是什么？
Coverage  为完成 Goal，还需要哪些不同学习价值或证据角色？
Sources   哪些来源对当前 Coverage 有直接价值匹配？
Evidence  当前候选实际证明了什么？
Gap       还缺什么具体价值或会改变决策的关键事实？
Next      下一步能新增什么价值；如果说不出来就 Stop。
```

这些只是即时判断框架，不要求向用户展示，也不落盘。

## 1. Goal：先还原任务，不要直接改写成关键词

先理解：

- 用户最终想理解、观察、练习、实践、比较、备课、找版本、获取文件还是转换内容；
- 资源实际给谁使用，哪些背景会明显改变内容尺度；
- 哪些条件是真正的 must / prefer / exclude；
- 什么样的结果才算对这个用户有用。

不要把探索策略误写成用户长期偏好，也不要把 prefer 擅自升级成 must。

### 只有答案会改变路线时才澄清

提问前问自己：**不同答案是否会让我去找明显不同的东西？**

如果会，而且无法从已有上下文可靠确定，优先问一个信息增益最高的问题。例如“一年级数学资料”中的同步讲解 / 基础练习 / 趣味拓展会导向明显不同材料，就应先确认主要方向。

如果不会，就直接行动。不要为了平台、数量、格式或完整画像补字段。用户已经说“你决定”“都可以”“先看看”时，不要把选择责任重新推回去。

详见 [`references/conversation.md`](references/conversation.md)。

## 2. Coverage：按学习价值拆路线，不按平台拆路线

搜索路线来自用户需要的不同价值，例如：

- 理解：概念、原理、系统讲解；
- 观察：真实过程、动画、纪录片、实验现象；
- 练习：习题、题卡、worksheet、可打印任务；
- 实践：实验、手工、项目、活动方案；
- 沉浸：故事、朗读、人物叙事；
- 比较：方法、版本、观点、原始证据；
- 获取：明确书名、版本、ISBN、文件或详情页。

“火山科普 / 火山知识 / 儿童火山知识”通常还是同一搜索空间；“喷发原理理解 / 真实喷发观察 / 可打印实验单”才是不同 Coverage。

路线数量不是目标。窄任务一条可能足够；复合任务可能需要多条。不要为了少调用工具压掉真实价值差异，也不要为了显得全面凑固定数量。

## 3. Sources：Direct Value Match + Reasoned Fan-out

来源优势是搜索先验，不是内容边界。

派发时只判断：

1. 当前 Coverage 需要什么内容形态或证据；
2. 哪些来源对此存在直接、具体的价值匹配；
3. 应走 OpenClaw `web_search`、MCP `resource_search`，还是两者都参与；
4. 在对应来源里，人会怎么搜。

规则：

- 一个来源有直接价值匹配即可参与，不要求提供其他来源完全没有的独占价值；
- 多个来源可以竞争同一个 Coverage；
- “平台已接入”“用户是学生”“理论上可能有”都不足以派发；
- 不做 `Coverage × Platform` 笛卡尔积；同一来源的一条自然 query 可以覆盖相近价值；
- query 使用“主题 + 当前切面”，不要用“优质、高赞、精品、权威”等评价词代替后续判断；
- 未搜索的平台本身不是 Gap。

### Web 与 MCP 是并列召回能力

OpenClaw `web_search` 用于开放互联网跨站发现；MCP `resource_search` 用于已接入的专门资源生态。二者不是主搜索 / fallback，也不要在 MCP 里再包装通用 Web Search。

开放式、来源不限、需要官方/专业/图文/文档/长尾网页时，Web 往往有直接价值。用户明确限定平台、已经给出具体 URL，或窄任务已被专门生态直接覆盖时，可以跳过 Web。

具体平台先验与 trigger / non-trigger 见 [`references/source-routing.md`](references/source-routing.md)。

## 4. Evidence：判断候选是否真的有用

搜索阶段偏 Recall，评估阶段偏 Precision。具体候选只根据当前真实证据判断，不因为平台典型优势预加质量分。

候选只需要区分：

```text
Reject         明显不能解决当前 Goal
Hold           可能有用，但缺少一个会改变决策的关键事实
Recommendable  当前证据已经足够说明为什么值得给用户看
```

重点看 relevance、usefulness、target fit、constraint fit、substantive、credibility、complementarity。

允许 unknown。不要根据标题、平台、播放量或模型常识补造未显示的资源事实。

### Web 结果先是候选，不是 MCP Resource

`web_search` 的 URL、标题、摘要/片段、域名、日期只能支持它们实际显示的事实。snippet 不能自动升级成页面全文事实。

不要把 Web 命中批量 `resource_import_url`。只有具体 URL 满足以下至少一项时才进入 MCP：

- 用户已经选中并要求保存、下载、归档或转换；
- 页面本体缺少一个会改变推荐/获取决策的关键事实；
- 后续需要 Inspect / Download / HTML Design / Archive。

Web 和 MCP 命中同一个实际资源时，按当前可见 URL、平台稳定标识、标题/作者等证据语义去重，不创建跨工具持久 ID。

## 5. Gap → Next → Stop：每一步都要能说明新增价值

Gap 必须来自当前结果，而不是来自平台清单。

合法 Gap 例如：

- 用户要理解机制，但只有题目解析；
- 用户要练习，但只有讲解；
- 用户要可打印材料，但只有视频；
- 用户要版本事实，但只有泛化介绍；
- 开放式任务只有同质短视频，而可靠结构化解释仍明显缺失。

以下都不是充分 Gap：

- 还有平台没搜；
- 还能换关键词；
- 可能还有更好的；
- 搜索结果还有下一页。

继续 Search / Inspect 前必须能回答：**下一步会进入什么实质不同的搜索空间，或补什么会改变决策的事实？** 如果说不出来，就停止。

停止看 Goal 是否已充分覆盖，不看候选数量，也不要求所有 eligible source 都搜过。停止只表示当前证据足够进入选择或使用阶段，不表示“全网没有更好资源”。

详见 [`references/retrieval.md`](references/retrieval.md)。

## 6. Inspect：只为高潜候选补决策事实

只有未知事实会改变推荐、选择或获取决策时才 Inspect，例如：

- 是否真是资源本体而非 landing page；
- 版本、创作者、语言等关键事实不清楚；
- 用户明确要求无需登录、特定格式或可获取性；
- Web snippet 不足以判断。

不要为了流程完整 Inspect 全部候选，也不要把 Web 候选固定 Import → Inspect。

详见 [`references/inspection.md`](references/inspection.md)。

## 7. Browse 与 Enumerate：预览和完整性是两类任务

Browse 只需要拿到足够判断的代表性内容；来源还有更多页不意味着继续翻到底。

Browse / Preview 默认走匿名可达路线。某一路线被认证或风控挡住时，先判断是否存在其他匿名可达的等价发现路线；登录不应成为普通浏览的默认前置条件。只有任务价值确实依赖认证能力且匿名路线不足时，才进入 Session。

Enumerate 则是数据完整性任务，例如：

- 某创作者全部作品；
- 某合集/专辑/教材全部子资源；
- 某明确时间范围完整结果。

完整枚举应使用结构化 Expand / Job 能力直到来源真实结束；聊天一次展示多少条不能变成采集上限。`web_search` 不是已知创作者或容器完整枚举的替代品。

## 8. Selection：用户选择的是资源，不是临时句柄

用户说“第 2 个”“这两个”“刚才那个作者的视频”时，只能映射到他实际看到并能合理指代的候选。

优先保留当前对话中**真实存在**的资源身份：

```text
URL
稳定平台 ID
标题
作者
来源
```

不要把临时 `resource_id` 当永久身份。

特别注意：**只能复用当前上下文真实出现过的 URL / 稳定标识。** 如果上下文只提供了标题和作者，就不能声称“链接已经保留”；应基于现有真实身份重新定位，必要时再搜索或 Import，而不是虚构一个 URL。

Web 候选不需要先拥有 MCP `resource_id` 才能被用户选择。用户选中已经展示的 Web URL 后，直接复用该 URL 进入 `resource_import_url`，不要重新 Web Search 去猜同一篇。

临时句柄失效时，优先根据**确实已知**的 URL 或稳定平台标识恢复同一个资源；无法确认原资源时才重新进入发现阶段。

## 9. Acquire / Transform：副作用只服从明确用户意图

Download / Archive / Transform 都是副作用。

- 用户只是“先看看”“先别下载” → 只发现和判断；
- 用户明确“第 2 个帮我下载”“这个网页保存下来”且对象清楚 → 直接执行，不制造形式确认；
- 成功与否只依据真实工具结果，不能把“已开始”说成“已完成”。

Web URL 的典型获取路径是：

```text
已选具体 URL
→ resource_import_url
→ 必要时 Inspect
→ Download
```

不是所有任务都需要每一步。

下载后需要整理时再 Archive；网页只有用户明确要求精美 HTML / 优化排版时才进入 HTML Design。

详见 [`references/acquisition.md`](references/acquisition.md)、[`references/archive.md`](references/archive.md)、[`references/html-design.md`](references/html-design.md)。

## 10. 面向用户：给资源、真实链接和判断，不给内部流程

通常只展示：

- 真正必要的一个澄清问题；
- 少量真正值得选择的候选及差异；
- 每个候选的真实来源；
- 当前仍未确认、且会影响选择的重要事实；
- 用户要求副作用后，真实执行结果。

**只要真实搜索/资源结果提供稳定、可访问 URL，展示候选时必须同时展示该真实 URL；Web 与 MCP 候选一视同仁。**

链接必须来自真实工具结果或当前上下文已经确认的稳定资源身份。不要用 `resource_id`、query、平台首页或自行拼接地址冒充具体资源链接。当前结果确实没有 URL 时就明确说没有，不补造。

用户应至少能看到：

```text
标题 / 来源 / 真实链接 / 为什么值得选
```

不要把 Coverage、Gap、Dispatch、matched_queries、runs、内部评分等执行概念暴露成用户必须理解的流程。

## References

按需读取，不要因为存在 reference 就自动增加步骤：

- 需求理解与澄清：[`references/conversation.md`](references/conversation.md)
- 多轮检索、Coverage / Gap / Stop：[`references/retrieval.md`](references/retrieval.md)
- 来源生态与路由：[`references/source-routing.md`](references/source-routing.md)
- 候选事实检查：[`references/inspection.md`](references/inspection.md)
- 获取意图与下载结果：[`references/acquisition.md`](references/acquisition.md)
- 内容感知的离线 HTML 设计：[`references/html-design.md`](references/html-design.md)
- 归档分类：[`references/archive.md`](references/archive.md)
