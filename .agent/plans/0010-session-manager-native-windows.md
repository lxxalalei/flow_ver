# Session Manager 原生 Windows 支持

- 状态：completed
- 创建日期：2026-08-03
- 完成日期：2026-08-03
- 范围：`mcp/session-manager/` 的安全存储、Windows 安装说明、测试与分发包

## 目标

允许后续在原生 Windows OpenClaw 和可显示窗口的 Browser 环境中测试登录流程，同时避免把
Cookie/Token 以明文形式持久化。Windows 使用当前用户范围 DPAPI 加密会话记录；POSIX 继续
使用目录 `0700` 和文件 `0600`。两端保持相同 MCP 契约和 Skill 对话行为。

## 步骤

- [x] completed：检查工作树、现有存储格式和 Windows fail-closed 限制。
- [x] completed：实现 Windows DPAPI 加解密与跨平台文件存储策略。
- [x] completed：更新 Windows 安装文档、Skill 安全边界和测试。
- [x] completed：运行 Linux 回归、模拟 Windows DPAPI 测试及静态检查。
- [x] completed：重建最终分发包并验证 wheel、契约和 OpenClaw 注册。

## 验证结果

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`：共运行 48 个测试，
  43 个通过，5 个仅限原生 Windows 的 DPAPI/路径测试在当前 Linux 环境按预期跳过。
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -s`：退出码 0；另用
  `unittest discover -v` 取得完整测试计数。
- `compileall`：MCP 源码和构建脚本通过。
- 契约：7 个 JSON 文件全部可解析，契约测试通过；错误码包含
  `SECURE_STORAGE_UNAVAILABLE`。
- Skill：`quick_validate.py` 通过，本地 Markdown 相对链接检查通过；两轮只读前向流程审查后，
  已明确按操作能力门槛、域名规范化、会话级过期时间、任意 MCP 阶段安全存储失败、
  native Windows/WSL 边界和条件式重登录授权。
- 隔离安装：从最终 ZIP 内 wheel 强制安装成功；OpenClaw MCP probe 发现 4 个工具且
  diagnostics 为空；Skill 为 Ready、model-visible、user-invocable。
- 分发包：`.openclaw-test/session-manager-dist/openclaw-session-manager-0.3.0.zip`，12 个 bundle
  条目，wheel 11 个条目，大小 41307 字节，SHA-256：
  `94bc03b45cf37d99b1076116f20367738caab4ea4e1ceb35fcb56d063a8092ed`。
- 包审计：wheel 包含 `windows_dpapi.py` 和 0.3.0 metadata；使用 current-user
  `CryptProtectData`/`CryptUnprotectData`、用途绑定和加密 envelope；未启用
  `CRYPTPROTECT_LOCAL_MACHINE`，无 curl/subprocess 凭据探针回退，无旧 Windows fail-closed 文案。
- `git diff --check` 通过；顶层 `skills/` 仍只有 `learning-resource-flow`；构建缓存、隔离安装目录和
  0.2.0 ZIP 已清理，仅保留最终 0.3.0 ZIP。

## 结果

原生 Windows 支持和 0.3.0 独立分发包已完成。Windows 会在创建任何临时凭据文件前使用当前
Windows 用户范围 DPAPI 加密整条 session 记录；DPAPI 初始化、自检、加密或解密失败时拒绝
明文降级。MCP 默认数据目录为 `%LOCALAPPDATA%\OpenClaw\session-manager`，并拒绝 UNC、链接、
junction 和重解析点路径。

当前执行环境是 Linux，无法运行原生 Windows DPAPI API、Windows 文件替换/锁行为或可视
OpenClaw Browser。上述 native-only 自动测试和真实“打开浏览器 → 用户登录 → 回复已登录 →
捕获 → DPAPI 保存 → 重启读取 → 删除”smoke 必须在用户的原生 Windows OpenClaw 中执行；
这属于后续环境验证，不影响本次实现与 Linux 分发验证完成状态。
