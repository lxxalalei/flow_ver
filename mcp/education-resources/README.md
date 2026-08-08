# Education Resources MCP

本目录是教育资源工作区唯一的执行与权威状态服务。当前 Python stdio MCP 已运行
`contracts/` 的 `1.0.0` 控制面，当前 catalog 为 `1.3.0`，并且公共 catalog **暴露 13 个工具**。

教育资源主链当前只保留 `contracts/` 的 `1.0.0` 契约；历史教育资源 v1 已从工作区移除，迁移差异
仅保留在 `contracts/compatibility.md` 和 Git 历史中。`learning-v1` 仅是当前学习资料分类注册表的版本，
不是 MCP 协议版本。

权威状态链为：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job
                                                    -> AssetBundle(关系) -> Asset -> Archive

CandidateResource -> ResolvedResource -> Representation -> Resolution
                                      ^
                                      resource_inspect
```

搜索结果与模型实际展示集合严格分离。Skill 负责语义判断、候选审查和实际展示；MCP 负责所有权威状态、副作用、
幂等和安全校验。

0018 的检索归一化属于 MCP 内部实现：它先把各 Adapter 候选转换为私有模型并完成身份解析、合并和去重，
再投影为公共 ResultSet。0019 在此基础上增加独立 Resolution 层：Candidate、ResolvedResource、
Representation 和 Resolution 分别承担候选快照、解析资源、受控表示和一次检查的持久化结果。
公共 `contract_version=1.0.0` 不变，catalog 当前为 `1.3.0`，仍然只有 13 个工具。1.3.0
只追加已有工具输出中的可选 AssetBundle 字段，不新增 Bundle Tool。

平台登录、Cookie、Token、浏览器会话捕获与本地会话保存由独立 `session-manager` 负责，不属于
education-resources 的 13 工具 catalog。education-resources 不向模型暴露登录秘密。

## 目录

```text
contracts/                  # 当前运行的控制面契约
src/education_resource_mcp/
├── adapters/                  # MCP 内部平台 Adapter
├── retrieval/                 # 私有候选、身份解析、去重和平台 Registry loader
├── acquisition/               # 0021 内部获取策略、Router 与网页物化
├── server.py                  # stdio MCP 入口
├── service.py                 # 领域服务
├── storage.py                 # SQLite 权威状态
├── jobs.py                    # 异步任务
├── downloader.py              # 受控 HTTP(S) 下载
└── policy.py                  # 网络与路径安全
tests/                         # 单元、契约、安全和 stdio 测试
```

## 本地安装

使用独立虚拟环境，不要安装到系统 Python：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

当前 WSL 开发环境使用：

```text
/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv
```

## 启动

```bash
EDUCATION_RESOURCE_MCP_DATA_DIR=/absolute/path/to/data \
EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR=/absolute/path/to/session-manager-data \
EDUCATION_RESOURCE_MCP_SEARXNG_URL=http://127.0.0.1:8888 \
  .venv/bin/education-resource-mcp
