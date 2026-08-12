# OpenClaw Session Manager 0.4.0

一套可**独立分发**的 OpenClaw 登录态能力，不依赖也不修改本仓库的
`skills/learning-resource-flow/` 或 `mcp/education-resources/`：

- `session-manager` MCP：平台注册表、登录状态、服务端凭据提取、安全本地保存、探活和删除。
- `session-login-flow` Skill：默认把 MCP 与 OpenClaw Browser 串成“检测 → 打开官方登录页 →
  显式等待用户回复‘已登录’ → 浏览器宽捕获 → MCP 最小化保存 → 按支持情况探活”的流程；也约束
  用户明确授权的 canonical Cookie/Token direct import。

MCP 自己不能操作浏览器；Skill 负责要求宿主使用 OpenClaw Browser。两者一起安装后，
OpenClaw 才会在缺少登录态时主动打开浏览器、提示用户登录，并在用户明确确认后捕获会话。

## 0.4.0 的会话输入模型

浏览器侧不再按 Cookie 名、域名或固定 storage key 预过滤：

1. 用户必须在 OpenClaw 控制的浏览器中自行登录，并明确回复 **“已登录”**。
2. Skill 读取该受控浏览器上下文返回的全部 Cookie。
3. 对 `browser_storage` 平台，Skill 还读取当前官方页面 origin 可见的全部
   `localStorage`、`sessionStorage`，并提交 `location.origin`。
4. MCP 根据平台域名、固定键和受约束的动态模式进行权威提取。
5. MCP 只持久化平台真正需要的 canonical Cookie/Token；原始浏览器快照、无关 Cookie、
   Web Storage 包装和浏览器专用元数据全部丢弃。

因此“浏览器能抓到什么都交给 MCP”不等于“全部保存”。宽捕获只存在于一次
`resource_session_save` 的输入通道中，落盘前一定会做平台化最小化。

已有 canonical `{"cookies": [...]}` 和 `{"tokens": {"accessToken": "<normalized>"}}`
输入继续支持。用户主动提供其合法获得的 Cookie/Token，并明确指定受支持平台、认证用途和保存授权时，
Agent 可把 canonical 值一次性直送 `resource_session_save.session_data`。direct import 不得与同一次
browser capture 混合，也不接受任意 Header、文件、浏览器档案或未声明字段。

## 能力与安全边界

- 默认登录路径中，用户始终在浏览器中自行输入账号、密码、验证码，或完成扫码/MFA。
- Agent 不索取、不接收或代填账号、密码、验证码、扫码内容、短信码或 MFA。仅在用户主动提供合法
  Cookie/Token，并明确指定平台、用途和保存授权时，才可执行上述一次性 direct import。
- 浏览器捕获或 direct import 的原值都不得复述、展示、截图、写入临时文件、日志、计划、仓库或
  任何非 `resource_session_save` Tool。save 失败或响应不确定时不得自动重放或要求用户重发；先查
  权威 status 并停止，后续写入需要新的明确授权。
- `cookie_domains`、`storage_keys`、`storage_key_patterns` 是 MCP 的提取提示，不是浏览器侧
  allowlist；Skill 不应据此缩小浏览器返回的数据。
- MCP 对总字节数、Cookie 数、storage 条目数、字段长度、origin 和域名边界做限制。
- 凭据记录使用原子替换写入。原生 Windows 使用**当前 Windows 用户范围的 DPAPI** 加密，
  落盘 JSON 只包含格式标识和密文，不含 Cookie/Token 明文。
- POSIX-like 环境必须真正落实目录 `0700`、文件 `0600`；无法落实或核验时拒绝启动/写入。
- 许多 WSL `/mnt/c` 挂载不能可靠提供 POSIX 权限语义，不适合作为 WSL MCP 的凭据目录。
  本项目的窗口化 Browser 测试和正式本地运行优先采用**原生 Windows OpenClaw + 原生 Windows MCP**。
- DPAPI 密文只能由同一 Windows 用户上下文解密；它不能防御已在该用户上下文中运行的
  恶意进程，管理员级进程也属于边界外威胁。
- Cookie/Token 仍会从浏览器工具或 direct import 经过 Agent/MCP 参数通道。更强隔离需要未来由宿主 Plugin
  直接捕获并仅返回不透明 `capture_id`。

## MCP 工具

| 工具 | 副作用 | 作用 |
|---|---:|---|
| `resource_session_status` | 否 | 返回状态和登录/捕获元数据；`deep=true` 时按支持情况主动探活。 |
| `resource_session_login_guide` | 否 | 返回官方登录入口、捕获方式和服务端提取提示。 |
| `resource_session_save` | 是 | 接受浏览器宽捕获或明确授权的 canonical direct import，提取、最小化并原子保存；支持幂等键。 |
| `resource_session_delete` | 是 | 删除单个平台的本地会话；支持幂等键。 |

