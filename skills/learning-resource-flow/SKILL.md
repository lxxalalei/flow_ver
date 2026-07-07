---
name: learning-resource-flow
description: 儿童成长资料获取与归档的总调度入口。用于接收自然语言需求，创建并校验 request.json，处理 Intent 澄清循环，并按六阶段顺序调度需求理解、搜索计划、平台搜索、筛选选择、下载和归档。
---

# learning-resource-flow

## 职责

作为套件唯一总入口，维护会话状态并调度六个阶段。不要在本 Skill 中实现平台搜索、质量筛选、下载或归档逻辑。

本套件寻找适合孩子成长的资料：既包括学科与知识，也包括认知探索、情绪心理、生活习惯、安全教育、艺术创造、运动健康、社会认知和亲子陪伴。识别孩子想理解、探索、练习、实践、表达或改善的主题，根据用户表达组织需求，不预设学科范围、资源形态或学习路径。只保留会实际影响搜索与筛选的信息，省略没有证据或与当前需求无关的维度。

```text
用户需求
  -> stage 1 resource-intent
  -> stage 2 resource-search
  -> stage 3 resource-platforms（搜索模式）
  -> stage 4 resource-selector
  -> stage 5 resource-downloader
  -> stage 6 library-manager
```

搜索与下载严格分离：`resource-platforms` 只执行 Stage 3 搜索，Stage 5 的下载能力完全由 `resource-downloader` 负责。

## 会话目录

每个阶段文件的输出格式由写入该文件的 Skill 负责定义和校验。Flow 只创建 `request.json` 与 `manifest.json`、维护阶段状态，并按固定文件名调度；不要在这里重复定义下游业务字段。

为每个新需求创建：

```text
.learning-resource-work/sessions/{session_id}/
├── manifest.json
├── request.json
├── stage1_intent.json
├── stage2_search_plan.json
├── stage3_search_results.json
├── stage4_selection.json
├── stage5_download.json
├── stage6_archive.json
└── downloads/
```

`session_id` 使用 `{YYYYMMDD}-{HHmm}-{topic-slug}`。上下文中只保留 `session_id`、当前阶段和各阶段的最小 `_summary`；完整数据通过文件传递。

## 初始化 Stage 1 输入

执行 Flow 的模型必须先创建 `request.json`，再调用 Intent。不得把聊天消息直接作为未持久化参数传给 Intent。

按以下步骤初始化：

1. 原样复制当前用户需求到 `data.raw_request`，不得总结、纠错或补充模型理解。
2. 只把与当前需求直接有关的历史话语写入 `conversation_evidence`；每条必须包含 `role` 和原文 `content`。
3. 创建 `{session_dir}` 和初始 `manifest.json`，将所有阶段设为 `pending`。
4. 创建 `{session_dir}/request.json`：

```json
{
  "_meta": {
    "schema_version": "request/v1",
    "session_id": "20260630-1030-volcano-earthquake",
    "created_at": "ISO 8601"
  },
  "data": {
    "raw_request": "找适合孩子了解火山和地震的成长资料",
    "conversation_evidence": []
  }
}
```

5. 运行输入校验：

```bash
python3 learning-resource-flow/scripts/validate_request.py {session_dir}/request.json
```

6. 只有校验退出码为 0 时，才把 stage 1 设为 `in_progress` 并调用 `resource-intent`。校验失败时修复 `request.json` 一次；仍失败则在 manifest 中将 stage 1 标记为 `failed`，不得继续。

Stage 1 只能读取该快照，不依赖未持久化的聊天上下文。Flow 后续更新请求时保留 `raw_request` 原文，只追加澄清问题和用户回答；不要提前概括确认事实。

## manifest

创建会话时写入：

```json
{
  "schema_version": "session-manifest/v1",
  "session_id": "20260630-1030-volcano-earthquake",
  "updated_at": "ISO 8601",
  "status": "in_progress",
  "current_stage": 1,
  "stages": {
    "stage1": {"status": "pending"},
    "stage2": {"status": "pending"},
    "stage3": {"status": "pending"},
    "stage4": {"status": "pending"},
    "stage5": {"status": "pending"},
    "stage6": {"status": "pending"}
  }
}
```

