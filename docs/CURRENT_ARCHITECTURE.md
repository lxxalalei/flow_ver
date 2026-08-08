# 当前架构事实快照

> 快照日期：2026-08-08
> 分支：`codex/growth-resource-taxonomy-rework`
> Baseline commit：`bfc4a1230e08ddc07eb05027fd6cbe92b8e952f6`（`docs: add Resource Retrieval Agent system design document`）

本文是当前分支的架构事实快照，不是新的运行时契约。版本、工具和 Adapter 清单以当前
工作树中的 `mcp/education-resources/contracts/tool-catalog.json`、Schema、Python
运行时代码和上述 Git 基线为准；设计文档、历史 Skill 和旧计划不能覆盖这些机器事实。

## 1. 当前边界与版本

| 项目 | 当前事实 |
|---|---|
| 唯一用户入口 | `skills/learning-resource-flow/` |
| MCP 服务 | `mcp/education-resources/`，Python stdio MCP |
| 公共契约目录 | `mcp/education-resources/contracts/` |
| `contract_version` | `1.0.0` |
| `catalog_version` | `1.3.0` |
| MCP server name | `education-resources` |
| catalog `server_id` | `learning_resources` |
| MCP 实现版本 | `0.2.0`（`server.py` 的 MCP server metadata） |
| 公共领域工具 | 13 个 |
| 权威状态 | SQLite 中的 Flow、ResultSet、Presentation、Selection、Plan、Job、AssetBundle/BundleItem、Asset、Archive、Resolution |
| 历史实现 | `legacy/skill-pipeline-v1/`，只读迁移与回滚证据，不参与 active runtime |

当前 active 主链为：

```text
自然语言
  -> learning-resource-flow Skill
  -> education-resources stdio MCP
  -> ResourceService
  -> 搜索 Adapter / Acquisition Router / 下载器
  -> SQLite 权威状态 + 受控文件
```

业务状态链为：

```text
FlowTask -> ResultSet -> Presentation -> Selection
         -> DownloadPlan -> Job -> 内部 Acquisition Router
         -> AssetBundle(关系) -> Asset -> Archive

CandidateResource -> ResolvedResource -> Representation -> Resolution
                                      ^
                                      resource_inspect（不改写 ResultSet）
```

`session-manager` 是独立的会话/授权 MCP，不属于 education-resources 的公共 catalog。
凭据、Cookie、浏览器档案、SQLite 数据和下载资产必须留在源码工作区之外。

### 机器目录与 Schema 的一致性

当前 `tool-catalog.json` 声明 13 个工具，`server.py` 也注册 13 个工具，下面的 13 工具
表是 active runtime/catalog 口径。`contracts/schemas/tool-catalog.schema.json` 已同步
约束为 13 个唯一工具并包含 `resource_browse_creator`、`resource_inspect`，当前 catalog
可通过该 meta-schema。`resource_inspect` 是历史 catalog 兼容加法；0022 的 AssetBundle 字段
是当前 `1.3.0` 的可选输出兼容加法；公共 `contract_version` 仍为 `1.0.0`。

### 0018 私有检索归一化层

0018 在 `mcp/education-resources/src/education_resource_mcp/retrieval/` 增加内部检索模型，
它们不是 MCP 公共 Schema，也不是可由模型提交的权威 ID：

| 内部类型 | 用途 |
|---|---|
| `CandidateResourceInternal` | Adapter 候选进入公共投影前的归一化载体 |
| `ResourceIdentity` | 保存逻辑资源的身份证据；不等同于公共 `resource_id` |
| `Representation` | 表示同一资源的可获取或可展示形态 |
| `ResolvedResource` | 身份和候选元数据完成内部解析后的资源对象 |

0019 在上述私有层之上增加独立 Resolution：Candidate 是 ResultSet 中的待审查候选，
ResolvedResource 是一次检查后可比较的服务内部资源对象，Representation 是其受控的
网页/文档/媒体表示，Resolution 是带 `resolution_id`、检查元数据、可用性和失败摘要的
持久化结果。Resolution 不回写不可变 ResultSet，也不改变 Presentation/Selection 绑定。

`resource_inspect` 的输入固定为 `contract_version`、`flow_id`、`resource_id` 和
`idempotency_key`。服务端按 Flow ownership 重新读取资源来源；模型不得提交 URL、路径、
批量 ID、检查深度或凭据。成功输出只返回 `resolution_id`、`resolution_status`、受控
`resolved_resource`、Representation 元数据和 failures，不返回 locator、文件字节或本地路径。

