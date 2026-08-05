# 浏览器宽捕获与平台化凭据提取

- 状态：completed
- 创建日期：2026-08-03
- 完成日期：2026-08-03
- 范围：mcp/session-manager 的捕获契约、SmartEdu 提取、独立 session-login-flow Skill、Windows 分发安装与验证

## 步骤

- [x] completed：检查现有捕获契约、SmartEdu 规则、测试、分发脚本和 Windows 安装状态。
- [x] completed：实现浏览器宽捕获输入、MCP 平台化提取和最小化持久化，并兼容已有精确输入。
- [x] completed：更新独立 Skill、契约 Schema、文档和回归测试，不改动 active 教育资源 Skill/MCP。
- [x] completed：构建 0.4.0，备份 Windows OpenClaw 配置后升级 MCP 与 Skill Junction。
- [x] completed：运行 Python/契约/Skill 验证、Windows MCP probe/doctor 和不泄露凭据的 SmartEdu 合成冒烟检查。

## 验证

- `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py'`：64 个测试通过，5 个仅适用于原生 Windows 的测试跳过；HTTP 302 测试仍有一个已有的无害 `ResourceWarning`。
- `python -m compileall -q -f src tests scripts`：通过；生成的 `__pycache__` 已清理。
- Skill `quick_validate.py`：通过。
- `git diff --check`：通过。
- 分发包：`openclaw-session-manager-0.4.0.zip`，SHA-256 为 `3c90a2c224e683180687cc8056c6d03d5d276583b0cc8d7aeef584da6a366f05`；旧 `0.3.0` 测试包已删除。
- Windows OpenClaw：版本 `2026.7.1-2 (0790d9f)`；`mcp status` 显示 `session-manager` configured/enabled/ok；probe 发现 4 个工具且无 diagnostics；doctor `ok=true` 且无 issues。
- Windows Skill：`session-login-flow` eligible、modelVisible、userInvocable、commandVisible 均为 true。
- Windows DPAPI 假凭据保存、重启读取、删除往返：通过。
- Windows SmartEdu 合成宽捕获：提取并仅保存 1 个 `accessToken`，丢弃 3 个无关项，随后成功删除；未输出或使用真实凭据。

## 结果

- `session-manager` 版本升级为 `0.4.0`。浏览器侧可在用户明确回复“已登录”后提交当前受控上下文返回的全部 Cookie，以及当前官方 origin 可见的全部 `localStorage` / `sessionStorage`；Agent 不再按名称、域名或存储键预筛选。
- MCP 在服务端按平台域边界和提取规则处理宽输入，只持久化最小规范凭据；原始浏览器 dump 不落盘，幂等指纹基于最小化后的规范凭据。
- SmartEdu 支持精确 Token 键、受约束的动态 `ND_UC_AUTH-...&ncet-xedu&token` 键、有限深度嵌套 JSON 和受约束 Cookie fallback，并校验官方 origin、Cookie 域、过期时间、候选冲突与畸形匹配 JSON。
- 原生 Windows 安装目录为 `C:\Users\admin\AppData\Local\OpenClaw\packages\session-manager\0.4.0`；`current` 和 `session-login-flow` 均为指向 0.4.0 的 Junction。
- OpenClaw 配置升级前备份为 `C:\Users\admin\.openclaw\backups\openclaw.json.20260803-195553.session-manager-0.4.0.bak`，备份与升级前配置哈希一致；升级后配置哈希未变化。
- `skills/learning-resource-flow/` 与 `mcp/education-resources/` 本次均未修改。

## 已知边界与后续验证

- 仍保留每个平台独立的用户“已登录”确认门，不绕过账号密码、验证码、MFA、付费墙或访问控制。
- 本轮没有在真实 SmartEdu 账号上执行交互式浏览器抓取，因为当前执行环境没有可直接调用的 OpenClaw 浏览器控制接口，且真实抓取必须等待用户登录确认。Windows 合成提取和 DPAPI 持久化已通过；SmartEdu Cookie fallback 是否可直接作为真实请求 Bearer 凭据，仍需一次不泄露值的真实平台请求验证。
- 宽捕获值当前仍会经过 Agent 到 MCP 的工具参数；服务端保证最小化落盘，但若要进一步避免 Agent 接触原始值，后续应增加浏览器宿主侧不透明 `capture_id`，由 MCP/可信宿主直接交换数据。
- Windows 上保留已安装的 `0.3.0` 目录作为回滚点；只删除了工作区中的过期 `0.3.0` 分发 zip。