所有工具使用 `contract_version: "1.0.0"`；catalog 版本为 `1.1.0`。MCP 永远不在响应中
返回凭据原文。契约见 [`contracts/v1/`](contracts/v1/)。

## `resource_session_save` 宽捕获输入

Cookie 平台可直接提交浏览器返回的 Cookie 对象：

```json
{
  "cookies": [
    {
      "name": "<browser-returned-name>",
      "value": "<browser-returned-value>",
      "domain": ".example.com",
      "path": "/",
      "httpOnly": true,
      "secure": true
    }
  ]
}
```

Web Storage 平台同时提交当前官方 origin 的存储快照：

```json
{
  "cookies": ["<browser Cookie objects>"],
  "storage_origin": "https://official-origin.example",
  "local_storage": {
    "<browser-returned-key>": "<browser-returned-string-value>"
  },
  "session_storage": {
    "<browser-returned-key>": "<browser-returned-string-value>"
  }
}
```

这些都是结构占位符，不能替换为真实凭据写入文档、日志或叙述。用户明确授权 direct import 时，
原值只能出现在一次 save 输入中。`storage_origin` 必须是当前
页面真实的 `location.origin`，只能使用 HTTP(S)、不能带 userinfo/path/query/fragment，并且
必须按 DNS label 边界匹配平台官方域名。

## 状态语义

- `status=stored` 只表示本地凭据记录已保存且结构检查通过，不表示远端平台已接受登录态。
- 只有 `probe_status=valid` 表示远端平台明确接受当前登录态。
- `probe_status=invalid` 表示平台拒绝；`probe_status=probe_error` 表示探测不确定。
- 平台没有可靠探针或未执行探测时统一报告 `probe_status=no_probe`。
- `missing` 表示没有本地记录；`expired` 表示过期；`invalid` 表示记录结构不可用；
  `not_required` 表示平台不需要登录态。

## 支持平台

| 平台 | 认证 | MCP 提取规则 | 主动探活 |
|---|---|---|---:|
| B站 `bilibili` | Cookie | 从宽 Cookie 捕获中保留 `bilibili.com` 范围 | 是 |
| 知乎 `zhihu` | Cookie | 从宽 Cookie 捕获中保留 `zhihu.com` 范围 | 是 |
| 智慧教育 `smartedu` | Token | 官方 SmartEdu origin 下的固定键或受约束动态存储记录；必要时尝试受约束 Cookie fallback | 否 |
| 网易公开课 `open163` | Cookie | `163.com` | 否 |
| 微信公众号 `wechat` | Cookie | `sogou.com` | 否 |
| 微博 `weibo` | Cookie | `weibo.com` / `sina.com.cn` | 否 |
| 喜马拉雅 `ximalaya` | Cookie | `ximalaya.com` | 否 |
| 百度文库 `baiduwenku` | Cookie | `baidu.com` | 否 |
| 国家图书馆 `nlc` | Cookie | `nlc.cn` | 否 |
| annas-archive / cctv / kepu / yixi / runoob | 无 | 不捕获 | 不需要 |

SmartEdu 可识别受约束的 `ND_UC_AUTH-...&ncet-xedu&token` 动态键，解析其 JSON 中嵌套的
`access_token`/`accessToken`，并归一化为 canonical `tokens.accessToken`。原始动态键、JSON
包装、refresh token、用户资料及无关 Cookie 都不会持久化。受约束的
`UC_TOKEN-...-ncet-xedu` Cookie 仅作为 storage 未提取到 token 时的兼容 fallback；由于平台
没有远端探针，`stored` 不能证明该 fallback 可作为远端 bearer token 使用。

平台规则以 `resource_session_login_guide` 的实时结果为准，不要在 Skill 中硬编码或猜测。

## 从源码安装

要求 Python 3.12+。以下命令在 `mcp/session-manager/` 目录执行。

Linux/macOS/WSL：

```bash
python -m venv .venv
.venv/bin/pip install .
```

原生 Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

console script 和模块启动均可：

```bash
.venv/bin/session-manager
.venv/bin/python -m session_manager
```

Windows：

```powershell
.\.venv\Scripts\session-manager.exe
.\.venv\Scripts\python.exe -m session_manager
```

## 注册 MCP

Linux/macOS/WSL（使用绝对路径）：

```bash
openclaw mcp add session-manager \
  --command "/absolute/path/to/mcp/session-manager/.venv/bin/session-manager" \
  --env "SESSION_MANAGER_DATA_DIR=/absolute/path/to/private/session-data" \
  --include "resource_session_*"
```

