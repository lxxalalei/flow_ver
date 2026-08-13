# Multi-Agent Search Planning — Experimental

本文件描述一个**可选实验能力**：在极少数复杂搜索中，让 OpenClaw leaf sub-agent 帮 Main Agent 规划互补搜索方向。

它不是普通搜索默认路径，也不改变 `education-resources` MCP 的 Tool、Flow、ResultSet、Selection 或获取状态模型。当前基线始终是：**一个强 Main Agent + 语义 Skill + MCP**。

## 1. 为什么默认不用

多 Agent 会增加上下文、调度和合并成本。如果 Main Agent 自己能在一次思考中形成 1–3 个清楚、互补的搜索角度，直接搜索通常更简单、更稳定。

只有并行规划本身能提高**语义搜索质量**时才考虑 child；不要因为 OpenClaw 支持 sub-agent、平台很多或想“显得全面”而使用。

### 适合考虑

- 用户明确要求系统性、较全面的横向研究；
- 请求同时包含几个真正独立的学习价值，例如“理解原理 + 看真实过程 + 找实践材料”；
- 一个复杂主题需要明显不同的证据路线，例如专业原始资料与视觉材料；
- 首轮结果已经暴露两个彼此独立、且都需要较复杂规划的缺口。

### 不适合

- 一个方向就够的窄任务；
- Main Agent 很容易自己形成 1–3 个高质量角度；
- 只是想多搜平台；
- 只是改写近义 query；
- 当前真正问题是需要用户澄清；
- 当前只剩 Inspect、认证、版本确认、下载或归档事实问题。

如果拿不准是否值得 spawn，默认不 spawn。

## 2. 所有权边界

多 Agent 只辅助**搜索规划**。

```text
用户目标
  -> Main Agent 判断是否需要实验性并行规划
  -> optional leaf child：各自提出一个语义方向/来源职责/query
  -> Main Agent 审查、去重、裁剪
  -> Main Agent 调用 education-resources resource_search
  -> Main Agent 阅读真实 ResultSet 并继续判断
```

所有权保持：

- **Main Agent**：理解用户目标、最终搜索角度、来源选择、query、候选判断、是否继续搜索、Presentation 和用户交互；
- **leaf child**：只返回临时搜索规划建议；
- **MCP**：Flow、ResultSet、Presentation、Selection、Resolution/Representation、Plan、Job、Outcome、Asset、Archive 和真实工具事实。

Child 输出不是业务状态、用户事实或搜索证据。不得把 child 的自然语言建议写成 `resource_id`、ResultSet、availability、Provider、下载状态等事实。

## 3. 第一版预算

一次最多同时 spawn **2 个 leaf sub-agent**。

- 不允许 child 再 spawn child；
- 不按平台创建固定角色，例如 Bilibili Agent / Zhihu Agent / Generic Agent；
- 一个 child 通常负责一个真正独立的语义角度；
- 很简单的方向由 Main Agent 自己做，不为了凑两个 child 强拆任务。

多 Agent 不能成为扩大搜索轮数、ResultSet 容量或平台数量的理由。

## 4. 给 child 的上下文

优先使用 isolated child，并显式传递完成这一方向真正需要的最小上下文：

- 当前用户真正目标；
- 当前 `resource_target`；
- 与该对象明确相关、确实影响搜索的可靠上层背景；
- 用户明确 must / prefer / exclude；
- child 负责的唯一搜索角度或当前缺口；
- 已经覆盖的内容，避免重复；
- 明确边界：只给搜索规划建议，不执行资源工具。

不要把整个 `USER.md`、`MEMORY.md`、家庭画像或完整 transcript 复制给 child。

### 示例任务

```text
你只辅助规划当前学习资源任务的一个搜索方向，不执行任何资源 Tool。

目标：让小学阶段孩子系统了解火山。
对象：孩子自己使用。
显式约束：中文优先；用户没有指定平台或载体。
你负责：过程观察方向。
已经覆盖：火山形成与喷发原理。

请建议：
- 这个方向具体要帮助用户获得什么；
- 最适合的主力来源生态及理由；
- 如果确有互补价值，可补 1 个来源；
- 每个来源最多 1 条自然、聚焦的 query；
- 你当前最重要的不确定性。

不要调用 resource_*、web/browser/exec；不要生成 resource_id、ResultSet、可下载性或其他业务事实。
```

