# WSL OpenClaw 浏览器配置

- 状态：completed
- 创建日期：2026-07-30
- 完成日期：2026-07-30
- 范围：WSL 用户级 Chrome for Testing、OpenClaw Browser 与 Gateway 配置

## 步骤

- [x] completed：下载并校验 Chrome for Testing 151
- [x] completed：安装到用户级版本目录
- [x] completed：启用 OpenClaw Browser 和本地 Gateway
- [x] completed：运行 browser doctor、版本和页面 smoke 验证

## 验证

- Chrome 可执行文件报告 `151.0.7922.71`。
- OpenClaw Browser 插件状态为 `loaded`。
- Gateway 用户服务已启用且健康检查通过。
- `browser doctor --deep` 全部检查通过。
- 持久 `openclaw` Profile 成功打开 `https://example.com/` 并取得页面快照。
- OpenClaw 配置 Schema 校验通过。
- 已执行仓库级 `git diff --check`；它被任务开始前已有的 CRLF/尾随空白修改阻塞。本计划文件自身的尾随空白检查通过，未改写这些无关文件。

## 结果

- 从 npmmirror 下载 Chrome for Testing `151.0.7922.71`，并使用与 Google 官方一致的 MD5 完成校验。
- 浏览器安装在 `/home/admin_quanxiao/.local/share/chrome-for-testing/151.0.7922.71/`，未覆盖系统 Chrome 149。
- OpenClaw 使用有界面、持久化的 `openclaw` Profile 和自定义 Chrome 151。
- Gateway 已安装为 systemd 用户服务；WSLg 显示变量和 Linux `/tmp` 通过 drop-in 注入。
- 浏览器保持运行，可继续打开目标平台并由用户手动登录。
- 剩余仓库风险：既有未提交文件包含大量 `git diff --check` 告警，与本次浏览器配置无关。
