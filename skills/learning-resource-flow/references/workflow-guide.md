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
7. 最多两轮。达到上限后仍无法确定核心主题或消除硬约束冲突，将 stage 1 标记为 `failed` 并结束本次规划。

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
- 放宽费用、语言或质量条件：复用 stage 3，重跑 stage 4。
- 接受现有候选：继续在 stage 4 选择。

不要由 flow 自行改写用户约束。

## 部分平台失败

Stage 3 只要存在成功结果即可进入 stage 4。向用户展示候选时附带失败平台及原因，但不要把平台失败描述为“该平台没有资源”。

## 下载降级

Stage 5 使用：

- Level 0：完整原资源。
- Level 1：官方或平台提供的预览/替代格式。
- Level 2：可用正文、字幕、音频或核心内容。
- Level 3：元数据、摘要和来源链接。

降级结果必须明确标注，不得伪装成完整下载。

## 恢复

读取 manifest 后，从第一个非 `completed` 阶段继续。恢复前确认其输入文件存在且上游阶段已完成。遇到 `waiting_user` 时不得自动重跑，必须先取得并持久化用户回答。

重跑阶段时：

1. 将该阶段标记为 `in_progress`。
2. 将所有下游阶段重置为 `pending`。
3. 新输出使用原文件名覆盖前先保留必要错误记录。
4. 成功后标记 `completed`；业务结果只保存在阶段文件。

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