阶段状态只使用 `pending`、`in_progress`、`waiting_user`、`completed`、`failed`、`cancelled`。`waiting_user` 表示阶段已产生明确问题，正在等待用户回答。调用前标记 `in_progress`；成功后标记 `completed`；失败时增加统一 `error` 对象。文件名和阶段写入者是固定规则，不在 manifest 重复保存。

## 六阶段调度

### Stage 1：理解需求

1. 确认 `{session_dir}/request.json` 已通过输入校验；否则停止。
2. 将 manifest 的 `current_stage` 设为 1，`stages.stage1.status` 设为 `in_progress`。
3. 调用 `resource-intent`，只传递绝对 `{session_dir}`；Intent 固定读取 `request.json`，输出 `stage1_intent.json`（`intent-spec/v1`）。
4. 确认输出文件存在，并运行 `resource-intent/scripts/validate_output.py`。输出缺失或校验失败时将 stage 1 标记为 `failed`，不得继续。
5. 读取 `_summary.status`；它必须与 `data.status` 一致。
6. `_summary.status=ready` 时，将 stage 1 标记为 `completed`，再进入 stage 2。
7. `_summary.status=needs_clarification` 时，从 `_summary.question` 取得问题并进入下面的澄清交接；不得调用 Search。

### Stage 1：澄清交接

1. 确认 `_summary.question` 是非空字符串，且与 `data.clarification.question` 一致；否则将 stage 1 标记为 `failed`，错误码使用 `INVALID_CLARIFICATION`。
2. 将该问题原文以 `{"role":"assistant","content":"..."}` 追加到 `request.json:data.conversation_evidence`，不得由 Flow 改写、扩展或追加第二个问题。
3. 重新校验 `request.json`，将 `stages.stage1.status` 设为 `waiting_user`，然后只向用户展示该问题并结束当前轮次。
4. 用户回答后，将回答原文以 `{"role":"user","content":"..."}` 追加到 `conversation_evidence`，不另行概括。
5. 保留最初的 `raw_request`，重新校验 `request.json`，把 stage 1 设回 `in_progress`，再次调用 Intent。
6. 不限制澄清轮数。只要 Intent 仍返回 `needs_clarification` 且用户愿意继续提供信息，就重复上述交接；只有 Intent 返回 `ready` 后才能进入 stage 2。
7. 用户明确取消时结束会话。用户明确表示无法提供必要信息、拒绝继续澄清，且 Intent 仍无法形成可搜索需求时，将 stage 1 标记为 `failed`，错误码使用 `CLARIFICATION_UNRESOLVED`；不要编造答案或绕过 Intent。

### Stage 2：生成搜索计划

- 调用 `resource-search`。
- 输入 `stage1_intent.json`，输出 `stage2_search_plan.json`。
- 本阶段只决定去哪里搜、搜什么、搜多少，不执行搜索。

### Stage 3：执行平台搜索

- 直接调用 `resource-platforms` 的搜索模式。
- 输入 `stage2_search_plan.json`，输出 `stage3_search_results.json`。
- `run_search_plan.py` 在原子写入前完成必要字段、计数和 `session_id` 自检；执行器返回失败时不得进入 Stage 4。
- 读取 `_summary.resource_count` 和 `data.errors` 判断继续、重试或调整计划。
- `resource_count>0` 时，将 stage 3 标记为 `completed` 并进入 Stage 4；部分平台失败不影响已有结果继续使用。
- `resource_count=0` 时不得调用 Selector。存在可重试错误时按错误建议重试 Stage 3，但不要在外部状态没有变化时重复同一失败调用；仍为零结果时将 stage 3 标记为 `waiting_user`。
- `data.errors` 出现 `AUTH_REQUIRED`、`AUTH_SESSION_EXPIRED` 或同类认证错误时，读取对应平台文档，说明缺少的具体登录信息并询问是否需要协助配置。用户授权后，由模型更新本地凭据约定，并在重试 Stage 3 时注入对应环境变量；不要为凭据变化重做 Intent 或搜索计划。
- 零结果且没有错误表示搜索成功但未召回内容；只有不可重试错误表示当前平台无法提供结果。两种情况都向用户提供调整关键词、扩大平台、修改条件或取消的选择。用户选择调整时从 Stage 2 重跑，选择重试时从 Stage 3 重跑。
- 只有执行器异常、输出缺失或校验失败时才将 stage 3 标记为 `failed`。
- 本阶段只执行平台任务、归一化字段和记录错误，不做跨平台筛选或最终质量评分。

