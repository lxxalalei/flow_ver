# 当前架构

> 快照日期：2026-08-18  
> 只描述当前 active 运行事实。旧 Flow / ResultSet / Presentation / Selection / Plan / authority 设计只保留在 Git 历史。

## 1. 当前定位

`education-resources` 是一个**资源能力 MCP**，不是资源工作流后端。

```text
用户自然语言
  ↓
learning-resource-flow Skill / Main Agent
  │  理解目标、规划搜索、判断候选、理解用户选择、决定归档分类
  ↓
education-resources MCP
  │  Platform Search / Import URL / Inspect / Download / Batch / Archive
  ↓
平台 Adapter / Downloader / 本地资料库
```

核心边界：

> Agent 负责语义判断；MCP 负责真实 IO、平台调用和文件副作用。

MCP 不复制“用户看过哪些候选、选择第几个、是否满足目标”等对话状态，也不把正常用户行为建模成数据库事务。

## 2. 当前 10 个 Tool

1. `resource_search`
2. `resource_browse_creator`
3. `resource_import_url`
4. `resource_inspect`
5. `resource_download`
6. `resource_job_status`
7. `resource_job_cancel`
8. `resource_batch_collect`
9. `resource_batch_read`
10. `resource_archive`

已移除且不应恢复为主链的工作流 Tool/状态：Flow、ResultSet lineage、Presentation、Selection、Download Plan、confirmation token、ArchiveRecord、AssetBundle、authority/binding/digest 链。

## 3. 搜索与外部 Web 的分工

专门平台搜索走：

```text
resource_search
```

普通网页发现默认走宿主 OpenClaw / anysearch 的 Web Search。Agent 选中具体 URL 后：

```text
resource_import_url(source_url="https://...")
```

MCP 对这个 URL 建立当前进程内的 `resource_id`，立即 Inspect，然后可继续 Download / Archive。

MCP 的 `platform="generic"` 仍保留，但只作为宿主 Web Search 中文召回不足时的补充路线，不再机械加入每轮搜索计划。

## 4. `resource_id` 是临时句柄

MCP 只在当前进程内保留：

```text
resource_id -> 当前搜索/导入得到的原始资源对象
```

不写 `resources.jsonl`，不做 resource handle 数据库恢复。

原因：`resource_id` 只是这次会话调用 MCP 时对资源的临时称呼。真正稳定的资源身份是 URL、平台资源 ID 等。

MCP 重启导致旧 `resource_id` 失效时，恢复顺序是：

```text
已知原 URL
  → resource_import_url(URL)

已知平台稳定 ID
  → 精确重新定位该资源

只有标题/作者/平台
  → 针对该具体资源做最小精确搜索

无法确定原资源
  → 最后才回到原始搜索任务重新发现候选
```

不要因为一个临时句柄失效就重新执行整套研究任务。

## 5. Inspect 与 Download

Inspect 只在事实会改变推荐或下载决策时调用。

用户明确要求下载后：

```text
resource_download(resource_ids=[...])
```

每个资源执行：

```text
fresh Inspect
  ↓
AcquisitionPlanner.route()
  ↓
exact registered Provider
  ↓
Downloader
```

`AcquisitionPlanner` 只是一次性 Provider router，不创建持久 Plan、fingerprint、digest 或 revalidation snapshot。

## 6. Job：只为真实长任务持久

下载和批量枚举可能跨较长时间，用户需要进度、取消以及 MCP / Gateway 重启后的真实状态，因此 Job 使用薄文件状态：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/<job_id>/
  request.json
  job.json
  worker.log
  cancel.flag        # 只有取消后才出现
  results.jsonl      # 只有 batch job 才出现
  ...下载产物
```

每个 Job 由 detached worker 执行。MCP 重启不等于下载任务被取消；worker 已死且 Job 未到终态时标记为 `interrupted`。

这不是 durable workflow：没有 JobItem / Outcome / checkpoint / resume token / execution binding / job version。Interrupted 任务重新发起即可，不做断点状态机。

## 7. Batch：大数据不进入对话

`resource_browse_creator(limit=50)` 是交互式预览。

需要完整枚举创作者作品时：

```text
resource_batch_collect(
  platform="douyin",
  mode="creator_full",
  creator_id="..."
)
```

默认**不设 `max_items`**，平台翻页到真实结束；只有用户明确说“最多 N 条”时才传 `max_items=N`。

当前 Bilibili / Douyin / Weibo 创作者枚举使用内部 generator 按页 yield，Batch 一边采集一边 append 到 `results.jsonl`，不先把完整资源列表堆在内存里。

Bilibili `time_range_search` 同样按天、按平台分页流式写入；不再有人为 90 天上限。

去重使用稳定 URL/资源身份，不按标题去重，避免两个同名资源被误删。

读取结果：

```text
resource_batch_read(job_id=..., offset=0, limit=20)
```

单页最多 50 条只是 Tool Result 分页大小，不会截断磁盘上的完整结果集。

## 8. Archive

下载 Job 到达 `succeeded` 或 `partial` 后：

```text
resource_archive(
  job_id=...,
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

Agent 决定语义分类；MCP 只移动真实文件。

默认资料库根目录：

```text
~/Documents/学习资料库/
```

Windows 通常对应：

```text
C:\Users\<用户名>\Documents\学习资料库\
```

可通过 `EDUCATION_RESOURCE_MCP_LIBRARY_DIR` 覆盖。

资料库会追加 `manifest.jsonl` 记录来源 URL、平台、标题、作者和最终路径。Manifest 写入失败只记录 warning，不把已经成功的文件归档伪装成失败。

没有 `archive_id`、ArchiveRecord、AssetBundle、archive digest/version 或 ready state。

## 9. 当前应保留的必要检查

保留这些直接保护真实能力正确性的边界：

- HTTP/HTTPS 和本地路径合法性；
- 平台真实登录态；
- Provider 必须产生真实文件；
- exact Provider 路由；
- 下载/批量取消；
- 文件格式/MIME 等下载器实际需要的校验；
- 抖音 creator_id 明显截断时直接报错；
- Bilibili `creator_id` 接受数字 mid 或真实 `space.bilibili.com/<mid>` 主页 URL。

不保留与真实业务无关的证明链、哈希绑定或任意数据截断。

## 10. 当前核心目录

```text
mcp/education-resources/src/education_resource_mcp/
├── server.py
├── service.py
├── search.py
├── batch.py
├── inspection.py
├── inspection_registry.py
├── archive.py
├── library-taxonomy.json
├── jobs.py
├── job_worker.py
├── job_state.py
├── sessions.py
├── session_bridge.py
├── adapters/
└── acquisition/
```

已删除且不应恢复为主链：

```text
storage.py
models.py（旧 Flow/Contract 输入模型）
retrieval/
contracts/
taxonomy.py（旧运行时 taxonomy/校验体系）
```

## 11. 当前验证重点

1. Search / Web Search → Import URL 是否返回真实可用资源；
2. Inspect 是否得到下载需要的实际 Representation；
3. Download 是否产生正确文件；
4. Batch 是否真正翻页到平台结束、结果不被硬截断；
5. `resource_batch_read` 是否只分页而不丢数据；
6. Archive 是否移动到正确资料库目录并返回最终路径；
7. OpenClaw 长任务是否不再因 Tool Result 膨胀而频繁 compaction；
8. 平台真实失败是否诚实暴露。

验证重点是真实业务行为，不让旧状态契约测试迫使实现重新复杂化。
