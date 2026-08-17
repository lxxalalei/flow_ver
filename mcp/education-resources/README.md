# Education Resources MCP

`education-resources` 是一个薄的 Python stdio MCP。它不管理学习资源工作流，只把真实的搜索、资源检查、下载、批量枚举和文件归档能力暴露给 Agent。

## 核心边界

```text
Main Agent / Skill
  需求理解 / 搜索规划 / 相关性判断 / 用户选择 / 归档分类
        ↓
education-resources MCP
  Platform Search / Import URL / Inspect / Download / Job / Batch / Archive
        ↓
平台 Adapter / Downloader / 本地资料库
```

MCP 不维护 Flow、ResultSet、Presentation、Selection、Download Plan、confirmation token、authority/binding/digest 链，也不保存“用户看过第几个候选”这类对话状态。

## 10 个 Tool

1. `resource_search`：调用已接入平台的搜索 Adapter。
2. `resource_browse_creator`：小规模预览一个创作者的作品。
3. `resource_import_url`：把宿主 Web Search 找到的具体 URL 注册成当前进程的资源句柄，并立即 Inspect。
4. `resource_inspect`：确认可访问性、资源类型和实际 Representation。
5. `resource_download`：用户明确要求获取后启动真实下载 Job。
6. `resource_job_status`：查看下载或批量 Job 的状态、进度、文件和失败。
7. `resource_job_cancel`：取消当前 Job。
8. `resource_batch_collect`：把大规模枚举结果流式写入 `results.jsonl`。
9. `resource_batch_read`：分页读取 Batch 结果。
10. `resource_archive`：把成功下载的文件移动到学习资料库。

## Web Search 与 MCP Search

普通网页发现默认由宿主 OpenClaw / anysearch 的 Web Search 完成。挑中具体网页后：

```text
resource_import_url(source_url="https://...")
```

即可进入 Inspect → Download → Archive 管道。

MCP 的 `platform="generic"` 仍可用于宿主 Web Search 中文召回不足时补搜，但不应机械加入每轮搜索计划。

## `resource_id` 只在当前进程有效

Search / Import 返回的 `resource_id` 是临时操作句柄：

```text
resource_id -> 当前 MCP 进程里的资源对象
```

不写 `resources.jsonl`，不为搜索句柄建立数据库或恢复层。

如果 MCP 重启导致句柄失效：

```text
已知选中资源 URL
  → resource_import_url(URL)

已知平台稳定 ID
  → 精确重新定位该资源

只有标题 / 作者 / 平台
  → 做一次针对该资源的最小精确搜索

无法确定原资源
  → 最后才重新执行更宽的原始搜索
```

一旦调用 `resource_download`，完整资源快照已经写入该 Job 的 `request.json`，后续 worker 不依赖旧 `resource_id`。

## Download / Job

```text
resource_download(
  resource_ids=["res_..."],
  preferred_container="original"
)
```

下载前会 fresh Inspect，再按当前真实 Representation 路由到 exact Provider。

Job 使用薄文件状态，是因为真实下载/批量任务需要进度、取消，并且不能因为 MCP / Gateway 重启就无故消失：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/<job_id>/
  request.json
  job.json
  worker.log
  cancel.flag        # 取消后才出现
  results.jsonl      # Batch Job 才出现
  ...下载产物
```

worker 已死但 Job 未到终态时标记为 `interrupted`；重新发起即可，不实现断点 checkpoint、resume token、JobItem、Outcome 或执行绑定状态机。

## Batch：完整结果落盘，对话只分页

小规模预览：

```text
resource_browse_creator(platform="douyin", creator_id="...", limit=50)
```

完整枚举：

```text
resource_batch_collect(
  platform="douyin",
  mode="creator_full",
  creator_id="..."
)
```

`creator_full` 默认不设置 `max_items`，让平台翻页到真实结束。只有用户明确要求“最多 N 条”时才传：

```text
max_items=N
```

当前 Bilibili / Douyin / Weibo 的创作者枚举按平台分页 yield，Batch 边采集边写 `results.jsonl`，不先把完整列表堆进内存。

Bilibili `time_range_search` 同样按天、按页流式枚举，不设人为 90 天上限。去重依据 URL/稳定资源身份，不按标题去重。

读取：

```text
resource_batch_read(job_id="job_...", offset=0, limit=20)
```

单页最多 50 条只是控制一次 Tool Result 的大小；磁盘上的完整结果不会因此被截断。

## Archive

```text
resource_archive(
  job_id="job_...",
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

Agent 判断 `domain_id/topic`，MCP 只移动该下载 Job 已产生的真实文件。分类确实不确定时可留空 `domain_id`，进入 `99-待分类/其他`。

默认资料库：

```text
~/Documents/学习资料库/
```

Windows 通常为：

```text
C:\Users\<用户名>\Documents\学习资料库\
```

可通过：

```text
EDUCATION_RESOURCE_MCP_LIBRARY_DIR
```

覆盖默认目录。

目录示例：

```text
学习资料库/
  04-自然科学/
    天文与宇宙/
      视频/
      音频/
      图文/
      其他/
```

归档根目录还会追加 `manifest.jsonl` 记录来源 URL、平台、标题、作者和最终路径。Manifest 写入失败只记 warning，不影响已经成功移动的文件。

## 配置

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

## 当前目录重点

```text
src/education_resource_mcp/
├── server.py              # 10 个 MCP Tool
├── service.py             # 临时资源句柄 + Job / Archive
├── search.py              # Generic + 多平台 Search
├── batch.py               # 大结果流式枚举 / JSONL
├── inspection.py
├── inspection_registry.py
├── archive.py
├── library-taxonomy.json
├── adapters/
├── acquisition/
├── jobs.py                # detached worker spawner
├── job_worker.py
├── job_state.py
└── sessions.py
```

没有 `storage.py`、Flow database、Plan/digest authority 层或资源句柄持久缓存。

当前最重要的验收仍是真实 OpenClaw 场景：能否顺利完成发现 → 判断 → 选择 → 下载 → 归档，以及大规模枚举时是否不再把上下文塞爆。
