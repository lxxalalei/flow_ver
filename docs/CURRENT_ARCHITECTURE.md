# 当前架构

> 快照日期：2026-08-19
> 只描述当前 active 运行事实。旧 Flow / ResultSet / Presentation / Selection / Plan / Asset / authority / digest 设计只保留在 Git 历史或 legacy 中。

## 1. 当前定位

项目现在由一个语义 Skill 和一个能力 MCP 组成：

```text
用户自然语言
  ↓
learning-resource-flow Skill / Main Agent
  │  理解目标、设计搜索任务、判断候选、Gap、用户选择和获取意图
  │
  ├── Host Web Search
  │      ↓ 选中具体 URL
  │   resource_import_url
  │
  ↓
education-resources MCP
  ├── Search / Browse / Import / Inspect
  ├── Download / Job / Batch / Archive
  └── Session status / login guide / save / delete
          ↓
      单一 SessionStore
```

核心边界：

> Agent 负责语义判断；MCP 负责真实能力、IO 和必要的运行状态。

Session 是 `education-resources` 内的一组辅助能力，不再拥有独立 MCP 进程。它也不是 Search / Download 的固定前置流程。

## 2. Active 组件

### `skills/learning-resource-flow/`

唯一用户入口和语义决策层，负责：

- 需求理解与必要澄清；
- 搜索任务设计与来源职责；
- 候选质量、内容 Gap、Coverage Gap 和停止判断；
- 用户选择语义；
- 获取意图；
- 归档语义分类。

Skill 不复制 MCP 参数说明，也不把搜索、Inspect、下载、归档写成固定流水线。

### `mcp/education-resources/`

唯一 active MCP。负责平台调用、URL 导入、候选事实检查、下载、批量枚举、Job、归档，以及辅助 SessionStore 管理。

Session 代码职责仍与资源 Adapter 分离，但共用同一进程和同一数据目录，不再经过 `session_bridge.py` 或 standalone/local 双路径。

## 3. 当前 14 个 Tool

资源能力：

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

Session 辅助能力：

11. `resource_session_status`
12. `resource_session_login_guide`
13. `resource_session_save`
14. `resource_session_delete`

Session Tool 只在两种情况下使用：

- 某个真实资源能力返回 `AUTH_REQUIRED`；
- 用户主动要求登录、保存、查询或删除平台登录态。

平台存在登录能力，不等于当前操作需要登录。

## 4. SessionStore

当前只有一份 SessionStore：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/sessions/
```

资源 Adapter 和 Session Tool 直接使用同一个 Store。

浏览器捕获可以较宽，但 MCP 先按平台规则筛选，再只持久化真正需要的 Cookie / Token / storage key；不再因为整包 localStorage/cookie snapshot 较大而在筛选前拒绝。

保留的必要行为：

- 平台域名和字段筛选；
- 过期判断；
- 原子写入；
- Windows 当前用户 DPAPI；
- 支持的平台可选远端 probe；
- 不向 Agent 返回凭据原文。

已删除独立 `session-manager` 为本地写入重放而存在的 operation ledger、idempotency fingerprint/revision 链和跨 Store bridge。

由于不维持双轨兼容层，升级后旧 standalone session 可能需要用户重新捕获一次登录态；之后都写入新的单一 Store。

### SmartEdu

公共 Search / Catalog 始终匿名，不自动重放已保存浏览器 token。公共 401/403 按网络出口/IP 风控/平台访问拒绝处理，不自动转成登录流程。

只有具体 Inspect / Download 真实返回 `AUTH_REQUIRED` 时才进入 Session Tool。

### Anna's Archive

当前 `annas-archive` 是 Libgen 镜像支持的匿名图书发现/获取路线，不需要 Anna 会员登录；SessionStore 对该平台返回 `not_required`。

## 5. Host Web Search 与 URL Import

普通网页发现默认由宿主 OpenClaw Web Search 完成。选中具体 URL 后：

```text
resource_import_url(source_url="https://...")
```

Import 不再无条件把 URL 标成 `generic`。当前对明确 URL 形态做一层薄识别：

- Bilibili 视频 URL → `bilibili` Inspector / Downloader；
- Zhihu 页面 URL → `zhihu` Inspector；
- `basic.smartedu.cn` → `smartedu` Inspector；
- 无法明确识别 → `generic`。

这只是 Host Web 到现有专门能力的桥接，不建立第二套平台 Registry 或 Resolver Framework。

## 6. Generic Web Resource

Generic Web 不再把自研 Block IR 当资源本体。

当前链路：

```text
BoundedWebFetcher
  ↓
source.html             # fetch 成功得到的原始 HTML 响应
  ↓
Trafilatura
  ├── index.html        # 可读 HTML
  ├── content.md        # Markdown
  └── metadata.json     # 获取/抽取事实