```

stdio 的 stdout 只用于 MCP 协议。诊断日志应写入 stderr，业务文件只写入配置的数据目录。

`EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR` 指向独立 `session-manager` 的数据目录。设置后，
education-resources 会通过 `openclaw-session-manager` 包只读消费同一份安全凭据（Windows 下包括当前用户 DPAPI），
不会维护第二份 Cookie/Token。显式设置该目录但运行环境未安装 `openclaw-session-manager` 时，MCP 会启动失败而不是静默读取空的旧存储。

未设置 `EDUCATION_RESOURCE_MCP_DATA_DIR` 时，默认使用：

```text
~/.local/share/quanxiao/education-resource-mcp-data
```

## 公共工具

暴露以下 13 个工具：

1. `resource_flow_start`
2. `resource_flow_status`
3. `resource_search`
4. `resource_presentation_save`
5. `resource_selection_save`
6. `resource_download_prepare`
7. `resource_download_start`
8. `resource_job_status`
9. `resource_job_cancel`
10. `resource_archive`
11. `resource_library_search`
12. `resource_browse_creator`
13. `resource_inspect`

主流程为：

```text
resource_flow_start
-> resource_search 或 resource_browse_creator（提交 task_version，产生待审查 ResultSet）
-> resource_inspect（可选：对当前 Flow 的高潜 resource_id 做有界核验，保存 Resolution）
-> 模型实际展示审查后的 ResultSet 子集
-> resource_presentation_save（允许保存空 Presentation）
-> 用户选择
-> resource_selection_save（只提交当前 Presentation positions）
-> resource_download_prepare（完整绑定 Presentation/Selection，返回 plan_digest）
-> 用户明确确认
-> resource_download_start（提交完整绑定和 plan_digest）
-> resource_job_status / resource_job_cancel
-> resource_archive
-> resource_library_search
```

### 创作者主页浏览：`resource_browse_creator`

该工具用于按创作者主页浏览内容列表，不是关键词搜索，也不直接生成 Presentation。它在当前 Flow 中创建一个新的
服务端 ResultSet，后续仍必须由 Skill 审查实际候选，再调用 `resource_presentation_save` 记录真实展示集合。

输入边界由 `contracts/schemas/tools/resource_browse_creator.schema.json` 固定：`contract_version` 必须为 `1.0.0`，
必须提交当前 `flow_id`、当前 `task_version`、幂等键、`platform` 和平台语义下的 `creator_id`；`creator_id` 为
1--512 字符，`limit` 可选且范围为 1--50，默认 50。输入对象禁止额外字段；调用方不得传入 Cookie、Token、本地路径、
脚本、命令或下载 URL 来替代这些字段。

成功结果与 `resource_search` 共享 ResultSet 语义，固定处于 `stage = reviewing`，包含 `search_run_id`、`result_set_id`、
`result_version`、`platform_runs`、`candidates`、`failures`、`has_more` 和 `created_at`。候选只是待审查资源，不等于
用户已经看到或选择的资源；只有 `resource_presentation_save` 保存的有序子集才能进入 Selection。服务端会规范化候选的
HTTP(S) 来源、过滤空标题，使用私有 retrieval 层按身份去重，并在去重后的保留候选上生成服务端随机 `resource_id`。

`resource_search` 与 `resource_browse_creator` 共用同一套 dedup 规则。身份优先级为：

```text
native ID -> ISBN -> DOI -> platform-aware canonical URL -> weak fingerprint
```

候选内部使用 `CandidateResourceInternal`、`ResourceIdentity`、`Representation` 和
`ResolvedResource`；这些类型不进入公共工具输入，也不能由模型伪造。URL 默认只去除 fragment，
平台特定查询参数必须由 Registry identity profile 显式列出。

当前内置实现只对实现 `search_creator` 的社交平台提供创作者浏览：`bilibili`、`douyin`、`zhihu`、`weibo`。教育或
资料平台即使支持普通 `resource_search`，也不因此支持创作者主页浏览；这类调用返回无伪造候选的结构化
`FEATURE_NOT_SUPPORTED` 失败记录。未知平台返回 `UNKNOWN_PLATFORM` 失败记录；认证不足、平台不可用等情况同样记录在
ResultSet 的平台运行和失败信息中，不绕过登录或访问控制。

### 资源核验：`resource_inspect`

该工具只接受以下四个输入字段：`contract_version`、`flow_id`、`resource_id`、
`idempotency_key`。它不接受 URL、路径、批量资源 ID、检查深度、Cookie、Token 或其他凭据；
服务端从当前 Flow 重新取得候选来源并执行策略校验。调用一次只处理一个资源，固定服务端 profile
`inspect-v1`，不使用下载 `jobs` 表。

输出按 Candidate/ResolvedResource/Representation/Resolution 分层，返回
`resolution_id`、`resolution_status`（`resolved`、`partial` 或 `unresolved`）、受控资源元数据、
可比较的 Representation 元数据和结构化 failures。Representation 只含服务端生成的
`representation_id`、类型、MIME、大小估计、授权提示等元数据，不返回 locator、文件字节、本地路径或
凭据。Inspect 不下载、不启动 Job、也不归档。

Resolution 幂等 scope 为 `resource_inspect:{flow_id}`。`resource_id + source_fingerprint +
inspect-v1` 的 `resolved`/`partial` 结果可缓存；`unresolved` 会保留以便审计和恢复，但新幂等键会重新检查。
成功缓存命中会在 inspection 元数据中标注 `cache_status=hit`。`resource_flow_status` 通过
`current_resolutions` 返回当前 ResultSet 范围内的安全摘要。

### 平台 Registry 与实现边界（0019）

当前 Registry/Schema/严格 loader 固定登记 `generic` 加 15 个内置平台，共 16 项；其中
`generic`、`bilibili`、`nlc`、`annas-archive`、`ximalaya`、`zhihu`、`smartedu` 七个条目
启用 `inspect`，其余九个保持关闭。每个条目都会生成冻结、递归不可变且可哈希的
`AdapterDescriptor`，其中 `generic` 是通用搜索后端的 descriptor，不是额外的社交平台 Adapter。
详细平台清单见 [platform Registry 说明](contracts/platforms/README.md)。

`annas-archive` 当前搜索和下载实现共用 Libgen client，是 Libgen-backed；`wechat` 当前通过
Sogou Weixin 页面搜索，不是微信官方搜索 API。专用下载器只对应明确的 platform-specific
acquisition strategy。网页获取在 0021 由内部 Acquisition Router 统一分流，不新增平台级
MCP 工具。

### 0021–0022 Acquisition Router、Web Materializer 与 AssetBundle

0022 保持公开 `contract_version=1.0.0`、`catalog_version=1.3.0` 和 13 个工具不变。
`resource_download_prepare -> 用户明确确认 -> resource_download_start` 的确认流程、Plan
digest、Job 生命周期和 Archive 输入不变；新增内容是服务端在 Job 结果上的 Bundle 关系投影。
Job `status` 不含 `partial`，`completion=complete|partial` 只表达已有 primary 时的结果完整度。

Router 只使用三种内部策略：

| 策略 | 作用 | 选择规则 |
|---|---|---|
| `direct_file` | 包装既有平台/公共下载器并产出已校验文件 | 已确认的文件、视频、音频、图书等直接媒体优先 |
| `web_materialize` | 静态抓取、Block IR 提取、重建安全 HTML/Markdown 并收集受控资产 | 普通文章、古诗文、图文博客和静态网页默认使用 |
| `web_capture` | 受控浏览器快照 | 仅用户明确要求且服务端显式允许；不是默认网页方式，也不是静态失败的自动 fallback |

网页 bundle 的受控布局为：

```text
index.html
content.md
metadata.json
assets/
webbundle.zip
```

HTML 和 Markdown 只引用 bundle 内的相对路径；资源名称、MIME、魔数和内容大小由服务端
验证。`Artifact` 只是 Acquisition 的临时文件描述；`Asset` 是服务端校验后持久化的不可变
内容。`AssetBundle` 是一个 Job × Resource 的有序关系，不是 ZIP 或目录；`BundleItem` 关联
成功 Asset 或没有 Asset 的失败事实。一个可用 Bundle 必须有且只有一个 `primary`，公开角色
固定为 `primary`、`subtitle`、`cover`、`metadata`、`attachment`、`transcript`、`companion`。

0021 的 `webbundle.zip` 在 0022 作为 singleton primary Asset 保持兼容，ZIP 内部文件不拆成
公开 BundleItem。服务端只能从来源事实赋予角色、顺序、`bundle_id` 和 `item_key`，不得由模型
或文件名推断；失败项不创建零字节假 Asset。

保留旧 `DownloadProvider` 映射：旧单文件为 `primary`，旧有序列表首项为 `primary`、其余
为 `attachment`；新 enriched batch 才能携带明确角色和逐项 failure。SmartEdu 课程保留来源
关系：视频（若有）为 `primary`，否则取首个明确内容项；PDF 为 `attachment`，MP3 为
`companion`，显式封面才为 `cover`。认证、策略阻断或取消终止整项获取，不能伪装成 partial。

所有获取策略均执行 HTTP(S) 限制、逐跳 SSRF 和 redirect 校验、流式大小/数量/bundle 上限、
MIME 与魔数交叉验证、取消传播和不完整产物清理；不执行网页脚本，不绕过认证、验证码、
付费墙、DRM 或其他访问控制。需要认证时返回结构化 `AUTH_REQUIRED`/等价状态，由独立
`session-manager` 合法完成登录；Cookie、Token、浏览器档案、路径和命令不进入工具输入。

取消会 quarantine 未完成 Job/Bundle/Asset；进程重启会把中断任务终结为 `failed` 或
`cancelled`，不自动重放网络副作用。Archive 仍是 asset-scoped，任何 ready BundleItem 可用
其服务端 `asset_id` 独立归档；Library 仍按 Asset 返回，并通过可选的 `bundle_id`、`role`、
`order`、`bundle_completion` 恢复关系。

`resource_flow_status` 可在任意恢复点调用，返回：

```text
current_result_set
current_presentation
current_selection
current_plan
current_job
current_resolutions
```

它不会返回 confirmation token/hash、Cookie、Token、数据库路径、临时目录、下载路径或归档本地路径。

完整不变量见 `contracts/domain-contract.md`；历史迁移差异见
`contracts/compatibility.md`；精确工具集合见 `contracts/tool-catalog.json`。

## 学习资料库归档

归档链路只处理学习资料：

```text
ready Asset
-> pending Archive
-> 受控临时文件与内容校验
-> 学习资料库原子落盘
-> ready SQLite 索引
-> resource_library_search
```

### learning-v1 分类

分类注册表以 [`contracts/taxonomy/learning-v1.json`](contracts/taxonomy/learning-v1.json)
为机器单一来源。一级领域 ID 固定为：

| 机器 ID | 中文目录 |
|---|---|
| `chinese_language` | `01-语文与中文` |
| `mathematics_reasoning` | `02-数学与思维` |
| `english_foreign_languages` | `03-英语与外语` |
| `natural_science` | `04-自然科学` |
| `humanities_social_studies` | `05-人文与社会` |
| `information_technology` | `06-信息科技` |
| `arts_aesthetics` | `07-艺术与审美` |
| `physical_health` | `08-体育与健康` |
| `learning_skills` | `09-学习方法与通用能力` |
| `interdisciplinary_practice` | `10-综合实践与跨学科` |

`亲子陪伴` 和 `待分类` 都不是领域。新归档在 metadata 中写入：

```json
{
  "classification": {
    "taxonomy_version": "learning-v1",
    "classification_status": "classified",
    "primary_domain": "natural_science",
    "secondary_domains": [],
    "topics": ["天文与宇宙"],
    "material_purposes": ["explanation"],
    "grade_levels": ["小学"],
    "difficulty": "introductory",
    "curriculum_versions": []
  },
  "collection": "太阳系专题",
  "tags": ["科普"],
  "notes": ""
}
```

分类状态为 `classified`、`needs_review` 或 `unclassified`。主领域只有一个，次领域只能从
注册表选择且不能与主领域重复；主题是清洗、去重和限长的受控自由文本。学段、难度和
教材版本只有存在证据时填写。旧平铺 `primary_domain`、`topics`、`source_name` 和旧中文
领域作为 deprecated 输入兼容；无法可靠映射时保留原始元数据并进入 `needs_review`。

### 目录、权威字段与内容去重

标准物理结构为：

```text
学习资料库/<固定中文领域目录>/<主主题>/<视频|图文|音频|其他>/<文件>
```

`needs_review` 和 `unclassified` 使用 `学习资料库/99-待分类/其他/<格式>/`。格式目录由
服务端依据已经验证的媒体类型和扩展名决定，未知格式进入 `其他`。默认文件名为
`[来源]-[标题].[扩展名]`；来源、标题、媒体类型、大小和 SHA-256 来自 Resource/Asset
权威字段，不信任模型提供的来源事实，也不接受客户端本地路径。

内容身份使用 SHA-256、文件大小及必要时媒体类型。不同 Asset 指向同一内容时不重复复制，
但保留每个 Asset 的可追溯归档关系并返回 `deduplicated`。同名不同内容追加稳定短哈希，
不覆盖既有文件。

### SQLite、迁移与恢复

SQLite 通过 `schema_migrations` 使用幂等前向迁移，当前 schema 包含迁移 5：迁移 1 保留既有控制面
列，迁移 2 建立学习资料归档基础，迁移 3 建立独立的 `resource_resolutions` 表，迁移 4
补充可恢复的检索轮次、provenance、coverage 与私有 identity 字段，迁移 5 建立
`asset_bundles`、`asset_bundle_items`、`asset_bundle_failures` 并按历史 `jobs.asset_ids_json`
回填 singleton Bundle。这里的迁移版本是存储 Schema 版本，不是公共 MCP 契约版本。旧数据库首次打开时保留现有 Flow、Resource、Job、
Asset、Archive、幂等键和审计记录；旧归档元数据被规范化并建立结构化索引，无法映射的
分类进入 `needs_review`，迁移不移动或批量重命名现有资料文件。

`archive_contents` 按 SHA-256 与文件大小唯一标识物理内容，保存已验证媒体类型、资源格式、
安全相对路径、受控临时相对路径以及 `pending`、`ready`、`failed`、`missing`、`corrupt`
状态。`archive_entries` 保留旧列并增加内容关联、归档状态、分类标量、归档/更新时间和错误；
次领域、主题、资料用途、学段、教材版本和标签分别进入关联表，供精确过滤和索引使用。

归档使用 `pending -> ready` 提交协议：建立待提交索引、写受控临时文件、复核大小和
SHA-256、原子移动，再提交 ready 状态。失败不会产生可检索的 ready 记录；内部对账可重试
遗留 pending，并把索引缺文件标记为 `missing`、内容校验异常标记为 `corrupt`。公共检索只
返回 Archive 与内容均为 ready 且文件存在的记录。

### Library Search

`resource_library_search` 支持 `query`、`taxonomy_versions`、`classification_statuses`、
`primary_domains`、`secondary_domains`、`topics`、`material_purposes`、`grade_levels`、
`difficulties`、`curriculum_versions`、`platforms`、`resource_types`、`resource_formats`、
`collections`、`tags`、`archived_after` 和 `archived_before`。单个字段的多个值采用 OR，
不同字段之间采用 AND；结构化字段精确匹配，关键词仅对标题、主题、标签和备注做受控
模糊匹配。

结果稳定按 `archived_at DESC, archive_id DESC` 排序。`limit` 控制页大小；有下一页时
返回 `has_more=true` 和不可解析、不可修改的签名 `next_cursor`。输出包含 `classification`、
`primary_domain_display_name` 和 `学习资料库/` 内的安全 `relative_path`。deprecated
`library_path` 如仍作为兼容字段出现，也只能是同一安全相对路径；不返回数据库路径、任务目录
或绝对路径。

## 搜索、下载和登录边界

当前 Generic 和平台搜索 Adapter 已内聚到 MCP 包，不依赖 `legacy/`。下载与网页物化只允许
通过服务端策略校验的 HTTP(S) 来源，并强制执行逐跳 SSRF/重定向、大小、数量、内容类型、
真实文件格式和取消校验。网页默认走静态 `web_materialize`；`web_capture` 不是默认 fallback。

需要认证的平台返回 `AUTH_REQUIRED` 后，应暂停资源状态转换，调用独立 `session-manager` 完成合法登录与会话保存，
再通过 `resource_flow_status` 恢复当前 Flow。不得把 Cookie 或 Token 作为 education-resources 工具参数传递。

## 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p 'test_e2e_*.py' -v
```