Resolution 的幂等 scope 为 `resource_inspect:{flow_id}`。缓存键为
`resource_id + profile_version(inspect-v1) + source_fingerprint`；`resolved` 与 `partial`
可跨新幂等键命中，`unresolved` 保留用于审计/恢复但不会成为新键的缓存命中。`flow_status`
通过 `current_resolutions` 返回当前 ResultSet 范围内的安全摘要。

身份解析按以下优先级工作：

```text
native ID -> ISBN -> DOI -> platform-aware canonical URL -> weak fingerprint
```

弱指纹只使用标题、创作者和版本/版次等有限字段。URL 默认只去除 fragment；只有平台
Registry 的 identity profile 明确声明的查询参数才会移除，不能用全局启发式改写来源。
`resource_search` 与 `resource_browse_creator` 在服务层共用同一套规范化和 dedup 流程，
先完成身份合并、丰富字段和 `limit` 截断，再为每个保留候选生成服务端随机的公共
`resource_id`。Adapter 提供的 ID、URL 或身份字段都不能直接成为公共权威 ID。

## 2. 公共工具表

工具均由 education-resources MCP 公开；平台 Adapter 不单独暴露为 MCP 工具。
`幂等` 表示 catalog 中的 `idempotency_required`，`Flow` 表示是否要求调用方提交
`flow_id`。

| # | 工具 | 副作用 | Flow | 幂等 | 职责 |
|---:|---|---|:---:|:---:|---|
| 1 | `resource_flow_start` | `state_write` | 否 | 是 | 创建服务端拥有的 FlowTask |
| 2 | `resource_flow_status` | `none` | 是 | 否 | 返回可恢复的权威 Flow 快照 |
| 3 | `resource_search` | `state_write` | 是 | 是 | 并行搜索并持久化不可变 ResultSet |
| 4 | `resource_presentation_save` | `state_write` | 是 | 是 | 保存实际展示的有序资源集合 |
| 5 | `resource_selection_save` | `state_write` | 是 | 是 | 按当前 Presentation 的位置保存用户选择 |
| 6 | `resource_download_prepare` | `state_write` | 是 | 是 | 创建绑定展示与选择的有期限 Plan，不下载 |
| 7 | `resource_download_start` | `job_control` | 是 | 是 | 消费已确认 Plan，启动异步下载 Job |
| 8 | `resource_job_status` | `none` | 是 | 否 | 查询 Job 进度、Asset/Bundle 和完整绑定 |
| 9 | `resource_job_cancel` | `job_control` | 是 | 是 | 请求取消排队或运行中的 Job |
| 10 | `resource_archive` | `archive_write` | 是 | 是 | 按 `asset_id` 归档已校验 Asset，并投影 Bundle 关系 |
| 11 | `resource_library_search` | `none` | 是 | 否 | 按受控元数据过滤已归档 Asset，并恢复 Bundle 关系 |
| 12 | `resource_browse_creator` | `state_write` | 是 | 是 | 浏览指定创作者在社交平台的内容列表 |
| 13 | `resource_inspect` | `state_write` | 是 | 是 | 有界核验一个当前 Flow 资源并保存 Resolution |

`resource_browse_creator` 是当前 active catalog 的正式工具，不是 Adapter 私有扩展。
它接收 `platform` 和 `creator_id`，当前仅对实现 `search_creator` 的 `douyin`、
`bilibili`、`zhihu`、`weibo` Adapter 提供创作者浏览能力；其他平台返回不支持或平台
不可用的结构化结果。

`resource_inspect` 一次只检查一个已存在的 Flow `resource_id`，固定使用服务端 profile
`inspect-v1`。它是有界同步检查，不是下载和归档入口；检查结果必须经过服务端存储和
幂等校验，Skill 只能把它作为候选审查/展示前的证据来源。

## 3. 资源类型与归一化

公共候选资源的 `resource_type` 由 `contracts/schemas/common.schema.json` 定义，当前枚举为：

| 机器值 | 运行时中文别名 |
|---|---|
| `article` | `网页`、`文章` |
| `book` | `图书` |
| `document` | `文档` |
| `video` | `视频` |
| `audio` | `音频` |
| `course` | `课程` |
| `dataset` | 直接使用机器值 |
| `other` | 未知或未纳入映射的类型的兜底值 |

