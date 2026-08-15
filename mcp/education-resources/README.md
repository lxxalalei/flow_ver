# Education Resources MCP

`education-resources` 是一个很薄的 Python stdio MCP。它的目标不是管理学习资源工作流，而是把已有的**搜索脚本、平台 Inspect 和下载脚本**稳定地暴露给 Agent。

## 核心边界

```text
Main Agent / Skill
  负责需求理解、搜索规划、相关性判断、补搜、候选展示和用户选择
        ↓
education-resources MCP
  Search / Browse Creator / Inspect / Download / Job
        ↓
平台 Search Adapter / Inspector / Downloader
```

MCP 不再维护：

- Flow / ResultSet / Presentation / Selection；
- Selection version / digest；
- Download Plan / confirmation token；
- SQLite 工作流状态；
- capability/readiness/eligibility authority 链；
- descriptor/registry digest 权威层；
- Archive/Library 工作流。

用户正常对话里的“看过哪些候选、选了第几个、是否明确要求下载”由 Agent 根据当前会话理解，不复制成数据库事务。

## 6 个 Tool

### `resource_search`

```text
resource_search(search_tasks=[...], limit=8)
```

调用 Generic Web 或平台 Search Adapter，返回候选资源和 `resource_id`。

### `resource_browse_creator`

```text
resource_browse_creator(platform="douyin", creator_id="...", limit=50)
```

用于已知创作者账号后的作品枚举。

### `resource_inspect`

```text
resource_inspect(resource_id="res_...")
```

只在可访问性、格式、版本、资源本体等事实会改变当前判断时调用。

### `resource_download`

```text
resource_download(
  resource_ids=["res_..."],
  preferred_container="original"
)
```

用户明确要求下载后直接调用。服务端会在真正下载前 fresh Inspect，选择实际能处理当前 Representation 的 Provider，然后启动异步 Job。

不再经过：

```text
Selection -> Prepare -> Plan -> Token -> Start
```

### `resource_job_status`

```text
resource_job_status(job_id="job_...")
```

返回下载状态、进度、真实文件和失败。

### `resource_job_cancel`

```text
resource_job_cancel(job_id="job_...")
```

取消当前下载任务。

## 最小内部状态

只保留两个进程内映射：

```text
resource_id -> Search 返回的原始候选
job_id      -> 下载状态 / 文件 / 失败
```

这是调用脚本所需的最小跨 Tool 状态。

`resource_id` 和 Job 不做进程重启恢复。MCP 重启后重新搜索即可；不为这个低频情况恢复 SQLite/Flow 状态机。

## 下载路由

`acquisition/planner.py` 现在只是一次性的 Provider router：

```text
fresh Inspect
  -> 找到 concrete Representation
  -> 根据 platform / kind / scope / container 选择已注册 Provider
  -> Downloader
```

它不创建 Plan，不生成 fingerprint/digest，不保存 revalidation snapshot。

当前仍复用已经验证过的平台 Downloader，例如：

- SmartEdu
- Douyin
- Ximalaya
- Bilibili
- Anna's Archive
- Zjer
- generic direct HTTP
- generic webpage materializer

Provider 失败不会被 Agent伪装成成功；需要登录时返回真实 `AUTH_REQUIRED`。

## 文件位置

下载产物直接位于：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/
```

`resource_job_status` 会返回真实 `path / filename / media_type / size_bytes`。当前没有额外 Archive 状态层。

默认数据目录：

```text
~/.local/share/quanxiao/education-resource-mcp-data
```

## 配置

主要环境变量：

```text
EDUCATION_RESOURCE_MCP_DATA_DIR
EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT
EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT
EDUCATION_RESOURCE_MCP_MAX_WORKERS
EDUCATION_RESOURCE_MCP_SEARXNG_URL
EDUCATION_RESOURCE_MCP_PREFER_SEARXNG
EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR
```

## 安装与启动

```bash
cd mcp/education-resources
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/education-resource-mcp
```

Windows：

```powershell
.venv\Scripts\python -m pip install -e .
.venv\Scripts\education-resource-mcp.exe
```

## 仍然保留的必要边界

做减法不等于删除真实业务需要的检查。当前仍保留：

- HTTP/HTTPS 网络与路径边界；
- 登录会话的真实处理；
- Provider 下载输出必须产生真实文件；
- 取消信号；
- 文件 MIME/格式等下载器本身需要的校验；
- exact Provider 路由，不在失败后偷偷换 Provider。

这些直接保护搜索/下载的正确性。与业务无关的状态证明链已经移除。

## 当前目录重点

```text
src/education_resource_mcp/
├── server.py              # 6 个 MCP Tool
├── service.py             # 轻量资源句柄 + Download Job
├── search.py              # Generic + 多平台 Search
├── inspection.py          # Inspect 基础能力
├── inspection_registry.py # 直接注册实际 Inspector
├── adapters/              # 平台搜索/Inspect/下载脚本
├── acquisition/           # Provider router + Downloader
├── jobs.py                # 小型进程内异步 JobRunner
└── sessions.py            # 登录会话读取
```

没有 `storage.py`、Flow database、tool contract catalog 或 retrieval authority registry。

项目当前最重要的验证仍然是真实 OpenClaw 场景：能不能顺利搜到、判断、选择并下载，而不是重新增加新的形式化门禁。
