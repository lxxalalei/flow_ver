# 统一任务上下文模型

- 状态：completed
- 创建日期：2026-07-30
- 完成日期：2026-07-30
- 范围：项目约束、active Skill、语义参考、回归案例和 MCP 下一版契约说明

## 目标

任务理解统一为 `user_role`、`resource_target`、目标和 `constraints`。用户角色与资源
对象相互独立，允许未知；搜索只由资源对象、目标和显式约束驱动。其余会影响结果的
用户明示条件统一进入普通约束。

## 步骤

- [x] completed：审计 active 文件中的任务上下文建模。
- [x] completed：更新项目约束、入口 Skill 和语义参考，统一任务模型与推导规则。
- [x] completed：更新语义回归案例和下一版 MCP 契约说明。
- [x] completed：运行静态校验、独立前向测试和真实 OpenClaw/GLM smoke。
- [x] completed：记录结果、风险并结清计划。

## 验证

- `skill-creator` 的 `quick_validate.py`。
- JSON 解析、Markdown 本地链接和 `git diff --check`。
- 独立 Agent 验证普通请求只依据资源对象、目标和显式约束设计搜索。
- 真实 `glm-req/glm-5.2` OpenClaw smoke。

## 结果

- 项目约束和 active Skill 现在直接使用 `user_role`、`resource_target`、目标和
  `constraints`，不再用旧分类的否定说明定义产品。未知字段保持未知，不为补齐模型追问。
- 搜索只由资源对象、目标和用户明示约束驱动。当前对话者身份只影响交互，不独立产生
  搜索方向，也不写入 MCP v1 的 `audience` 或 `learning_goal`。
- MCP v1 的 `learning_goal` 在资源对象已知时保留该信息，同时禁止虚构孩子的兴趣、动机、
  年级、资源形态或其他未表达事实。
- 回归案例覆盖直接搜索、家长为孩子找资源、明确给家长参考、显式收听约束、专注力资料、
  文件格式和无副作用搜索不二次确认。
- `quick_validate.py`、JSON 解析、Markdown 本地链接、`git diff --check` 和 active 语义残留
  检查全部通过。OpenClaw 配置有效，MCP doctor 返回 `education-resources: ok`。
- 独立 Agent 前向评审的四个案例都可直接搜索，资源对象和 v1 映射符合新模型。真实
  `glm-req/glm-5.2` 映射回合最终输出 `audience=null`，`learning_goal` 只描述给孩子使用的
  恐龙学习与科普资料，没有写入家长身份或虚构孩子兴趣。
- 真实自然请求直接建立 Flow 并搜索，实际查询没有增加无依据的家长内容。公开搜索源返回
  `Network is unreachable` 的部分失败和偏题候选，模型连续调整查询后在 120 秒超时，未形成
  最终候选回复；这是当前 generic 搜索质量与网络风险，不阻塞本次任务模型改造。
