# Session Manager MCP

独立的 cookie 管理 MCP 服务。只做三件事：**查询登录状态 / 存 cookie / 删 cookie**，外加对已存 cookie 的**主动探活**。

不依赖教育资源流水线，自带 14 个平台注册表。给需要测试"平台登录态捕获与校验"的人单独使用。

## 它做什么 / 不做什么

- ✅ 暴露 3 个 MCP 工具（见下），存到独立的数据目录。
- ✅ `deep=true` 时主动打平台探针接口，确认 cookie 服务端是否还认（目前 bilibili、zhihu 支持）。
- ❌ **不抓 cookie**——抓取由宿主（OpenClaw 的 browser 工具）完成，本服务只负责存/查/验。
- ❌ **永不回传 cookie 原文**——所有工具响应只返回状态和元数据。

## 工具

| 工具 | 作用 |
|---|---|
| `resource_session_status` | 批量查平台登录状态；`deep=true` 主动探活。返回 `needs_login` 列表。 |
| `resource_session_save` | 存已捕获的 session（`{"cookies":[...]}`）。 |
| `resource_session_delete` | 删除某平台 session。 |

所有工具首个参数为 `contract_version: "1.0.0"`。

## 平台注册表（14 个）

| 可捕获登录（9） | 登录入口 | 免登录（5） |
|---|---|---|
| bilibili B站 | passport.bilibili.com/login | annas-archive 安娜的档案 |
| zhihu 知乎 | zhihu.com/signin | cctv 央视网 |
| smartedu 智慧教育 | basic.smartedu.cn | kepu 科普中国 |
| open163 网易公开课 | open.163.com | yixi 一席 |
| wechat 微信公众号 | weixin.sogou.com | runoob 菜鸟教程 |
| weibo 微博 | passport.weibo.com/sso/signin | |
| ximalaya 喜马拉雅 | ximalaya.com/login | |
| baiduwenku 百度文库 | wenku.baidu.com | |
| nlc 国家图书馆 | read.nlc.cn | |

其中 **bilibili、zhihu** 配了探针 URL，`deep=true` 能真正校验；其余可捕获平台无探针时返回 `probe_status="no_probe"`。

平台按认证流派分三类（`auth_kind`）：
- **cookie**（bilibili/zhihu/weibo/ximalaya/open163/wechat/baiduwenku/nlc）：抓 `browser cookies`。
- **token**（smartedu）：抓 localStorage 里的 accessToken，**不是 cookie**——见下方"Token 平台"。
- **none**（annas-archive/cctv/kepu/yixi/runoob）：公开，免登录。

## 安装

需要 Python ≥ 3.12。

```bash
cd session-manager
python -m venv .venv
# Linux/macOS:
.venv/bin/pip install -e .
# Windows:
.venv\Scripts\pip install -e .
```

唯一依赖是 `mcp==2.0.0`。

## 数据目录

cookie 存在 `<data_dir>/sessions/<platform>.json`，**独立于任何其他 MCP**。

- 默认：`~/.local/share/session-manager/`（Linux/macOS）或 `%USERPROFILE%\.local\share\session-manager`（Windows）。
- 自定义：设环境变量 `SESSION_MANAGER_DATA_DIR=/path/to/dir`。
- 想和别的 MCP 共享 cookie：把该变量指向那个 MCP 的 data 目录即可。

## 在 OpenClaw 里注册

### 方式 A：命令行

```bash
openclaw mcp add session-manager \
  --command ".venv/bin/python" \
  --args "-m" "session_manager"
```

（Windows 把 `.venv/bin/python` 换成 `.venv\Scripts\python`）

### 方式 B：编辑 openclaw.json

在 `mcp.servers` 里加：

```jsonc
"session-manager": {
  "command": "<到 .venv 的绝对路径>/bin/python",
  "args": ["-m", "session_manager"],
  "env": {
    "SESSION_MANAGER_DATA_DIR": "<可选：自定义 cookie 存放目录>"
  },
  "connectTimeout": 10,
  "timeout": 30,
  "toolFilter": { "include": ["resource_*"] }
}
```

注册后重启 gateway 或 `openclaw mcp reload`，用 `openclaw mcp probe session-manager --json` 确认能看到 3 个工具。

## 捕获流程（在 OpenClaw 对话里）

1. **查状态**：让 agent 调
   `resource_session_status(contract_version="1.0.0", platforms=["bilibili","zhihu"])`
   → 看 `needs_login` 里有哪些要登录。
2. **开浏览器登录**：agent 用 browser 工具打开 `login_url`，**用户自己登录**（本服务不代填账密）。
3. **读 cookie 并保存**：agent 用 `browser cookies` 读出 cookie，按域名筛，调
   `resource_session_save(contract_version="1.0.0", platform="bilibili", session_data={"cookies":[...]})`。
4. **复核**：调
   `resource_session_status(contract_version="1.0.0", platforms=["bilibili"], deep=true)`
   → `probe_status="valid"` 说明 cookie 真有效；`"invalid"`/`"probe_error"` 则重抓。

### Token 平台（smartedu）

smartedu 不用 cookie，用的是 **localStorage 里的 accessToken**（Bearer token）。抓取方式不同：

1. agent 用 `browser navigate https://basic.smartedu.cn/`，用户登录。
2. agent 用 **`browser evaluate`** 读 localStorage（不是 `browser cookies`）：
   ```js
   // 找到 accessToken（具体 key 以站点实际存储为准）
   Object.fromEntries(Object.entries(localStorage).filter(([k]) => /token|auth/i.test(k)))
   ```
3. 把 token 存成 token 结构：
   ```
   resource_session_save(contract_version="1.0.0", platform="smartedu",
     session_data={"tokens": {"accessToken": "<token>"}, "headers": {"x-nd-auth": "<可选>"}})
   ```
   本服务会据此构造 `Authorization: Bearer <token>` + `accessToken` 两个请求头去探活。

> smartedu 目前没有干净的 whoami 探针端点，`deep=true` 暂返回 `no_probe`；token 是否真有效在下载/受限内容适配器实际使用时确认。后续找到 token 门禁端点后，补 `probe_url` 即可自动校验。

## 安全边界

- `session_data` 只含 cookie/token，不含用户名密码。
- 所有工具响应**不返回 cookie 原文**，只返回状态、时间戳和探活结果。
- 数据目录在仓库外，不会进版本控制。
- 不绕过验证码、不代登录；用户必须自己完成登录。

## 与上游的关系

本包的 `store.py` / `http_client.py` 移植自教育资源 MCP（`education_resource_mcp.sessions` / `.adapters.http_client`）。如果上游的探活逻辑或平台注册表更新，这里需要同步。