运行时由 `ResourceService._normalise_resource_type` 统一归一化，未知值不能把任意平台
字符串带入公共契约。归档资料的 `resource_format` 是另一层物理格式枚举：`video`、
`document`、`audio`、`other`；它不等同于候选的 `resource_type`。

## 4. Active Adapter 与下载实现

### 4.1 搜索 Adapter

`MultiPlatformSearchProvider` 在进程启动时按运行时代码注册以下平台 Adapter；模块导入
失败时会跳过该 Adapter，因此“已列入注册表”不等于已经完成真实来源或授权验收。

| 平台 ID | Adapter 类 | 创作者浏览 |
|---|---|:---:|
| `bilibili` | `BilibiliSearchAdapter` | 是 |
| `douyin` | `DouyinSearchAdapter` | 是 |
| `zhihu` | `ZhihuSearchAdapter` | 是 |
| `smartedu` | `SmartEduSearchAdapter` | 否 |
| `ximalaya` | `XimalayaSearchAdapter` | 否 |
| `cctv` | `CctvSearchAdapter` | 否 |
| `yixi` | `YixiSearchAdapter` | 否 |
| `kepu` | `KepuSearchAdapter` | 否 |
| `baiduwenku` | `BaiduwenkuSearchAdapter` | 否 |
| `runoob` | `RunoobSearchAdapter` | 否 |
| `nlc` | `NlcSearchAdapter` | 否 |
| `open163` | `Open163SearchAdapter` | 否 |
| `annas-archive` | `AnnasArchiveSearchAdapter` | 否 |
| `weibo` | `WeiboSearchAdapter` | 是 |
| `wechat` | `WechatSearchAdapter` | 否 |

此外还有 `generic` 搜索路径：默认使用 `GenericWebSearchProvider`（Bing），配置了
SearXNG 且显式开启时切换为 `SearXNGSearchProvider`。generic 不是单独的社交平台
Adapter，但属于 active 搜索后端。

### 4.2 平台 Registry、Schema 与 descriptor

当前平台能力 Registry 位于 `mcp/education-resources/contracts/platforms/`：

- `platform-registry.json` 固定登记 `generic` 加 15 个内置平台，共 16 项，版本为 `1.0.0`。
- `schemas/platform-registry.schema.json` 将平台数量固定为 16，并约束能力、身份 profile、
  采集策略和认证元数据的形状。
- `retrieval/registry.py` 通过严格 loader 校验 JSON 与 Schema，并额外校验平台 ID 唯一性、
  平台级 URL 清理键集合和 inspect 能力字段一致性；加载失败不能静默降级。
- `AdapterDescriptor` 从已校验 Registry 生成冻结、递归不可变且可哈希的 descriptor。
  `generic` 与 15 个内置平台都能获得 descriptor；generic 仍是通用搜索后端，不被误写成
  一个社交平台 Adapter。
- Registry 中 16 个平台精确启用 7 个 inspect：`generic`、`bilibili`、`nlc`、
  `annas-archive`、`ximalaya`、`zhihu`、`smartedu`；其余 9 个保持关闭。未启用平台由
  精确 Inspection Router 返回结构化 `FEATURE_NOT_SUPPORTED`，不会静默回退 generic。
- Generic Inspector 使用有界 GET、逐跳 SSRF/重定向校验、1 MiB 内容上限与 MIME/魔数
  交叉验证；七个平台 Inspector 均以固定夹具测试，不代表真实平台网络或授权已验收。

平台清单和每个平台的当前能力边界见
[platform Registry 说明](../mcp/education-resources/contracts/platforms/README.md)。

### 4.3 下载与网页物化

Job runner 在 `resource_download_start` 后统一执行内部 Acquisition Router。0022 不改变
公开 `contract_version=1.0.0`、`catalog_version=1.3.0`、13 个工具、Plan digest、确认
流程或 Archive 输入；Router 负责生成临时 Artifact，服务端再把校验通过的内容持久化为
Asset，并建立可选的 AssetBundle/BundleItem 关系。

当前运行时策略分为三类：

| 策略 | 内部职责 | 当前选择边界 |
|---|---|---|
| `direct_file` | 包装平台专用 Downloader 或受控公共 HTTP 下载并校验文件 | 已确认的直接媒体/文件优先 |
| `web_materialize` | 受控静态抓取、Block IR 提取、HTML/Markdown 重建和同源资产收集 | 普通文章、古诗文、图文博客和静态网页默认 |
| `web_capture` | 受控浏览器快照 | 只有显式允许的动态页面采集；不是默认网页方式，也不是静态失败的自动 fallback |

