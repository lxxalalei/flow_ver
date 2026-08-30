# 当前架构

> 快照日期：2026-08-25
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
  ├── Search / Expand / Import / Inspect / Download
  ├── Job status / cancel / paged read / Archive
  └── Session status / manage
          ↓
      单一 SessionStore
```

核心边界：

> Agent 负责语义判断；MCP 负责真实能力、IO 和必要的运行状态。

Session 是 `education-resources` 内的一组辅助能力，不再拥有独立 MCP 进程。它也不是 Search / Download 的固定前置流程。

## 2. Active 组件

### `skills/`

唯一用户入口和语义决策层，负责：

- 需求理解与必要澄清；
- 搜索任务设计与来源职责；
- 候选质量、内容 Gap、Coverage Gap 和停止判断；
- 用户选择语义；
- 获取意图；
- 归档语义分类。

Skill 不复制 MCP 参数说明，也不把搜索、Inspect、下载、归档写成固定流水线。

### `mcp/education-resources/`

唯一 active MCP。负责平台调用、URL 导入、结构展开、候选事实检查、下载、Job、归档，以及辅助 SessionStore 管理。

Session 代码职责仍与资源 Adapter 分离，但共用同一进程和同一数据目录，不再经过 `session_bridge.py` 或 standalone/local 双路径。

## 3. 当前 12 个 Tool

资源能力：

1. `resource_search`
2. `resource_expand`
3. `resource_import_url`
4. `resource_inspect`
5. `resource_download`
6. `resource_job_status`
7. `resource_job_cancel`
8. `resource_job_read`
9. `resource_html_design`
10. `resource_archive`

Session 辅助能力：

11. `resource_session_status`
12. `resource_session_manage`

公共面不再暴露 `resource_browse_creator`、`resource_batch_collect`、`resource_batch_read`，也不暴露 `creator_full`、`time_range_search`、`catalog_expand`、`collection_expand`、`start_day/end_day/specs/tabs` 等平台 mode 或参数。容器统一通过 `resource_expand` 展开，结果统一通过 `resource_job_read` 分页读取。

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

### 公共 Tool 与内部认证契约分离

`resource_session_manage` 对 Agent 只暴露：

```text
action         # save | delete
platform
capture?       # 仅 save；opaque browser-session capture object
expires_at?    # 仅 save
```

Agent 不需要知道 `capture` 内部某个平台具体依赖哪些 Cookie 名、storage key 或 Token 字段，也不手工筛选/拼接 credential。浏览器捕获可以较宽，SessionStore 再按平台内部规则筛选，只持久化 canonical subset。

平台认证事实继续保存在内部 `PlatformConfig` / SessionStore 中。例如 SmartEdu 当前明确：

```text
auth_kind = token
capture_method = browser_storage
storage_keys = accessToken, x-nd-auth
required_storage_keys = accessToken
```

这些内部字段不通过 `resource_session_status` 暴露给 Agent；status 只保留平台、登录 URL、捕获方式、probe 能力和状态。指定平台查询且确实需要登录时才附带登录步骤，全量状态查询不重复展开步骤。

Cookie 平台当前已确认域名边界，但并非每个平台都已经实测到最小 Cookie 名集合。没有证据时继续按当前内部域名筛选，不为了“更严格”凭经验增加 Cookie 名白名单。Z-Library 是明确例外：现行 EAPI 已确认只需要 `remix_userid` 与 `remix_userkey`，SessionStore 会丢弃同域其他 Cookie，且不会接收邮箱或密码。

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

教材 URL 的 Expand 直接匿名读取资源分片，按真实 404 或空分片结束，不设置任意分片上限。同步课、精品课生成真实子 Resource；无独立详情 URL 的绑定类型与无效条目通过 Job `summary.smartedu` 显式计数。

只有具体 Inspect / Download 真实返回 `AUTH_REQUIRED` 时才进入 Session Tool。

### LibGen

当前 active 平台标识为 `libgen`，搜索、检查和下载由 LibGen mirror + MD5 驱动，不需要登录，也不进入 Session 管理。

### Z-Library

当前 active 平台标识为 `zlibrary`。用户在浏览器自行登录后，MCP 从 browser capture 中只保存 `remix_userid` 与 `remix_userkey`，并通过受信任 EAPI 域名完成搜索、详情检查和单书下载。`book_id + book_hash` 是稳定操作身份；下载受用户账号每日额度约束，缺少登录态返回 `AUTH_REQUIRED`，额度耗尽返回 `RATE_LIMITED`。

MCP 不保存账号密码，不自动把凭据切换到发现到的陌生镜像。EAPI 域名只能从内置受信任集合选择，可用 `EDUCATION_RESOURCE_MCP_ZLIBRARY_EAPI_DOMAIN` 在该集合内显式切换。文件下载发生跨域重定向时，只允许 Cookie 继续发送给同一 Z-Library 域名族，外部 CDN 不携带登录 Cookie。该平台不作为 LibGen 的静默 fallback。

## 5. Host Web Search 与 URL Import

普通网页发现默认由宿主 OpenClaw Web Search 完成。选中具体 URL 后：

```text
resource_import_url(source_url="https://...")
```

Import 不再无条件把 URL 标成 `generic`。当前对明确 URL 形态做一层薄识别：

- Bilibili video / creator / collection；
- Douyin video / creator / collection；
- Ximalaya track / album / creator；
- SmartEdu textbook / course；
- Zjer course；
- CCTV column / video；
- LibGen book；
- Z-Library book；
- Zhihu 页面；
- 无法明确识别 → `generic`。

这只是 Host Web 到现有专门能力的桥接，不建立第二套平台 Registry 或 Resolver Framework。

## 6. Generic Web Resource

Generic Web 不再把自研 Block IR 当资源本体。

当前链路：

```text
BoundedWebFetcher
  ↓