通过 OpenClaw 验证：

```bash
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

成功条件是 doctor 报告 `ok`，probe 精确发现 13 个工具且 `diagnostics=[]`。0020 的本地
education-resources 回归、Schema、编译和 Markdown 检查已由根智能体记录；0021 获取实现曾
通过 317/317 的本地固定夹具回归。0022 已完成 catalog 1.3.0、migration 5、服务层多资产
接入、SmartEdu/旧 Provider、取消/重启状态和 Archive/Library 关系验收；契约 Bundle 检查
3/3、16 个 JSON Schema 校验及 education-resources 全量本地回归 348/348 通过。

0023 新增的 4 个进程级 E2E 使用原始换行 JSON-RPC 启动真实 MCP stdio 子进程，而不是
直接调用 Service：覆盖 13 工具发现、多资源 Inspect/确认/partial Bundle、网页 ZIP、逐 Asset
归档与 Library、AUTH_REQUIRED 后由外部会话恢复，以及下载中强杀进程后同 SQLite 重启。
4/4 E2E 和包含它们的全量本地回归 352/352 通过；测试服务器与无秘密认证 marker 只位于
`tests/` 和临时数据目录，生产入口没有 fixture mode。

本仓库当前没有把真实平台网络、合法生产会话、OpenClaw doctor/probe 或多租户生产隔离
当作本阶段已验收事实；固定夹具结果也不能替代这些验收。