原生 Windows PowerShell：

```powershell
$Mcp = (Resolve-Path ".\.venv\Scripts\session-manager.exe").Path
$Data = Join-Path $env:LOCALAPPDATA "OpenClaw\session-manager"
openclaw mcp add session-manager `
  --command "$Mcp" `
  --env "SESSION_MANAGER_DATA_DIR=$Data" `
  --include "resource_session_*"
```

未设置 `SESSION_MANAGER_DATA_DIR` 时，原生 Windows 默认使用
`%LOCALAPPDATA%\OpenClaw\session-manager`。服务启动时初始化并自检 DPAPI；初始化、加密或
解密失败均返回/触发 `SECURE_STORAGE_UNAVAILABLE`，不会降级为明文。

验证：

```bash
openclaw mcp probe session-manager --json
```

应发现 4 个 `resource_session_*` 工具。

## 安装 Skill

```bash
openclaw skills install \
  "/absolute/path/to/mcp/session-manager/distribution/skills/session-login-flow"
openclaw skills info session-login-flow --json
openclaw skills check --json
```

Skill 位于
[`distribution/skills/session-login-flow/`](distribution/skills/session-login-flow/)，与仓库顶层
active Skill 完全隔离。

原生 Windows PowerShell：

```powershell
$Skill = (Resolve-Path ".\distribution\skills\session-login-flow").Path
openclaw skills install --global "$Skill"
openclaw skills info session-login-flow --json
```

## 用户体验与自动串行流程

默认浏览器登录请求的预期流程：

1. Agent 调状态和登录指南。
2. 缺少登录态时，用 OpenClaw Browser 打开 MCP 返回的官方 `login_url`。
3. 提示用户自行登录并回复“已登录”，然后结束当前回合；不能用页面文字、URL 变化、
   Cookie 出现或超时代替这道门。
4. 收到明确“已登录”后，读取宽 Cookie；storage 平台再读取当前官方 origin 的全部
   local/session storage，并立即调用 `resource_session_save`。
5. MCP 提取并只保存最小凭据；Agent 再查状态和可用探针，只报告元数据和结论。
6. 多平台请求会自动打开下一个缺失平台，但每个平台都必须单独等待一次“已登录”。

direct import 分支只在用户主动给出合法 Cookie/Token，并明确指定平台、用途和保存授权时启用：先查
状态和平台支持，再生成唯一幂等键，把 canonical 值一次性直送 `resource_session_save`，随后重新查
状态。不得打开浏览器捕获来混合补全，不得自动重放；`stored/no_probe` 仍须由下游 fresh 平台请求验证。

如果 Browser、MCP 或 Skill 任一缺失，Agent 必须说明缺少的能力，不得假装完成。

## 数据目录

Linux/macOS/WSL 默认：

```text
~/.local/share/session-manager/
├── sessions/       # 每个平台一个 0600 JSON 文件
└── idempotency/    # 不含凭据原文的幂等结果记录
```

原生 Windows 默认：

```text
%LOCALAPPDATA%\OpenClaw\session-manager\
├── sessions\       # DPAPI current-user 加密 envelope
└── idempotency\    # 不含凭据原文的幂等结果记录
```

不要把数据目录放进 Git 仓库、同步盘或多人共享目录。WSL MCP 使用 POSIX 后端，不应把数据
目录放在 `/mnt/c`；原生 Windows MCP 使用 Windows 路径和当前用户 DPAPI，也不需要让浏览器
运行在 WSL 中。

## 构建独立分发包

```bash
python scripts/build_bundle.py
```

输出 `dist/openclaw-session-manager-0.4.0.zip`，包含：

- 可安装 wheel；
- `skill/session-login-flow/`；
- `contracts/`；
- `INSTALL.md`。

解压后安装 wheel，再注册 MCP 与 Skill；已有稳定 `current` Junction 的 Windows 安装可采用
版本目录并排安装后切换 Junction，无需重写 `openclaw.json`。

## 开发验证

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py'
python /mnt/c/Users/admin/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  distribution/skills/session-login-flow
git diff --check
python scripts/build_bundle.py --output-dir ../../.openclaw-test/session-manager-dist
```

Linux 开发环境中的测试只使用临时目录和合成 Cookie/Token。原生 Windows DPAPI 测试会在
Linux 跳过，必须在原生 Windows Python 中执行。真实 Browser 登录 smoke 也应在原生 Windows
OpenClaw 中运行，且只报告 origin 匹配、捕获数量、保存/丢弃数量和状态，不输出任何真实值。