### Stage 4：筛选并让用户选择

- 第一次调用 `resource-selector` 时只传递绝对 `{session_dir}`。Selector 读取 Stage 1 和 Stage 3，完成确定性预处理、公开证据核验、可选的多 Agent 并行审查和主 Agent 全局比较，再写入最终 `selector_review.json` 并返回候选展示；此时不得创建 `stage4_selection.json`。
- 将 stage 4 标记为 `waiting_user`，把 Selector 返回的候选和选择说明**原样展示**给用户，不得改写为 markdown 表格或其他格式，然后结束当前轮次。
- 用户回复后，把选择原话作为当前交互参数，连同同一 `{session_dir}` 交回 Selector。Selector 必须复用已有 review，不重新搜索或评分；只有明确选择或取消后才输出 `stage4_selection.json`。
- `finalize_selection.py` 会先校验 review，再自检 `_summary.status`、`_summary.selected_count` 和选择 ID；输出存在后将 stage 4 标记为 `completed` 或 `cancelled`。
- 没有合格候选时，提供放宽条件、换关键词或扩大平台范围的选项；不要进入下载阶段。
- `data.status=cancelled` 时，将会话标记为 `cancelled`。

### Stage 5：下载

- 调用 `resource-downloader`。
- 输入 `stage3_search_results.json` 和 `stage4_selection.json`，输出 `stage5_download.json`。
- 运行 `resource-downloader/scripts/validate_output.py {session_dir}`；校验失败时不得进入 Stage 6。
- 读取 `_summary` 中成功、降级和失败数量用于结果汇报。
- Downloader 使用自己维护的下载能力或通用方式，并负责重试和降级；不得调用 Platform 搜索层执行下载。

### Stage 6：归档

- 调用 `library-manager`。
- 输入 Stage 1、3、4、5 文件，输出 `stage6_archive.json`。
- 运行 `library-manager/scripts/validate_output.py {session_dir}`；只有校验通过才完成会话。
- 读取 `_summary` 中归档、跳过和失败数量用于最终汇报。
- 汇总成功、降级、失败和归档位置，将会话标记为 `completed`。

## 恢复与分支

收到消息后先判断：

| 类型 | 处理 |
|---|---|
| 新需求 | 创建新会话，从 stage 1 开始 |
| 修改需求事实或约束 | 更新 `request.json`，从 stage 1 重跑，并使后续阶段失效 |
| 仅调整搜索范围或平台策略 | 复用已验证 Intent，从 stage 2 重跑 |
| 重新查看现有候选 | 复用现有 `selector_review.json`，按 Selector 展示模板重新输出候选 |
| 扩大候选范围 | 调整搜索计划，从 stage 2 重跑 |
| 继续未完成下载 | 从 manifest 中首个未完成阶段恢复 |
| 查询已归档资源 | 直接调用 `library-manager` 检索模式，不创建搜索会话 |

区分恢复与重跑：恢复未完成工作时保留已有阶段文件；明确重跑时，先删除当前阶段及全部下游输出并把相应状态重置为 `pending`，避免读取旧结果。运行：

```bash
python3 learning-resource-flow/scripts/reset_from_stage.py {session_dir} {stage_number}
```

该脚本保留 `request.json`、manifest、已完成的上游输出和正式资料库内容。重跑 Stage 4 时同时删除 `selector_input.json`、`selector_worker_reviews/` 与 `selector_review.json`；重跑 Stage 5 或更早阶段时删除会话内 `downloads/`。脚本成功后再把目标阶段标记为 `in_progress` 并调用对应 Skill。

## 异常处理

- 用户取消：将当前阶段及会话标记为 `cancelled`。
- 阶段失败：记录错误；根据 `retryable` 决定重试，不静默跳过。
- 部分平台失败：stage 3 保留成功平台结果，并将失败调用写入 `data.errors`。
- 下载全部失败：保留来源链接及明确的降级结果，再询问是否更换资源。
- 不破解付费墙、不绕过访问控制、不下载用户未确认的资源。

## 参考资料

- `references/workflow-guide.md`：恢复、异常和用户交互规则。
- `references/output-templates.md`：候选展示、下载进度和最终结果模板。
- `scripts/reset_from_stage.py`：明确重跑前清理当前阶段及下游旧输出；恢复流程不要调用。
