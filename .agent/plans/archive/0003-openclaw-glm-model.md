# OpenClaw GLM 模型配置

- 状态：completed
- 创建日期：2026-07-30
- 完成日期：2026-07-30
- 范围：WSL 用户级 OpenClaw 配置、模型联调和相关项目文档

## 目标

让 WSL 原生 OpenClaw 的 `education-resources-dev` Agent 使用 Claude Code 当前的
`glm-req/glm-5.2`，同时避免把 Token 复制进仓库或 OpenClaw 主配置，并用真实模型
请求验证配置可用。

## 步骤

- [x] completed：安全检查 Claude Code 的模型、协议、端点和凭据来源，不输出密钥。
- [x] completed：配置 `glm-req` Provider、`glm-5.2` 模型、别名和 Agent 默认模型。
- [x] completed：使用 File SecretRef 复用本机 Claude Code Token，并收紧源文件权限。
- [x] completed：完成配置校验、Secret 审计和 Provider 实时 probe。
- [x] completed：完成最小真实 Agent 回合，确认目标模型返回结果且未使用 fallback。
- [x] completed：更新 README、开发计划和既有迁移计划中的验收状态。

## 配置结果

```text
provider: glm-req
api: anthropic-messages
provider model id: glm-5.2
agent model ref: glm-req/glm-5.2
alias: GLM 5.2
```

凭据由 OpenClaw File SecretRef 从 `~/.claude/settings.json` 的
`/env/ANTHROPIC_AUTH_TOKEN` 读取。仓库和 `openclaw.json` 均不保存实际 Token。
修改前配置备份位于用户 OpenClaw 配置目录，不进入仓库。

## 验证

- OpenClaw 配置 Schema 校验通过。
- Secret 审计为 clean，明文凭据计数和未解析引用计数均为 0。
- `glm-req/glm-5.2` Provider probe 返回成功。
- `education-resources-dev` 最小本地 Agent 回合返回预期文本，执行轨迹显示目标模型
  成功且未使用 fallback。
- MCP doctor/probe 继续成功并发现 9 个领域工具。

## 结果与剩余范围

本次模型配置任务全部完成。尚未执行的是完整教育资源业务回合，它属于阶段 6 的
后续验收，不是本次模型配置的阻塞项。若改为通过常驻 Gateway 运行，还需单独完成
Gateway 客户端认证和设备配对。