现有平台专用 Downloader 包括：

- `ximalaya`：`XimalayaDownloader`
- `bilibili`：`BilibiliDownloader`
- `smartedu`：`SmartEduDownloader`
- `douyin`：`DouyinDownloader`
- `annas-archive`：`AnnasArchiveDownloader`

平台专用 Downloader 仍由服务端根据已确认的资源和计划选择；网页资源不再由浏览器渲染
作为默认回退。动态页面无法安全静态物化时，服务端返回结构化失败或缺口；除非用户明确
要求且存在受控 snapshot profile，不得自动进入 `web_capture`。

普通网页的物化 Job 生成受控 bundle：

```text
<job-artifact>/
├── index.html
├── content.md
├── metadata.json
├── assets/
│   └── <server-generated-safe-name>.<verified-extension>
└── webbundle.zip
```

`index.html` 和 `content.md` 只引用同一 bundle 内的相对路径；`assets/` 只接受通过策略、
MIME 和魔数校验的资源。`Artifact` 是临时采集描述，`Asset` 是持久化不可变内容；
`AssetBundle` 是一个 Job × Resource 的有序关系，不等于 ZIP。0021 的 `webbundle.zip` 在
0022 作为 singleton primary Asset 保持兼容，ZIP 内部文件不拆成公开 BundleItem；归档仍只
接受服务端产生的 `asset_id`。

所有三种策略都必须经过：

```text
HTTP(S) allowlist -> 每跳 SSRF/redirect 校验 -> 流式大小/数量限制
                  -> MIME + magic 校验 -> 可取消 Job -> validated Asset
```

不执行网页脚本，不绕过登录、验证码、付费墙、DRM 或其他访问控制；Cookie、Token、浏览器
档案、任意路径和命令不进入工具输入。平台 Adapter、Downloader 和 Acquisition Router 都是
服务内部实现，不属于 public catalog。

### 4.4 AssetBundle 关系与兼容映射

一个 Job × Resource 最多产生一个服务端 Bundle；一个可用 Bundle 必须有且只有一个
`primary`。公开角色固定为 `primary`、`subtitle`、`cover`、`metadata`、`attachment`、
`transcript`、`companion`，角色、顺序、`bundle_id` 和 `item_key` 不由模型提交，也不能按
文件名推断。失败 BundleItem 的 `asset_id` 为空，不创建零字节假 Asset。

Job `status` 仍为 `queued`、`running`、`cancelling`、`succeeded`、`failed`、`cancelled`；
`completion=complete|partial` 只表达 Bundle 完整度。只有已有可用 primary 且存在失败项时
才是 `partial`；无 primary 为 `failed`，取消为 `cancelled` 并 quarantine，不自动重放网络
副作用。

旧 `DownloadProvider` 单文件映射为 `primary`，旧有序列表首项映射为 `primary`、其余为
`attachment`；enriched batch 才可携带明确角色和逐项失败。SmartEdu 课程保留来源关系：
视频（若有）为 primary，否则首个明确内容项为 primary；PDF 为 attachment，MP3 为 companion，
显式封面才为 cover。认证、策略阻断或取消终止整项获取。

当前实现事实需要单独标注：

- `annas-archive` 的搜索 Adapter 和专用下载 Adapter 当前共用 `libgen_client`，因此是
  Libgen-backed 实现；这不等于已完成 Anna's Archive 官方来源或生产授权验收。
- `wechat` 的搜索 Adapter 当前通过 Sogou Weixin 页面（`weixin.sogou.com`）获取结果，
  不是直接调用微信官方搜索接口。

## 5. 实现边界

- Skill 负责需求理解、必要澄清、搜索方向、候选审查、实际展示、用户确认和结果解释；
  不负责拼接命令、路径、下载 URL 或伪造业务状态。
- MCP 服务端拥有 Flow、Selection、Plan、Job、Asset、AssetBundle/BundleItem、Archive 和 Resolution 的权威状态；模型不能
  手工生成稳定 ID、展示位置、摘要、确认结果或归档结果。
- 有副作用的工具使用服务端幂等键，并重新校验 Flow、Presentation、Selection、Plan、
  来源、权限和资源状态。
