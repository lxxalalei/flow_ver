# Windows OpenClaw Session Manager 安装验证

- 状态：completed
- 创建日期：2026-08-03
- 完成日期：2026-08-03
- 范围：Windows 用户级 OpenClaw Skill、MCP 注册、原生 Python/DPAPI 与 SearXNG 运行状态

## 步骤

- [x] completed：定位 Windows OpenClaw、Python、现有 Skill/MCP 配置并确认链接类型。
- [x] completed：检查 SearXNG 配置、进程、端口、容器和搜索健康状态。
- [x] completed：在不影响其他 Skill/MCP 的前提下安装 0.3.0，Skill 和 MCP 版本选择使用 Windows junction。
- [x] completed：运行 MCP probe、Skill 检查与原生 Windows DPAPI 假凭据往返验证。
- [x] completed：整理安装路径、验证结果、搜索插件告警和剩余 GUI 登录 smoke 风险。

## 验证结果

- Windows OpenClaw：`OpenClaw 2026.7.1-2 (0790d9f)`；原生 Python 为 3.14.5。
- 安装前 `session-login-flow` Skill 路径不存在，`mcp.servers` 中也没有 `session-manager`，因此没有旧副本需要删除；其他 Skill/MCP 未被重置。
- 分发包 SHA-256 复核为 `94bc03b45cf37d99b1076116f20367738caab4ea4e1ceb35fcb56d063a8092ed`。
- wheel 安装到 `%LOCALAPPDATA%\OpenClaw\packages\session-manager\0.3.0\venv`，`pip check` 报告无依赖冲突，包版本为 0.3.0。
- `%LOCALAPPDATA%\OpenClaw\packages\session-manager\current` 是指向 `0.3.0` 的 Windows Junction；MCP 注册使用该稳定入口下的原生 Windows Python 和 `-m session_manager`。
- `%USERPROFILE%\.openclaw\skills\session-login-flow` 是 Windows Junction，目标为 0.3.0 包内的 Skill；OpenClaw 报告 eligible、modelVisible、userInvocable 和 commandVisible 均为 true。
- `openclaw mcp probe session-manager --json` 发现 4 个 `resource_session_*` 工具，diagnostics 为空；`mcp doctor --probe` 通过；`mcp reload` 已清除缓存，后续 runtime 使用新配置。
- 原生 Windows MCP stdio 假凭据往返成功：保存、重启读取、删除均通过；磁盘 envelope 为 `windows-dpapi-v1`，有 ciphertext，假 Cookie 标记未以明文出现，测试 session 文件已删除。
- SearXNG 运行于 WSL Docker，Windows `127.0.0.1:8888` 由 `wslrelay.exe` 转发；首页、`/config` 和 JSON 搜索均 HTTP 200，最终搜索请求返回 18 条结果。
- 发现独立问题：Windows OpenClaw 已配置 `provider=searxng`，但 `searxng` 插件本体未安装；CLI 明确警告 Gateway 会忽略该可选 provider。后端服务健康不等于 OpenClaw 当前可调用搜索工具。
- `git diff --check` 已通过；工作区源码未因 Windows 安装被覆盖。

## 结果

Windows 原生 OpenClaw 已安装独立 `session-login-flow` Skill 和 `session-manager` MCP 0.3.0。
Skill 与 MCP 的稳定版本入口均使用 Junction；MCP 进程由原生 Windows Python 启动，实际执行了
当前用户范围 DPAPI 加密/解密测试。真实浏览器登录仍需用户参与，未在本轮使用真实账号或
Cookie。SearXNG 后端已启动且搜索正常，但 OpenClaw 的官方 SearXNG 插件缺失，需要单独安装后
才能消除 provider unavailable 告警并让 Gateway 使用该搜索提供商。
