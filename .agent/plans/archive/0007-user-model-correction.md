# 用户模型与年龄策略纠正

- 状态：completed
- 创建日期：2026-07-30
- 完成日期：2026-07-30
- 范围：项目约束、active Skill、语义回归案例、MCP 下一版契约说明

## 目标

纠正从 legacy 和 MCP v1 枚举带入的错误产品模型：系统用户只有孩子和家长；资源可以
给孩子使用或给家长参考；亲子共同使用只是场景，不是第三类用户；教师不属于产品用户。
年龄和年级不是默认收集项，模型不得为了“适龄”主动询问。用户主动给出时可以用于搜索；
只有用户明确要求教材同步等必须定位学段的任务，才澄清资源范围，而不是收集年龄画像。

## 步骤

- [x] completed：定位教师、亲子用户类型和年龄优先规则的来源。
- [x] completed：更新持久项目约束和 active Skill 用户模型。
- [x] completed：重写澄清、搜索、候选和 MCP 映射中的年龄策略。
- [x] completed：更新语义回归案例并从 active MCP v1 枚举删除 `teacher`。
- [x] completed：运行 Skill、MCP、独立前向测试和真实 GLM smoke。

## 来源结论

- legacy Intent/Search 将孩子直接使用、家长辅助、亲子共同和教师组织混作并列受众。
- MCP v1 `audience` 枚举仍包含 `teacher`，并把学段、家长和教师混在同一字段。
- active Skill 重建时错误吸收了以上分类，并过度强调旧 Selector 的适龄判断与敏感主题年龄澄清。

## 验证

- `skill-creator` 的 `quick_validate.py`。
- JSON、Markdown 链接和 `git diff --check`。
- 独立 Agent 验证模糊请求、安全主题和家长找孩子资源时不主动询问年龄。
- 真实 `glm-req/glm-5.2` OpenClaw smoke。

## 结果

- 已将产品用户模型固定为孩子和家长；亲子共用只作为场景，教师不属于产品用户。
- 已从 active Skill 的 frontmatter、核心流程、需求理解、搜索策略、候选判断、响应规范和
  MCP 映射中删除教师用户和年龄默认澄清。
- 年龄、年级只在用户主动提供时利用；教材同步任务确实缺少年级或册次时，询问的是资源
  范围，不是用户画像。安全主题缺少年龄时直接按通用儿童安全、内容门槛和家长陪同需求审查。
- 已从 MCP v1 `resource_flow_start.audience` Schema 和 Pydantic 模型删除 `teacher`，并
  增加契约测试。当前字段仍混合学段、`parent` 和 `general`，下一版需要拆分
  `user_role` 与 `resource_target`。
- 前向测试发现语言过滤尚未由 v1 服务端强制执行，已在 MCP 工作流中禁止把非平台过滤
  描述成服务端保证。
- Skill 校验、JSON、Markdown 链接和 `git diff --check` 通过；MCP 语法检查和 29 项
  `unittest` 全部通过。
- 四个独立 Agent 回合验证了安全主题不问年龄、家长为孩子找资料不误写 `audience=parent`、
  未知用户角色不触发澄清，以及 v1 只使用平台硬过滤。
- 真实 `glm-req/glm-5.2` 回合直接判断可以开始防拐骗搜索，明确不询问年龄；OpenClaw
  加载更新后的唯一 Skill 和 9 个 MCP 工具，未使用 fallback。
- `openclaw config validate`、MCP doctor 和 probe 均通过，`diagnostics=[]`。

剩余风险：MCP v1 的 `audience` 仍不是清晰的产品领域字段，类型、语言、时间和时长过滤
仍未强制执行。两项问题保留为下一版契约重构任务，不由 Skill 伪装解决。
