# Flow 交互与恢复指南

## 用户确认点

只在以下位置等待用户：

1. Stage 1 的关键需求存在歧义，且不同答案会显著改变搜索结果。
2. Stage 4 展示候选后，等待用户确认下载项。
3. 搜索计划实际选中了缺少凭据的平台或引擎、无候选、全部下载失败或需要扩大权限范围时。

Stage 2 和 stage 3 正常情况下连续执行，不要求额外确认。

## Stage 1 等待与恢复检查点

Intent 决定当前问题，Flow 原样展示。进入等待前只做一次恢复性持久化：

```bash
# 第一个问题
python3 learning-resource-flow/scripts/checkpoint_intent.py {session_dir} --assistant-question "..."

# 用户回答后仍需继续澄清
python3 learning-resource-flow/scripts/checkpoint_intent.py {session_dir} --user-answer "..." --assistant-question "..."

# 用户回答后已经 ready
python3 learning-resource-flow/scripts/checkpoint_intent.py {session_dir} --user-answer "..."
```

检查点只保存尚未持久化的用户原话和问题语境。模型先理解、再保存，不从检查点读回同一轮消息重新判断。

等待期间保持 `session.status=waiting_user`、`stages.stage1.status=in_progress`。恢复时使用 `request.json` 和已保存证据重建需求理解；正常对话直接使用当前上下文。

## 候选不足

Stage 4 的合格候选少于 5 条时，说明主要过滤原因，并提供：

- 调整关键词或主题范围：回到 stage 2。
- 增加平台或改为穷尽模式：回到 stage 2。
- 修改费用、语言、类型、质量偏好等用户约束：此时 Stage 1 已完成，更新恢复快照并明确从 stage 1 重新开始；这与澄清期间继续活跃 Intent 不同。
- 接受现有候选：继续在 stage 4 选择。

不要由 flow 自行改写用户约束。

## Stage 3 凭据预检

只在搜索计划实际涉及需要认证的平台或引擎时读取本节：

1. 从 `stage2_search_plan.json` 取得实际平台和引擎，再读取 `resource-platforms/config/search-registry.json`；不检查无关来源。
2. 对 `auth=required` 的来源读取对应平台 reference，确认可接受的环境变量或 Cookie/Token 文件。`generic` 还要检查实际选中的 `engine_credentials`；当前 `qianfan` 使用 `QIANFAN_API_KEY`。
3. 检查执行环境和 `.learning-resource-flow/credentials.json` 指向的本地私有文件。只有非空环境变量或存在且非空的文件才算已配置；不得在消息、计划、manifest 或日志中回显凭据值。
4. 缺少必需凭据时先暂停 Stage 3，按输出模板说明缺少的来源和凭据类型，让用户选择协助配置或跳过；不要先调用对应来源试错。
5. 用户同意配置时，由模型把用户提供的凭据写入受支持的本地私有文件并更新凭据索引，不要求用户自行编辑文件。用户选择跳过时继续其他来源，同一轮不重复提醒。
6. 执行后出现 `AUTH_REQUIRED`、`AUTH_SESSION_EXPIRED` 或同类服务端认证错误时，使用相同交互处理。凭据变化不重做 Intent 或搜索计划。

## 部分平台失败

Stage 3 只要存在成功结果即可进入 stage 4。向用户展示候选时附带失败平台及原因，但不要把平台失败描述为“该平台没有资源”。

认证错误统一交由 Flow 的 Stage 3 凭据规则处理；用户已明确跳过的平台或引擎不重复提醒。

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

读取 manifest 后，从第一个非 `completed` 阶段继续。恢复前确认已完成阶段的正式输出存在且有效。当前阶段是 1、会话处于 `waiting_user` 且 Stage 1 仍为 `in_progress` 时，先取得用户回答，再使用持久化快照重建活跃 Intent 上下文；不要求在恢复前把本轮回答先转换成正式阶段文件，也不得自动生成 `stage1_intent.json`。

恢复阶段时保留现有文件和进度。明确重跑阶段时：

1. 运行 `python3 learning-resource-flow/scripts/reset_from_stage.py {session_dir} {stage_number}`。
2. 确认当前阶段及下游旧输出已删除，对应状态已重置为 `pending`。
3. 将目标阶段标记为 `in_progress` 并调用对应 Skill。
4. 成功后标记 `completed`；业务结果只保存在阶段文件。

重置脚本不删除 `request.json`、manifest、已完成的上游输出或正式资料库内容。重跑 Stage 4 会清理 Selector 输入、并行 worker 私有结果和最终 review；重跑 Stage 5 或更早阶段会清理会话内下载目录。

## 用户取消

使用 `session_state.py cancel {session_dir} {stage}` 更新会话，不直接编辑 manifest。保留已生成的阶段文件，以便用户明确要求恢复时继续。
