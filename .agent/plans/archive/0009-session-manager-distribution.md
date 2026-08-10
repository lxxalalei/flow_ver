# 独立登录态分发包

> 历史计划：本计划记录 0.2.0 的首次独立分发。原生 Windows 支持和 0.3.0 替代包见 `0010-session-manager-native-windows.md`；下述 0.2.0 路径与限制不再代表当前交付。

- 状态：completed
- 创建日期：2026-08-03
- 完成日期：2026-08-03
- 范围：`mcp/session-manager/` 内的独立 MCP、分发 Skill、契约、测试与文档

## 目标

在不修改、不依赖 `skills/learning-resource-flow/` 的前提下，交付一套可独立分发给其他
OpenClaw 用户的登录态流程：检测登录状态、打开登录页、等待用户自行登录、通过宿主浏览器
能力捕获最小必要 Cookie/Token、由 MCP 安全保存到本地，并在平台支持时主动探活验证。

## 步骤

- [x] completed：检查工作树、项目约束、现有 session-manager 和 Skill 创建规范。
- [x] completed：设计独立分发目录、平台登录元数据、工具契约与安全边界。
- [x] completed：增强 session-manager MCP，创建独立 `session-login-flow` Skill。
- [x] completed：补充独立测试、安装文档、契约 Schema 与分发说明。
- [x] completed：运行 Python、MCP stdio、打包安装、Skill 和工作区验证并记录结果。

## 验证结果

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -s`：38 个测试全部通过（含原生 Windows fail-closed 回归）。
- `python -m compileall -q`：MCP 源码和构建脚本通过。
- 契约：7 个 JSON 文件全部可解析，契约测试通过。
- MCP stdio：源码测试和从最终 wheel 安装后的 console script smoke 均通过，隔离 OpenClaw 发现 4 个工具且无 diagnostics。
- Skill：`quick_validate.py` 通过，本地 Markdown 相对链接检查通过。
- 分发包：成功重建 `.openclaw-test/session-manager-dist/openclaw-session-manager-0.2.0.zip`；
  包含 12 个条目（wheel、Skill、contracts 和安装文档），最终大小 35055 字节，SHA-256 为
  `a36cd5d3044341fe697c5caa2ba846f6f7cdad2d1992f6fb9714cac6f6b2a00d`，且构建后源码目录没有残留 `build/` 或 `dist/`。
- 隔离 OpenClaw：使用独立 HOME 成功执行 `mcp add`、`mcp probe`、`skills install --global`
  和 `skills info`；MCP 显示 4 个工具，Skill 为 eligible/modelVisible/userInvocable。
- `git diff --check`：通过。

## 结果

独立分发能力已完成，不修改顶层 `skills/learning-resource-flow/`。登录流程强制在打开官方登录页
后结束当前回合，等待用户明确回复“已登录”，再捕获平台注册范围内的最小 Cookie/Token、原子
保存并按平台能力探活。探针已限定为 urllib、禁止凭据重定向且无 curl 子进程回退；原生 Windows
因未实现 ACL/DPAPI 而 fail-closed，需使用 WSL Linux 文件系统。当前原始凭据仍经过 Agent/MCP
参数通道，文件也未使用钥匙串加密；更强
隔离需要后续增加宿主 Plugin，直接捕获并只返回不透明 `capture_id`。
