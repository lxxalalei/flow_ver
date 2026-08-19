# 收敛提交审查修复

- 状态：completed
- 创建日期：2026-08-19
- 完成日期：2026-08-19
- 范围：部署脚本、运行环境验证、测试基线、批量结果读取、active 文档

## Objective

- 让 `eba4578` 的单 MCP 收敛版本能够通过部署前验证、完整测试和 MCP stdio probe，并消除审查发现的 active 文档与静默数据丢失问题。

## Non-goals

- 不修改 Bilibili 日期范围搜索的时区语义。
- 不恢复独立 `session-manager`、旧 contracts、Flow/Plan/Asset 状态链或两阶段下载。
- 不执行真实平台下载、Windows DPAPI 或真实 OpenClaw 用户链路。

## Business invariants

- active 部署只包含 `education-resources` MCP 与 `learning-resource-flow` Skill。
- Session 捕获继续按平台域名和字段筛选，测试不得放宽生产校验。
- 损坏的批量结果必须显式失败，不得以完整页返回。
- 当前旧 checkout 的用户未提交修改不得被触碰。

## Acceptance criteria

- AC-01：PowerShell 同步脚本不再引用或部署已删除的 session-manager/session-login-flow。
- AC-02：源码版本、包元数据和运行环境验证一致，验证器按需求语义而不是说明符文本顺序比较。
- AC-03：完整 pytest、compileall、Markdown 链接、diff check 和 MCP stdio probe 通过。
- AC-04：Batch JSONL 损坏返回结构化 `JOB_STATE_INVALID`，并有回归测试。
- AC-05：active 文档不再链接或声明已删除 contracts 为权威。

## Expected change surface

- Likely to change：`scripts/sync-to-openclaw.ps1`、MCP 版本/验证脚本、相关测试、`docs/README.md`、批量读取实现、少量格式修复。
- Should not change：Bilibili 时间范围实现、Skill 语义、平台 Adapter 行为、旧 checkout 未提交文件。

## 步骤

- [x] completed：修复部署、版本和运行环境验证阻断
- [x] completed：修复测试基线、批量损坏语义和 stdio 覆盖
- [x] completed：修复 active 文档与格式问题
- [x] completed：执行完整验证、提交并推送

## Complexity exceptions

默认：无。此次只删除过期路径、修正现有校验与补回归证据，不新增抽象或 source of truth。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| compileall | passed | Python 源码、测试和脚本可编译 | 真实行为 |
| full pytest | passed（205 tests，最新远端基线） | 当前 MCP 后端回归 | 真实 Agent/平台 |
| runtime verifier | passed（0.4.0） | 安装元数据和运行依赖一致 | Windows/OpenClaw |
| MCP stdio probe | passed（纳入 full pytest，14 Tools） | 进程启动与公共 Tool 暴露 | 真实平台调用 |
| Markdown links / diff check | passed | active 文档相对链接与补丁格式 | 用户链路 |

## 未执行验证

- 当前机器没有 `pwsh`，未执行 PowerShell 解析或 Windows 部署。
- 未执行真实 OpenClaw Agent/用户流程、真实平台登录或下载。