- `resource_archive` 只接受服务端产生的 `asset_id` 与所属 Job，不接受本地路径、任意
  URL、Bundle 关系或文件字节；Archive 仍是 Asset-scoped。
- 网络来源只允许受策略控制的 `http`/`https`；服务端执行 SSRF、重定向、大小上限、
  内容类型和真实文件格式校验。
- 大文件和二进制不进入 Tool JSON 或模型上下文；只返回稳定 ID、元数据和受控引用。
- stdio 是进程边界，不是安全沙箱；当前实现是单机开发 MVP，不代表多租户生产隔离。
- `legacy/skill-pipeline-v1/` 只保留历史证据，active MCP 不得在运行时导入 legacy。

## 6. 验证状态与剩余风险

### 已完成的本次静态核对

- 已确认实施 branch 与 baseline commit；0017–0023 的各子 Agent 与根智能体交付均已通过
  定向、全量本地回归和进程级 E2E 统一验收，发布状态以 Git 历史为准。
- 已解析当前 `tool-catalog.json`：`contract_version=1.0.0`、`catalog_version=1.3.0`、
  13 个工具。
- 已对照 `server.py` 的 `@server.tool` 注册：运行时包含同一组 13 个工具，含
  `resource_browse_creator` 和 `resource_inspect`。
- 已对照搜索 Adapter 注册表、创作者浏览方法和平台下载器注册代码，形成本文第 4 节清单。
- 已修复 `resource_browse_creator` 的 `search_run_id`、相对 `$ref`、平台运行记录形状和
  独立幂等范围，并补充真实服务输出契约测试。
- 0017 已在隔离 Python 环境运行契约、创作者浏览、搜索、服务和控制面相关测试 29 项，
  全部通过。
- 0018 已在隔离 Python 环境运行 Identity、Dedup、Registry、Adapter descriptor、Search、
  Browse、Service、Contract 和 Control Plane 相关测试 104 项，全部通过；Registry JSON
  Schema、`compileall`、16 项平台能力表一致性和本轮 22 条本地 Markdown 链接检查通过。
- 0019 根验收合并测试 109/109 通过；0020 Adaptive Retrieval 完成后，education-resources
  本地 MCP 回归 279/279 通过，同时通过源码编译、Schema、33 条本地 Markdown 链接与差异检查。
- 0021 完成 Acquisition Core、逐跳 Web Fetch、Block IR/Web Materializer、服务/Job/Archive
  接入后，定向获取与安全测试 38/38、服务与控制面回归 40/40、education-resources 全量本地
  回归 317/317 通过；源码与测试 `compileall` 通过。这些是本地固定夹具结果，不等于真实
  平台网络或 OpenClaw E2E 验收。
- 0022 已完成 catalog 1.3.0 可选 Bundle 输出、migration 5、服务层多资产接入、SmartEdu/
  旧 Provider、Archive/Library Bundle 关系、取消 quarantine 和重启终结语义；根智能体的
  education-resources 全量本地固定夹具回归 348/348 通过，契约 Bundle 检查 3/3、16 个
  JSON Schema 校验通过。
- 0023 已完成当前机器可执行的进程级 E2E：4/4 原始 JSON-RPC stdio 场景通过，覆盖 13 工具
  发现、多资源 partial Bundle、网页 ZIP、Archive/Library、AUTH_REQUIRED 后新 Job 恢复，
  以及下载中强杀 MCP 后同 SQLite 重启终结且不自动重放；全量本地回归为 352/352。

### 尚未完成或超出本次范围

- 当前仍未运行真实平台网络测试或 OpenClaw doctor/probe；当前 macOS 未发现 `openclaw`
  命令，不能把固定夹具结果或历史 WSL 结果当成当前实时验收。
- 真实杀进程恢复已由本地 stdio E2E 验收；真实平台网络与 OpenClaw doctor/probe 仍需外部
  运行环境，本地回归不能替代它们。
- Adapter 已注册只表示代码接入，不代表对应平台的授权、条款、登录状态、反爬限制和
  生产可用性已经通过验收。
- 本快照不代表真实平台网络、合法生产会话、OpenClaw E2E 或多租户生产隔离已就绪。

相关入口：

- [工作区 README](../README.md)
- [工具说明](../TOOLS.md)
- [开发路线](DEVELOPMENT_PLAN.md)
- [采集策略与网页物化](../skills/learning-resource-flow/references/acquisition-strategy.md)
- [education-resources contracts 目录](../mcp/education-resources/contracts/README.md)
