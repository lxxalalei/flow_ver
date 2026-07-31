# 目标优先的语义 Skill 重建

- 状态：completed
- 创建日期：2026-07-30
- 完成日期：2026-07-30
- 范围：项目约束、`skills/learning-resource-flow/`、legacy 语义资产、示例与开发文档

## 目标

从最终用户通过自然对话发现、判断、选择并安全保存教育资源的结果反推 active Skill。
旧七个 Skill 只作为领域经验和回归样本，不保留其多 Skill 调度、Stage JSON、脚本路径
或目录结构。MCP 继续承担权威状态和确定性执行，Skill 重新承担完整的教育语义决策。

## 步骤

- [x] completed：将目标优先、允许推倒重构和 legacy 仅作参考写入持久项目约束。
- [x] completed：按需求理解、搜索决策、候选判断审计旧流程的有效语义资产。
- [x] completed：从零设计并重建唯一 active Skill 的语义架构和渐进式 references。
- [x] completed：更新示例与项目文档，明确 Skill/MCP 新边界。
- [x] completed：运行结构、语义回归和独立前向测试并结清计划。

## 非目标

- 不恢复旧七个可发现 Skill。
- 不恢复 Stage 1-6 文件流水线、manifest、session_dir 或模型拼接脚本命令。
- 不因 legacy 当前支持某个平台就直接承诺该平台已经迁移。
- 本计划不改写 MCP 的下载安全和权威状态边界，除非新的语义设计发现契约缺口并另行记录。

## 验证

- `skill-creator` 的 `quick_validate.py`。
- 新语义对话案例的静态完整性和回归检查。
- 独立 Agent 对模糊需求、搜索策略与候选判断场景的前向测试。
- Markdown 本地链接、文件存在性和 `git diff --check`。

## 结果

- 已把“最终用户结果优先、允许推倒重构、legacy 只作知识与证据来源”写入
  `AGENTS.md`、`USER.md` 和开发计划。
- 已并行审计旧 Intent、Search 和 Selector，保留需求影响测试、儿童受众与适龄、
  约束强度、学习体验搜索、证据护栏和互补推荐；未迁回旧 Stage、脚本或模型评分文件。
- 已从零重建唯一入口 Skill，新增需求澄清、发现策略和候选判断三个渐进式 reference，
  重写 MCP 映射与用户响应规则，并建立 17 个语义回归案例。
- 已记录 MCP 下一轮必须解决的任务契约、多查询聚合、硬过滤执行和候选证据缺口。
- `quick_validate.py`、JSON 解析、Markdown 本地链接和 `git diff --check` 均通过。
- 三个独立 Agent 前向测试覆盖模糊需求、安全教育搜索、候选判断和修改下载选择，均通过。
- 首次真实 GLM smoke 暴露“主题和年龄合并提问”，已把单一语义维度规则提升到
  `SKILL.md` 并复测；第二次 `glm-req/glm-5.2` 回合只询问核心主题，加载唯一 Skill
  和 9 个 MCP 工具，未使用 fallback。

剩余风险：当前 MCP v1 仍只能用单查询替换展示集合，无法结构化保存完整学习者与约束，
且类型、语言、时间、时长过滤尚未全部在服务端强制执行。上述问题已进入开发计划的下一项
契约重构，不由 Skill 伪装为已经解决。
