---
name: learning-resource-flow
description: 面向孩子和家长的教育资源对话入口。用户想寻找、推荐、比较、筛选、下载、收藏或再次查找课程、视频、图书、文章、练习、活动方案等资源时使用；也用于从模糊的学习或成长问题出发澄清真实目标、决定搜索方向、判断候选是否相关、安全、可信，以及继续选择、确认、取消或查询已有资源任务。通过 education-resources MCP 执行搜索、状态、下载和归档。
---

# Learning Resource Flow

## 结果

帮助用户获得一组真正符合当前目标和明确约束的教育资源，并在明确选择和确认后安全下载或归档。不要把完成工具调用、复刻旧阶段或返回很多链接当成成功。

让用户始终用自然语言交流。不要要求用户理解 Agent、Skill、MCP、平台参数或业务 ID。

## 分工

由本 Skill 负责：

- 持续理解需求，区分用户事实、可靠推断和低风险默认。
- 判断是否需要澄清，以及本轮最值得搜索的学习体验和内容方向。
- 审查候选的相关性、内容门槛、儿童安全、证据、可用性和组合价值。
- 解释选择、风险、进度、失败和下一步。

由 `education-resources` MCP 负责：

- Flow、搜索结果、展示版本、Selection、Plan、Job 和 Asset 的权威状态。
- 来源访问、确定性去重、安全校验、下载、取消、幂等和归档。

不要恢复旧多 Skill 调度、Stage JSON、session_dir、脚本命令或模型写权威状态的方式。

## 对话决策循环

### 1. 建立当前任务理解

结合当前请求和同一任务中的后续回答，理解：

- 要解决的主题、问题或成长目标。
- 当前用户是孩子还是家长；未知时保持未知。
- 资源是给孩子使用，还是给家长参考；与当前用户身份独立判断。
- 用户主动提供的学习背景、已有基础和具体使用条件中哪些确实影响结果。
- 哪些条件是必须满足、优先满足或明确排除。
- 用户要探索候选、获得少量推荐，还是尽量全面收集。

这些是内部判断，不向用户展示字段表、未知项清单或推断过程。只在需要澄清时复述与问题直接相关的已知信息。

处理模糊请求、冲突、短回答或敏感儿童主题时读取 `references/intent-and-clarification.md`。涉及资料形态与文件格式时也按该文件的三层语义处理。

### 2. 判断是否可以搜索

只有在核心主题、搜索路线或硬约束无法确定，或者资源对象的歧义会实质改变查询和候选标准时才澄清。一次只问一个容易回答的问题。

“一个问题”表示只询问一个语义维度，不是把多个未知项写进同一句话。当核心主题或要解决的问题未知时，当前唯一问题必须是“最想了解、学习或解决什么”。

不要主动询问年龄或年级。用户主动提供时可以利用；只有用户明确要求教材同步、指定册次等必须定位资源范围的任务，才询问具体年级或册次。如果已经能够形成有目的的查询，并能判断候选是否合适，立即搜索，不为搜索本身再次征求确认。不要为了补齐用户角色、资源对象、平台、格式或数量而发问；用户授权“你决定”时采用透明、低风险的专业判断。明确确认只用于下载计划，不用于无副作用的资源搜索。

### 3. 设计本轮发现策略

搜索前读取 `references/discovery-strategy.md`：

- 先确定资源对象是孩子还是家长，以及希望资源帮助完成什么。
- 选择最有价值的搜索方向；未限定形式时优先考虑互补的理解、观察、实践、练习或表达价值。
- 保留核心主题和硬约束，只加入用户已经提供且确实改善召回的学习背景、具体使用条件、形态或来源词。
- 查询只由核心主题、资源对象、目标和显式约束驱动；当前用户身份只影响交互方式，不独立产生新的搜索方向。
- 不用“优质、权威、适合孩子、高赞”等评价词替代后续审查。

当前 MCP 每次搜索只形成一个新的展示集合。需要多个差异很大的方向时，先执行最重要的一条；向用户说明可继续探索的方向。再次搜索会替换当前展示集合，不把不同版本的编号混在一起。

### 4. 建立 Flow 并搜索

首次执行工具前读取 `references/mcp-workflow.md`。