source.html                         # fetch 成功得到的原始 HTML 响应，完全不改
  ↓
Trafilatura
  ├── content.md                    # 清洗后的 Markdown
  └── cleaned semantic HTML
          ↓
     Reader template
     Simple.css 2.3.7 (vendored, MIT)
     + 少量本项目阅读样式
          ↓
       index.html                    # 单文件可读 HTML，CSS 与正文图片内嵌

用户明确要求视觉设计时：
resource_html_design(context)        # 有界摘录、提纲、结构统计，显式标记截断
  -> Agent HTML Design Skill         # 主题 / 受众 / 页面任务 / DesignSpec
  -> resource_html_design(render)    # 完整清洗正文原样注入 adaptive-reader-v1

metadata.json                        # 获取 / 抽取 / Reader 事实
```

原则：

- `source.html` 与正文抽取解耦；抽取失败不能删除已经取得的源响应；
- Trafilatura 继续负责成熟的正文/结构抽取，不继续扩展自研 `web_blocks.py`；
- Reader 只包装 Trafilatura 的清洗后派生 HTML，不参与正文判断，也不反向修改 `source.html` / `content.md`；
- 默认单文件模板标识为 `clean-reader-v2`；用户明确要求设计后为 `adaptive-reader-v1`；
- Reader 基础主题使用 vendored Simple.css 2.3.7，保留 MIT 许可证；生成的 CSS 和正文图片直接内嵌进 `index.html`，不依赖 CDN、npm、JS 或在线字体；
- Reader 统一处理正文宽度、中文/英文系统字体、标题层级、链接、图片、表格、引用、代码块、移动端、dark mode 与打印；
- HTML Design Context 只给模型有界摘录、提纲和结构统计，并显式暴露截断；网页内容视为不可信数据。DesignSpec 不包含正文、HTML、CSS 或脚本；本地 Renderer 保持 main 正文片段逐字不变，使用受控的明暗 token、字体栈、布局与构件变体更新终态文件记录；
- HTML Design 只支持恰好含一个 Generic Web 网页产物、尚未归档的终态 Download Job；多网页歧义和缺失文件显式失败；
- Trafilatura 抽取失败时仍生成同一个 Reader 外壳，并明确提示原始响应位于 `source.html`；Job 仍保持 partial，不把模板成功误报为正文抽取成功；
- 链接、图片和表格继续以 Trafilatura 清洗后的真实内容为准；清洗后保留的有效栅格图片会经同一网络与格式校验边界获取并转换为 `data:` URL，重复地址只获取一次；
- 图片无法获取或格式不支持时，不保留会继续联网的图片地址，而是写入可读占位，并将 Job 标记为 partial、在 metadata/warnings 中显式记录；Reader 不克隆原网页脚本、广告、视频、原站 CSS 或浏览器运行状态，因此它是“清洗正文的单文件离线阅读页”，不是完整网页镜像；
- 当前不接 Monolith / SingleFile / ArchiveBox，不追求任意动态网页的自包含浏览器级镜像；
- 单个 HTTP 响应仍有真实获取字节上限，超出时显式失败，不截成看似完整的资源。

单文件 Reader 的图片内嵌使用现有 Python 网络边界和标准库 Base64，不引入 Monolith、浏览器运行时或新的第三方依赖。

## 7. `resource_id` 与 Job

`resource_id` 只在当前 MCP 进程内有效：

```text
resource_id -> 当前 Search / Import / JobRead 得到的资源对象
```

稳定资源身份仍是 URL、平台原生稳定 ID 等。句柄失效时优先按已知 URL/平台 ID 重定位同一资源，不重跑整个研究任务。

Download 和 Expand 是真实长任务，因此 `job_id` 持久：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/<job_id>/
  request.json
  job.json
  worker.log
  cancel.flag        # 取消后才出现
  results.jsonl      # Expand 才出现
  ...下载产物
```

