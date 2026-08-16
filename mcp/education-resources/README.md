# Education Resources MCP

`education-resources` 是一个很薄的 Python stdio MCP。它的目标不是管理学习资源工作流，而是把已有的**搜索脚本、平台 Inspect、下载脚本和文件归档能力**稳定地暴露给 Agent。

## 核心边界

```text
Main Agent / Skill
  负责需求理解、搜索规划、相关性判断、候选展示、用户选择、归档分类
        ↓
education-resources MCP
  Search / Browse Creator / Inspect / Download / Job / Archive
        ↓
平台 Search Adapter / Inspector / Downloader + 本地资料库
```

MCP 不再维护：

- Flow / ResultSet / Presentation / Selection；
- Selection version / digest；
- Download Plan / confirmation token；
- SQLite 工作流状态；
- capability/readiness/eligibility authority 链；
- descriptor/registry digest 权威层；
- ArchiveRecord / AssetBundle / Library 状态机。

用户正常对话里的“看过哪些候选、选了第几个、是否明确要求下载、资源应该归到哪个类别”由 Agent 根据当前会话理解，不复制成数据库事务。

## 9 个 Tool

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

### `resource_batch_collect`

```text
resource_batch_collect(platform="douyin", creator_id="...", mode="creator_full", max_items=500)
```

批量枚举模式（0057）：把创作者全量作品写入 `jobs/<job_id>/results.jsonl`，
返回体只有任务句柄和条数，全量清单不进对话。与下载 Job 同一套 detached
worker 语义：跨 MCP/网关重启存活、可取消、崩溃如实 `interrupted`。

### `resource_batch_read`

```text
resource_batch_read(job_id="job_...", offset=0, limit=20)
```

分页读取批量结果文件，单次默认 20 条、上限 50 条。

### `resource_archive`

```text
resource_archive(
  job_id="job_...",
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

下载 Job 已经 `succeeded` 或 `partial` 后，把成功文件移动到学习资料库。Agent 负责判断 `domain_id/topic`；MCP 只做真实文件移动。

分类不确定时可留空 `domain_id`，进入 `99-待分类/其他`。没有 `archive_id`、ArchiveRecord、AssetBundle、digest 或版本状态。

## 最小内部状态与 Job 持久化

进程内只保留一个映射：

```text
resource_id -> Search 返回的原始候选
```

下载 Job 的状态不在进程里，而在文件：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/<job_id>/
  job.json      # Job 状态唯一权威（临时文件 + 原子替换）
  request.json  # 本 Job 的资源快照
  worker.log    # detached worker 的输出
  cancel.flag   # 取消意图（出现即生效）
  ...下载产物
```

每个 Job 由一个脱离 MCP 进程生命周期的 worker 子进程执行（`job_worker.py`）。MCP 或网关重启后：

- 在途 Job 继续下载，`resource_job_status` 照常返回进度和文件；
- worker 已死且未到终态的 Job 会被如实标记为 `interrupted`（重新发起下载即可，不支持断点续传）；
- 终态 Job 的 `resource_archive` 跨重启依然可用。

`resource_id` 句柄会以 `resources.jsonl` 缓存最近 1000 条并在启动时载回——MCP 重启后正在进行的会话仍可继续 inspect/download，不必重搜。不恢复 SQLite/Flow 状态机；0056 只把 Job 状态落在上述文件里。

归档会在资料库根目录追加 `manifest.jsonl`（每次归档一行：来源平台/URL/标题/作者/时间/最终路径），作为零数据库的溯源清单。

## 下载路由

`acquisition/planner.py` 只是一次性的 Provider router：

```text
fresh Inspect
  -> 找到 concrete Representation
  -> 根据 platform / kind / scope / container 选择已注册 Provider
  -> Downloader
```

它不创建 Plan，不生成 fingerprint/digest，不保存 revalidation snapshot。

当前仍复用已经验证过的平台 Downloader，例如 SmartEdu、Douyin、Ximalaya、Bilibili、Anna's Archive、Zjer、generic direct HTTP 和 generic webpage materializer。

Provider 失败不会被伪装成成功；需要登录时返回真实 `AUTH_REQUIRED`。

## 文件与归档目录

下载中的产物位于：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/
```

归档后移动到用户系统自带的“文档/Documents”目录下：

```text
~/Documents/学习资料库/
```

Windows 通常对应：

```text
C:\Users\<用户名>\Documents\学习资料库\
```

如需自定义，可设置：

```text
EDUCATION_RESOURCE_MCP_LIBRARY_DIR
```

目录结构：

```text
学习资料库/
  04-自然科学/
    天文与宇宙/
      视频|音频|图文|其他/
        文件
```

顶层分类配置位于：

```text
src/education_resource_mcp/library-taxonomy.json
```

它只负责 `domain_id -> 目录` 映射，不参与搜索、下载或状态校验。

归档成功后 `resource_job_status` 中对应文件路径也会更新为资料库最终路径。

## 配置

主要环境变量：

```text
EDUCATION_RESOURCE_MCP_DATA_DIR
EDUCATION_RESOURCE_MCP_LIBRARY_DIR
EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT
EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT
EDUCATION_RESOURCE_MCP_MAX_WORKERS
EDUCATION_RESOURCE_MCP_SEARXNG_URL
EDUCATION_RESOURCE_MCP_PREFER_SEARXNG
EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR
```

默认数据目录：

```text
~/.local/share/quanxiao/education-resource-mcp-data
```

默认归档目录：

```text
~/Documents/学习资料库
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
- exact Provider 路由，不在失败后偷偷换 Provider；
- 归档只消费当前 Job 已产生的真实文件，不接收任意外部本地路径。

这些直接保护搜索、下载和归档的正确性。与业务无关的状态证明链已经移除。

## 当前目录重点

```text
src/education_resource_mcp/
├── server.py              # 7 个 MCP Tool
├── service.py             # 轻量资源句柄 + Download Job + Archive
├── search.py              # Generic + 多平台 Search
├── inspection.py          # Inspect 基础能力
├── inspection_registry.py # 直接注册实际 Inspector
├── archive.py             # 文件格式辅助 + 薄归档
├── library-taxonomy.json  # 学习资料库目录配置
├── adapters/              # 平台搜索/Inspect/下载脚本
├── acquisition/           # Provider router + Downloader
├── jobs.py                # detached worker spawner（并发上限沿用 MAX_WORKERS）
├── job_worker.py          # 下载 worker 子进程入口
├── job_state.py           # job.json 状态文件 / 进程探活 / 取消 flag
└── sessions.py            # 登录会话读取
```

没有 `storage.py`、Flow database、tool contract catalog 或 retrieval authority registry。

项目当前最重要的验证仍然是真实 OpenClaw 场景：能不能顺利搜到、判断、选择、下载并归档，而不是重新增加新的形式化门禁。