+ webbundle.zip
```

原则：

- `source.html` 与正文抽取解耦；抽取失败不能删除已经取得的源响应；
- Trafilatura 负责成熟的正文/结构抽取，不继续扩展自研 `web_blocks.py`；
- 当前不接 Monolith / SingleFile / ArchiveBox，不追求任意动态网页的自包含浏览器级镜像；
- 链接、图片和表格交给 Trafilatura 的结构保留能力，原始 URL/HTML 始终保留最终事实；
- 单个 HTTP 响应仍有真实获取字节上限，超出时显式失败，不截成看似完整的资源。

如果后续真实用户明确需要“离线打开仍尽量完整还原 CSS/图片”的单文件网页，再单独评估 Monolith，不提前引入。

## 7. `resource_id` 与 Job

`resource_id` 只在当前 MCP 进程内有效：

```text
resource_id -> 当前搜索/导入/BatchRead 得到的资源对象
```

稳定资源身份仍是 URL、平台原生稳定 ID 等。句柄失效时优先按已知 URL/平台 ID 重定位同一资源，不重跑整个研究任务。

下载和 Batch 是真实长任务，因此 `job_id` 持久：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/<job_id>/
  request.json
  job.json
  worker.log
  cancel.flag        # 取消后才出现
  results.jsonl      # Batch 才出现
  ...下载产物
```

这不是 durable workflow；没有 Flow、Selection、Plan、Outcome、checkpoint、resume token 或执行绑定状态机。

## 8. Inspect / Download / Batch / Archive

Inspect 只在未知事实会改变推荐、选择或获取决策时使用，不是固定步骤。

资源与最终文件不是一一对应：

```text
1 Resource -> 0..N Files
```

Resource 是用户选择的逻辑对象；Representation 是 Inspect 确认的当前可获取形态/组成事实；File 是 Provider 真正产生的交付物。`primary` Representation 用来确定 exact Provider / acquisition route，`attachment` / `companion` 等可以描述同一逻辑资源自然附带的其他文件。这里不新增 Component/Bundle 持久状态。

`preferred_container="original"` 表示按资源自身的自然交付方式获取。自然交付可以是一个文件，也可以是多个文件；Agent 不应因为 landing URL 本身是 webpage 就判断资源不可下载，也不应为了让它“可下载”自行补一个扩展名。只有用户明确要求当前真实存在的某个主表示时才指定容器；指定不存在的主格式应显式失败。

SmartEdu 课程是当前第一个明确的复合资源案例：课程 detail 可以同时确认主视频、PDF 资料和伴随音频；同一视频的 MP4/HLS/码率变体只选择一个当前主版本，而独立文档/音频保留为 attachment/companion。SmartEdu Downloader 已可为一个课程 Resource 返回多个真实文件，Job 的 `files` / `failures` 是最终事实。

用户已明确选定普通候选并要求下载时直接：

```text
resource_download(resource_ids=[...])
```

下载内部 fresh Inspect，并路由到当前 exact Provider；失败返回真实失败，不静默切换不等价 Provider。

完整枚举使用 `resource_batch_collect`，默认不传 `max_items`，直到来源真实结束；`resource_batch_read` 的分页大小只控制单次 Tool Result。**Batch 结果始终只是候选集合，不等于用户已经选择下载。**

当前 Batch 与 Download 的衔接不增加新 Tool：

- 用户只选择 batch 中的一部分 → `resource_batch_read` 读取必要页，每个返回候选获得当前进程 `resource_id`，再用现有 `resource_download(resource_ids=[...])`；
- 用户明确选择一个完整 `succeeded` batch 的全部结果 → 直接 `resource_download(batch_job_id="...")`，MCP 从该 batch 的 `results.jsonl` 恢复资源事实并提交一个普通多资源 Download Job；Agent 不需要为了下载全部而分页搬运每个 URL；
- batch 若为 `partial` / `failed` / `cancelled`，不能通过 `batch_job_id` 把当前部分结果冒充“全部”。用户仍可明确选择已经展示的个别候选并按 `resource_id` 下载。

这只是把已选择资源的机械循环留在 MCP 后台；用户选择仍属于 Skill/Agent，不创建 Selection/Confirm 状态对象。

Archive 只移动真实下载 Job 已产生的文件；分类语义由 Agent 决定。

## 9. 当前核心目录

```text
skills/learning-resource-flow/

mcp/education-resources/
└── src/education_resource_mcp/
    ├── server.py
    ├── service.py
    ├── search.py
    ├── batch.py
    ├── inspection.py
    ├── archive.py
    ├── jobs.py
    ├── job_worker.py
    ├── job_state.py
    ├── sessions.py
    ├── windows_dpapi.py
    ├── adapters/
    └── acquisition/
        ├── web_fetch.py
        └── web_materializer.py
```

不存在 active `mcp/session-manager/`、`session_bridge.py` 或生产路径 `web_blocks.py`。

## 10. 当前验证重点

1. 同一个 `education-resources` MCP 是否正确暴露资源与 Session Tool；
2. Session broad capture 是否先筛选再保存 canonical session；
3. SmartEdu 保存过 session 时公共 Search 是否仍匿名；
4. Anna/Libgen 是否不触发登录；
5. Host Web URL → Import 是否能恢复明确的平台身份；
6. Generic Web 是否同时保留 `source.html` 与 Trafilatura 可读表示；
7. SmartEdu 课程 Inspect 是否同时暴露主视频与自然附件/伴随内容，`original` 是否无需 Agent 猜格式即可产生多文件 Job；
8. BatchRead 子集候选是否能得到 `resource_id`，完整 succeeded batch 是否能在用户明确选择全部后直接交给现有 Download Job；
9. Download / Batch / Archive 其他既有行为是否未被多文件/批量衔接语义破坏；
10. 真实 OpenClaw 用户链路是否能完成搜索 → 判断 → 用户选择 → 下载 → 文件，且批量枚举不会自动触发下载。

后端测试不能替代第 10 项。