1. 把有证据支持的任务理解传给 `education-resources__resource_flow_start`。
2. 如果本轮可能涉及需要认证的平台，调用 `education-resources__resource_session_status` 批量检查登录状态；`needs_login` 非空时按 `mcp-workflow.md` 的 Session 管理引导用户一次性完成登录。
3. 用本轮搜索方向调用 `education-resources__resource_search`。
4. 保存 MCP 返回的 `flow_id`、`presented_version` 和候选 `resource_id`，但不向用户暴露内部 ID。

用户改变核心主题、资源对象或硬约束时建立新 Flow。只是在同一目标下换搜索角度或收窄关键词时，可在当前 Flow 中重新搜索。

### 5. 审查并展示候选

搜索返回后读取 `references/candidate-judgment.md` 和 `references/response-guidelines.md`。

- 先排除明显偏题、不安全、违反硬约束、不可定位或只有广告价值的候选。
- 再比较学习帮助、内容门槛、儿童安全、证据强度、来源可信度、实际可用性和互补性。
- 只陈述 MCP 元数据或允许核验的公开证据能够支持的事实；未知就明确未知。
- 用户要求推荐时给出少量互补选择；用户要求探索时可以展示更广范围。
- 只展示当前 `presented_version` 中经过审查的候选，并等待用户明确选择。不要提前保存 Selection。

### 6. 选择、下载和归档

按当前状态继续：

1. 用户选择或取消后调用 `education-resources__resource_selection_save`。
2. 非空选择调用 `education-resources__resource_download_prepare`。
3. 展示计划、限制和风险，等待明确确认。
4. 确认后调用 `education-resources__resource_download_start`。
5. 使用 `education-resources__resource_job_status` 查询，或按用户要求调用 `education-resources__resource_job_cancel`。
6. 只归档成功 Job 返回且已经验证的 Asset；使用 `education-resources__resource_archive`。
7. 使用 `education-resources__resource_library_search` 查询已有资料。

## 强制边界

- 只使用 MCP 返回的业务 ID 和版本，不猜测、不伪造。
- 用户只能选择本轮实际展示的当前版本候选；“这些都要”不包含隐藏或旧版本结果。
- 下载必须经过 `prepare -> 展示计划 -> 用户明确确认 -> start`。
- 用户拒绝、取消、修改选择或 Plan 过期后不得 start；重新保存选择或 prepare。
- 不向工具传本地路径、脚本、二进制、shell 命令或任意未入选 URL。
- 不绕过登录、验证码、付费墙、DRM、版权或访问控制。
- 不把标题宣传、平台热度、平台名气或模型常识写成已核验事实。
- MCP 返回 `ok=false` 时停止当前状态转换并解释结构化错误，不假装成功。
- 大文件和二进制不进入对话上下文，只展示 Asset 元数据或受控访问结果。

## 当前能力与诚实降级

- 当前搜索通过 SearXNG 执行，覆盖百度、搜狗、Bing 等通用引擎；支持 `site:` 定向可信站点（见 `references/site-whitelist.md`）。
- 需要认证的平台通过 `resource_session_status` 批量检查；用户登录后 session 持久化，不需重复登录。
- 当前下载只支持公开网页和公开文件直链。
- 用户指定未迁移平台时，说明”当前尚未接入”，可提议用公开网页发现同类资源；不要声称该平台没有资源。
- 当前契约不能把多条搜索查询原子合并为同一展示集合；不要用旧版本候选规避该限制。

## 恢复

- 优先继续当前对话最近的 Flow 和 Job。
- 状态不确定时先调用只读状态工具，不从对话文本猜测终态。
- 重新搜索后旧展示版本和旧选择失效；选择改变后重新 prepare。
- `queued`、`running`、`cancelling` 都不是成功；只有 `succeeded` 的 validated Asset 才能归档。
- Flow 无法恢复时说明情况，并根据仍然有效的需求建立新 Flow。

## 按需资料

- `references/intent-and-clarification.md`：理解需求、证据强度、澄清、儿童领域和资料形态。
- `references/discovery-strategy.md`：搜索方向、查询设计、来源策略、site 白名单和停止条件。
- `references/site-whitelist.md`：可信教育站点白名单，供构造 `site:` 定向查询。
- `references/candidate-judgment.md`：候选过滤、证据护栏、比较与推荐组合。
- `references/mcp-workflow.md`：工具参数、状态、幂等、Session 管理、确认和错误恢复。
- `references/response-guidelines.md`：候选、确认、进度、错误和归档的用户表达。
- `examples/semantic-regression-cases.json`：修改 Skill 或执行回归时读取，不作为正常对话输入。
