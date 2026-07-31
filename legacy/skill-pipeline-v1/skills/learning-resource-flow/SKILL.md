---
name: learning-resource-flow
description: 儿童成长与学习资料发现、筛选、获取和归档的唯一用户入口。当用户要求为孩子寻找、搜索、推荐、筛选、下载、收藏或继续处理课程、视频、图书、文章、练习和活动资料时使用。默认通过 education-resources MCP 维护 Flow、候选、选择、下载任务和归档状态；旧六阶段 Skill/脚本流程仅作为迁移期显式回滚后端。
---

# learning-resource-flow

## 职责

作为套件总入口，维护一次资料需求的阶段边界、用户确认点和恢复上下文。模型负责需求理解、候选解释和用户交互；`education-resources` MCP 服务负责权威状态、搜索执行、Selection 校验、下载任务和归档事务。

本套件覆盖学科学习，也覆盖认知探索、情绪心理、生活习惯、安全教育、艺术创造、运动健康、社会认知和亲子陪伴等儿童成长主题。以用户表达为准，不预设学科、资源形态或学习路径。

```text
用户需求
  -> 需求澄清
  -> resource_flow_start
  -> resource_search
  -> 候选解释与用户明确选择
  -> resource_selection_save
  -> resource_download_prepare
  -> 用户确认下载风险和范围
  -> resource_download_start
  -> resource_job_status / resource_job_cancel
  -> resource_archive
```

## 核心契约

- Stage 1 把当前对话作为主要工作上下文。用户回答澄清问题时，继续同一份需求理解。
- 默认使用 MCP 服务返回的 `flow_id`、`resource_id`、`plan_id`、`job_id` 和 `asset_id`；不得自行生成或修改这些 ID。
- 每个有副作用的工具调用使用新的稳定 `idempotency_key`；重试同一请求时复用原键，改变参数时必须换键。
- 用户只能选择 `resource_search` 本轮 `presented_version` 返回的资源，不能把任意 URL 或未展示资源直接交给下载。
- 下载必须执行 `prepare -> 展示计划 -> 用户明确确认 -> start`。未确认、取消或确认令牌失效时不得调用 `resource_download_start`。
- 模型不得传递本地路径、脚本路径、解释器、二进制或 shell 命令；归档只使用 MCP 返回的 `asset_id`。
- MCP 失败时报告结构化错误并按 `retriable` 决定下一步，不得静默回退为直接执行下载脚本。

## 默认 MCP 调度

首次进入或恢复时按需读取 `references/openclaw-mcp-tools.md`，严格使用其中的工具顺序和状态转换：

1. 在需求已经足以搜索后调用 `resource_flow_start`，保存返回的 `flow_id`。
2. 调用 `resource_search`；解释相关性、适龄性、来源和失败项，展示本轮 `presented_version` 与候选。
3. 等待用户明确选择或取消，再调用 `resource_selection_save`。首次展示候选时不得提前保存选择。
4. 有选择时调用 `resource_download_prepare`，向用户展示资源、容器、大小上限、风险和过期时间。
5. 用户明确确认后调用 `resource_download_start`；立即返回 `job_id`，不要在一次工具调用中等待下载完成。
6. 使用 `resource_job_status` 查询进度；用户取消时调用 `resource_job_cancel`。
7. 只有 Job 为 `succeeded` 且返回 validated Asset 时，才按 `asset_id` 调用 `resource_archive`。
8. 查询已有资料时调用 `resource_library_search`，不读取或修改本地索引文件；若当前没有有效 `flow_id`，先以查询主题建立一个 Flow，再执行检索。

默认协议版本为 `contract_version=1.0.0`。工具结果 `ok=false` 时不得继续假定阶段成功。

## 旧后端兼容边界

以下“会话与状态”“六阶段调度”仅在环境明确设置 `execution_backend=legacy`、MCP 尚未启用或执行迁移对等测试时使用。默认 MCP 模式不得同时写旧 Stage 文件或调用旧平台/下载脚本，以免产生双重权威状态。

## 会话与状态（legacy）

新需求使用 `.learning-resource-work/sessions/{session_id}/`，其中 `session_id` 为 `{YYYYMMDD}-{HHmm}-{topic-slug}`。

初始化时：

1. 使用 `scripts/session_state.py create {session_dir}` 创建 manifest。
2. 将用户最初请求原样写入 `request.json:data.raw_request`，只收录与本次需求有关的历史原话：

```json
{"_meta":{"schema_version":"request/v1","session_id":"...","created_at":"..."},"data":{"raw_request":"用户原话","conversation_evidence":[]}}
```

3. 使用 `scripts/validate_request.py` 校验快照，然后开始 Stage 1。

所有 manifest 状态变化都通过 `scripts/session_state.py` 完成，不直接编辑文件。在 Stage 1 进入等待，或基于最新回答生成正式输出前，运行 `scripts/checkpoint_intent.py {session_dir} [--user-answer "..."] [--assistant-question "..."]`，单向保存尚未持久化的用户回答和当前问题；模型不需要读回检查点才能继续理解。