这不是 durable workflow；没有 Flow、Selection、Plan、Outcome、checkpoint、resume token 或执行绑定状态机。

## 8. Search / Expand / Inspect / Download / Archive

Inspect 只在未知事实会改变推荐、选择或获取决策时使用，不是固定步骤。

资源与最终文件不是一一对应：

```text
1 Resource -> 0..N Files
```

Resource 是用户选择的逻辑对象；Representation 是 Inspect 确认的当前可获取形态/组成事实；File 是 Provider 真正产生的交付物。`primary` Representation 用来确定 exact Provider / acquisition route，`attachment` / `companion` 等可以描述同一逻辑资源自然附带的其他文件。这里不新增 Component/Bundle 持久状态。

`preferred_container="original"` 表示按资源自身的自然交付方式获取。自然交付可以是一个文件，也可以是多个文件；Agent 不应因为 landing URL 本身是 webpage 就判断资源不可下载，也不应为了让它“可下载”自行补一个扩展名。只有用户明确要求当前真实存在的某个主表示时才指定容器；指定不存在的主格式应显式失败。

SmartEdu 课程是当前第一个明确的复合资源案例：课程 detail 可以同时确认主视频、PDF 资料和伴随音频；同一视频的 MP4/HLS/码率变体只选择一个当前主版本，而独立文档/音频保留为 attachment/companion。课程可以整体自然交付多个文件，也可以按需 Expand 为具有平台稳定 item/group 身份的文件级 Resource。子资源不持久化签名 CDN URL，Inspect/Download 每次从课程 Detail 重新定位当前表示；缺少稳定平台键的条目不伪造独立身份。Job 的 `files` / `failures` 是最终事实。

用户已明确选定普通候选并要求下载时直接：

```text
resource_download(resource_ids=[...])
```

下载内部 fresh Inspect，并路由到当前 exact Provider；失败返回真实失败，不静默切换不等价 Provider。