这只是沟通模板，不是新 Schema。

## 5. Main Agent 必须重新判断 child 输出

Child 完成后不能直接拼接输出。Main Agent 至少重新检查：

1. 是否真正对应当前用户目标；
2. 是否违反 must/exclude；
3. 两个建议是否真的互补，还是同义/平台重复；
4. 来源是否有独特贡献；
5. query 是否自然、聚焦，是否虚构了年龄、版本、偏好；
6. 是否值得占用当前搜索预算。

重复方向合并；偏题或较弱建议直接丢弃。Child 的探索假设不会自动变成用户 preference/constraint。

最终 `search_tasks[]` 仍由 Main Agent 形成并提交。

## 6. Child 不操作资源 Flow

禁止 leaf child 调用：

- `resource_flow_start`；
- `resource_search` / `resource_browse_creator`；
- `resource_inspect`；
- Presentation / Selection；
- download / archive。

也不要：

- 为每个 child 新建 Branch Flow；
- 让多个 child 并发 Extend 同一 Flow；
- 新增跨 Flow ResultSet merge；
- 把 child session 变成第二套资源状态系统。

MCP mutation 始终由 Main Agent 根据当前服务端事实有序提交。

这个边界的目的不是增加形式化流程，而是避免两个语义规划者同时修改同一个权威资源状态。

## 7. 等待和失败

如果当前 OpenClaw 提供 `sessions_yield`，spawn 完本轮所需 children 后优先让完成事件自然返回；不要用 `sessions_list` / `sessions_history` 建轮询循环。

Child 超时、失败或建议质量低时：

- Main Agent 直接使用自己已有的理解继续；
- 不把规划失败解释成“没有资源”；
- 不因此改走 web/browser/exec 或第二个资源后端；
- 不建立 fallback Agent 链。

Multi-agent 不可用不应阻塞普通资源搜索。

## 8. 首轮之后的再次委派

首轮真实结果出来以后，先由 Main Agent 判断**具体还缺什么**。

只有缺口本身仍然复杂、且让一个 child 专门规划有明显收益时，最多再使用 **1 个 child**。

例如：

```text
已有：原理解释 + 过程视频
缺少：真正适合低年级、可打印的火山观察/实验活动单
```

可以让一个 child 只规划“可打印活动材料”的来源与 query。

不要重新把已经满足的原理和视频方向再 spawn 一遍。如果缺口很简单，Main Agent 直接补搜。

## 9. 用户背景边界

Main Agent 只把 child 完成任务确实需要的可靠背景传进去。

多孩子场景由 Main Agent 先确认本次对象；child 不从家庭记忆猜 target，也不负责更新长期记忆。

Child 提出的资源形态、学习方式和来源都是临时探索建议，不能自动沉淀成用户长期偏好。

## 10. 如何判断这个实验能力值不值得保留

不要因为实现已经存在就默认它有效。应使用同一模型、同一 MCP、同一用户输入做 A/B：

```text
A：Main Agent 单独规划
B：Main Agent + 最多 2 个 planning child
```

至少比较：

- 需求理解是否更准确；
- 搜索角度是否更互补；
- 平台派发是否更合理；
- query 是否更自然；
- 是否减少无效搜索；
- 最终候选质量是否提高；
- 额外时间和上下文成本是否值得。

如果没有稳定增益，就保持普通路径单 Agent，不为了架构完整把 multi-agent 放回主 Skill。

## 11. 部署边界

只有 live OpenClaw session 实际提供 `sessions_spawn` 时才能使用；希望同一 turn 等结果时还需要相应等待能力。具体 Tool 名称和配置以当前 OpenClaw runtime 为准，不由本 Skill 猜测或写入用户配置。

如果部署能给 leaf child 收窄 tool policy，child 只需要语义规划能力，不需要 `education-resources` MCP、session-manager、web/browser/exec 或其他资源副作用工具。

当前推荐实验边界：

- `maxSpawnDepth=1`；
- 同一轮最多 2 个 planning child；
- child 不拥有资源数据面；
- Main Agent 始终负责最后决策。