恢复任务时先 `inspect`，校验已经完成的正式输出，再从首个未完成阶段继续。只有中断恢复或上下文不足时才使用持久化快照重建 Intent。

## 六阶段调度（legacy）

### Stage 1：理解需求

- 使用 `resource-intent` 持续分析当前对话中的资料需求。
- Intent 需要澄清时，向用户展示它形成的一个自然语言问题并等待；不生成正式 `stage1_intent.json`，也不进入 Search。
- 用户回答后继续已有理解，直到 Intent 判断需求足以支持搜索，或用户取消、拒绝提供真正必要的信息。
- Intent ready 后生成并校验一次正式 `stage1_intent.json`；校验通过后完成 Stage 1。

### Stage 2：生成搜索计划

- 调用 `resource-search`。
- 输入 `stage1_intent.json`，输出 `stage2_search_plan.json`。
- 本阶段只决定搜索方向、平台和预算，不执行搜索。

### Stage 3：执行平台搜索

- 调用 `resource-platforms` 的搜索模式。
- 输入 `stage2_search_plan.json`，输出 `stage3_search_results.json`。
- 只为计划实际使用的平台和引擎预检凭据；进入本阶段时按需读取 `references/workflow-guide.md` 的 Stage 3 凭据规则。
- 有有效结果且认证问题已经处理时进入 Stage 4；零结果、缺失凭据或认证失效时按指南暂停、重试或调整计划。
- 本阶段不做跨平台质量筛选。

### Stage 4：筛选并确认

- 调用 `resource-selector`，传递同一 `{session_dir}`。
- Selector 读取 Stage 1 和 Stage 3，审查候选并返回展示内容；Flow 原样展示并等待用户选择。
- 用户回复后把选择原话交回 Selector，复用已有审查结果，不重新搜索或评分。
- 只有用户明确选择或取消后才生成 `stage4_selection.json`。

### Stage 5：下载

- 调用 `resource-downloader`。
- 输入 `stage3_search_results.json` 和 `stage4_selection.json`，输出 `stage5_download.json`。
- 校验通过后进入 Stage 6；成功、降级和失败结果按 Downloader 输出汇报。

### Stage 6：归档

- 调用 `library-manager`。
- 输入 Stage 1、3、4、5 的正式文件，输出 `stage6_archive.json`。
- 校验通过后完成会话，并汇报归档、跳过、失败数量和归档位置。

## 继续、调整与重跑

默认 MCP 模式优先复用 `flow_id`：重新搜索会生成新的 `presented_version`，旧选择随即失效；Selection 变化后必须重新 prepare；Job 和 Asset 状态由服务端恢复。下表只用于 legacy 后端。

| 用户意图 | 起点 |
|---|---|
| 新资料需求 | 新会话，Stage 1 |
| 修改需求事实或约束 | 更新恢复快照，从 Stage 1 重跑 |
| 只调整搜索范围、平台或关键词 | 复用 Intent，从 Stage 2 重跑 |
| 重新查看已有候选 | 复用 Selector review |
| 扩大候选范围 | 从 Stage 2 重跑 |
| 继续未完成流程 | 从 manifest 首个未完成阶段恢复 |
| 查询已归档资料 | MCP 模式先复用或建立查询 Flow；legacy 模式直接使用 Library Manager 检索 |

恢复保留现有进度；明确重跑时使用 `scripts/reset_from_stage.py` 清理目标阶段及下游旧产物。详细分支规则仅在发生恢复、零结果、凭据问题或下载降级时读取 `references/workflow-guide.md`。

## 异常与安全

- 用户取消时取消当前会话，不继续调用下游 Skill。
- 阶段失败时记录真实错误，并依据 `retryable` 决定是否重试。
- 部分平台失败时保留成功结果，不把失败描述成“平台没有资源”。
- 不破解付费墙、不绕过访问控制、不下载用户未确认的资源。
- stdio MCP 是进程边界而不是安全沙箱；不得因为工具来自 MCP 就放宽来源、大小、路径或访问权判断。

## 按需资源

- `references/openclaw-mcp-tools.md`：默认 MCP 工具顺序、参数、确认、恢复和错误处理；首次执行或状态不确定时读取。
- `references/pipeline-data-contract.md`：生成阶段交接文件、恢复旧会话或排查接口时读取；正常 Stage 1 澄清不读取。
- `references/workflow-guide.md`：发生中断恢复、凭据问题、零结果、候选不足或下载降级时读取相关章节；正常 Stage 1 澄清不读取。
- `references/output-templates.md`：需要向用户展示凭据提醒、候选、下载进度或最终结果时读取对应模板。
- `examples/flow-routing-cases.json`：修改 Flow 或执行回归验收时读取，不用于正常请求。
- `scripts/session_state.py`：状态操作的唯一入口。
- `scripts/checkpoint_intent.py`：保存 Stage 1 等待边界的恢复证据，不参与语义判断。
- `scripts/reset_from_stage.py`：明确重跑时清理目标阶段和下游产物。