完整枚举统一使用 `resource_expand`，直到来源真实结束；`resource_job_read` 的分页大小只控制单次 Tool Result。**Expand 结果始终只是候选集合，不等于用户已经选择下载。**

当前 Expand 与 Download 的衔接不增加新 Tool：

- 用户只选择展开结果中的一部分 → `resource_job_read` 读取必要页，每个返回候选获得当前进程 `resource_id`，再用 `resource_download(resource_ids=[...])`；
- 用户明确选择一个完整 `succeeded` Expand Job 的全部结果 → 直接 `resource_download(expand_job_id="...")`，MCP 从该 Job 的 `results.jsonl` 恢复资源事实并提交普通多资源 Download Job；Agent 不需要为了下载全部而分页搬运每个 URL；
- Expand Job 若为 `partial` / `failed` / `cancelled`，不能通过 `expand_job_id` 把当前部分结果冒充“全部”。用户仍可明确选择已经展示的个别候选并按 `resource_id` 下载。

这只是把已选择资源的机械循环留在 MCP 后台；用户选择仍属于 Skill/Agent，不创建 Selection/Confirm 状态对象。

Archive 只移动真实下载 Job 已产生的文件；分类语义由 Agent 决定。

## 9. 当前核心目录

```text
skills/

mcp/education-resources/
└── src/education_resource_mcp/
    ├── server.py
    ├── service.py
    ├── search.py
    ├── expand.py
    ├── inspection.py
    ├── archive.py
    ├── jobs.py
    ├── job_worker.py
    ├── job_state.py
    ├── sessions.py
    ├── windows_dpapi.py
    ├── adapters/
    │   ├── expansion.py          # 仅按平台分派 Expand
    │   ├── *_expand.py           # 各平台展开协议与分页实现
    │   ├── smartedu_resource.py  # SmartEdu 纯身份/关系/文件选择事实
    │   └── smartedu_download.py  # SmartEdu 网络与文件物化
    └── acquisition/
        ├── web_fetch.py
        ├── web_materializer.py
        └── vendor/
            ├── simple.min.css
            └── SIMPLE_CSS_LICENSE.txt
```

不存在 active `mcp/session-manager/`、`session_bridge.py` 或生产路径 `web_blocks.py`。

## 10. 当前验证重点

1. 同一个 `education-resources` MCP 是否正确暴露资源与 Session Tool；
2. `resource_session_manage(action=save)` 的 public schema 是否只暴露 opaque `capture`，而不是 Cookie/Storage/Token 字段结构；
3. Session broad capture 是否仍由 MCP 筛选后只保存 canonical session；
4. Session status 返回的登录步骤是否不泄漏内部 `cookie_domains` / `storage_keys`；
5. SmartEdu 保存过 session 时公共 Search 是否仍匿名；
6. LibGen 是否始终使用 `libgen` 平台身份且不触发登录；
7. Z-Library 是否只持久化两个 canonical Cookie，并按 `AUTH_REQUIRED → Session save → 重试` 驱动搜索、检查与下载；
8. Host Web URL → Import 是否能恢复明确的平台身份；
9. Generic Web 是否同时保留原始 `source.html`、Trafilatura `content.md`，并把清洗 HTML 与正文图片放进无 CDN/JS/远程图片依赖的统一 Reader `index.html`；
10. SmartEdu 课程 Inspect 是否同时暴露主视频与自然附件/伴随内容，`original` 是否无需 Agent 猜格式即可产生多文件 Job，course Expand 的稳定子文件是否可单独 Inspect/Download；
11. JobRead 子集候选是否能得到 `resource_id`，完整 succeeded Expand Job 是否能在用户明确选择全部后直接交给现有 Download Job；
12. Expand / Download / Archive 既有行为是否未被多文件/完整枚举衔接语义破坏；
13. 真实 OpenClaw 用户链路是否能完成搜索 → 判断 → 用户选择 → 下载 → 文件，且 Expand 不会自动触发下载。

后端测试不能替代第 13 项。
