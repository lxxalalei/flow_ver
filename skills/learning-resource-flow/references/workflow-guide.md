# Flow 交互与恢复指南

## 用户确认点

只在以下位置等待用户：

1. Stage 1 的关键需求存在歧义，且不同答案会显著改变搜索结果。
2. Stage 4 展示候选后，等待用户确认下载项。
3. 无候选、全部下载失败或需要扩大权限范围时。

Stage 2 和 stage 3 正常情况下连续执行，不要求额外确认。

## Stage 1 澄清循环

Intent 返回 `needs_clarification` 时：

1. 从 Intent `_summary.question` 读取问题，并核对它与 `data.clarification.question` 一致；不要由 Flow 重新组织一组问题。
2. 先把问题作为 assistant evidence 写入 `request.json`，再把 stage 1 标记为 `waiting_user` 并向用户展示。
3. 下一轮收到回答后，把回答原文作为 user evidence 追加到 `request.json`。
4. 不另行概括确认事实，避免 Flow 提前完成 Intent 的语义归纳。
5. 每次写入后运行 `python3 learning-resource-flow/scripts/validate_request.py {session_dir}/request.json`。
6. 重跑 stage 1；不要直接修改 `stage1_intent.json`。
7. 不设置固定轮数上限。Intent 返回 `needs_clarification` 时继续交接，直到返回 `ready`、用户取消，或用户明确拒绝继续提供且缺失信息无法安全省略。
8. 用户无法提供某项信息但授权继续时，重新运行 Intent，由 Intent 判断能否省略该维度或采用透明的低风险默认；Flow 不替 Intent 作出语义决定。

等待回答期间，manifest 至少记录：

```json
{
  "current_stage": 1,
  "stages": {
    "stage1": {
      "status": "waiting_user"
    }
  }
}
```

恢复会话时，如果 stage 1 为 `waiting_user`，先把当前用户消息视为该问题的回答；除非用户明确取消或提出了一个应创建新会话的新需求。

## 候选不足

Stage 4 的合格候选少于 5 条时，说明主要过滤原因，并提供：

- 调整关键词或主题范围：回到 stage 2。
- 增加平台或改为穷尽模式：回到 stage 2。
- 修改费用、语言、类型、质量偏好等用户约束：更新 `request.json`，从 stage 1 重跑。
- 接受现有候选：继续在 stage 4 选择。

不要由 flow 自行改写用户约束。

## 部分平台失败

Stage 3 只要存在成功结果即可进入 stage 4。向用户展示候选时附带失败平台及原因，但不要把平台失败描述为“该平台没有资源”。

认证错误统一交由 Flow 的 Stage 3 凭据规则处理；用户已明确跳过的平台不重复提醒。

## 搜索零结果

Stage 3 的 `_summary.resource_count=0` 时停止在当前阶段，不调用 Selector：

1. 存在可重试错误时，根据错误建议重试；外部状态没有变化时不要循环执行同一失败调用。
2. 没有错误表示搜索成功但未召回内容；只有不可重试错误表示当前平台无法提供结果。这两种情况都不是输出校验失败。
3. 将 stage 3 标记为 `waiting_user`，提供调整关键词、扩大平台、修改条件或取消。
4. 用户调整搜索方案时从 Stage 2 重跑；用户要求原计划重试时从 Stage 3 重跑。
5. 只有执行器异常、输出缺失或校验失败时将 stage 3 标记为 `failed`。

## 下载降级

Stage 5 使用：

- Level 0：完整原资源。
- Level 1：官方或平台提供的预览/替代格式。
- Level 2：可用正文、字幕、音频或核心内容。
- Level 3：元数据、摘要和来源链接。

降级结果必须明确标注，不得伪装成完整下载。

## 恢复

读取 manifest 后，从第一个非 `completed` 阶段继续。恢复前确认其输入文件存在且上游阶段已完成。遇到 `waiting_user` 时不得自动重跑，必须先取得并持久化用户回答。

恢复阶段时保留现有文件和进度。明确重跑阶段时：

1. 运行 `python3 learning-resource-flow/scripts/reset_from_stage.py {session_dir} {stage_number}`。
2. 确认当前阶段及下游旧输出已删除，对应状态已重置为 `pending`。
3. 将目标阶段标记为 `in_progress` 并调用对应 Skill。
4. 成功后标记 `completed`；业务结果只保存在阶段文件。

重置脚本不删除 `request.json`、manifest、已完成的上游输出或正式资料库内容。重跑 Stage 4 会清理 Selector 输入、并行 worker 私有结果和最终 review；重跑 Stage 5 或更早阶段会清理会话内下载目录。

## 用户取消

写入：

```json
{
  "status": "cancelled",
  "cancelled_at": "ISO 8601",
  "cancelled_stage": 4
}
```

保留已生成的阶段文件，以便用户明确要求恢复时继续。
