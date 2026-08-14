# 当前架构

> 快照日期：2026-08-14  
> 目标：只描述当前 active 运行事实。历史设计、已废弃 authority/readiness 链和被替代的并发方案请查 `.agent/plans/archive/`。

## 1. Active 边界

| 项目 | 当前事实 |
| --- | --- |
| 用户入口 | `skills/learning-resource-flow/` |
| MCP | `mcp/education-resources/`（Python stdio） |
| MCP metadata | `0.2.0` |
| 公共契约 | `contract_version=1.0.0` |
| Tool catalog | `catalog_version=1.7.0`，14 个领域 Tool |
| 平台 Registry | 17 个 active platform ID；描述搜索/Inspect/宽 acquisition 能力，不是 exact Provider 路由表 |
| 分类 | `contracts/taxonomy/learning-v1.json` |
| SQLite | migration 9 |
| 获取服务 | `service.py` → `ResourceService` |
| 获取存储 | `storage.py` → `Store` |
| 获取规划 | `acquisition/planner.py` → `AcquisitionPlanner` |
| Provider 路由 | exact `(provider_id, provider_version)`；失败不 silent fallback |

## 2. 总体职责

```text
用户
  ↓
learning-resource-flow Skill
  │  负责语义研究与决策：
  │  需求理解 / 必要澄清 / 搜索角度 / 来源选择 / query / 候选判断 / 补搜决策
  ↓
education-resources MCP
  │  负责业务事实、状态和副作用：
  │  Flow / ResultSet / Presentation / Selection / Resolution / Representation
  │  Plan / Job / Outcome / Asset / Archive
  ↓
Search Adapter / Inspector / exact Provider
```

核心原则：**模型不以 MCP 状态机作为思考模型。** Skill 先判断用户真正需要什么资源；MCP 负责保存事实、校验状态并执行受控副作用。

## 3. 用户主链

```text
自然语言需求
  ↓
Need reconstruction
  ↓
形成 1–3 个真正互补的搜索角度
  ↓
按内容/证据需求选择来源并生成 source-native query
  ↓
resource_search
  ↓
判断真实候选是否有用
  ├─ 事实不足且会改变决策 → selective resource_inspect
  ├─ 有明确缺口且存在更好的下一路线 → 补搜
  └─ 已足够 → 展示候选
        ↓
resource_presentation_save
        ↓
用户选择
        ↓
resource_selection_save
        ↓
必要时 fresh Inspect
        ↓
resource_download_prepare
        ↓
向用户展示实际 Plan
        ↓
用户明确确认
        ↓
resource_download_start
        ↓
Job / Outcome / Asset
        ↓
可选 Archive
```

“缺口”“继续搜索”“停止并展示”仍然是模型判断，但不再要求用 `SemanticReview -> Gap -> StopDecision` 这种形式化状态机表达。

## 4. 业务状态

```text
FlowTask
  -> ResultSet
  -> Presentation
  -> Selection
  -> Resolution / Representation
  -> Plan / PlanItem
  -> Job / JobItem
  -> Outcome
  -> AssetBundle / Asset
  -> Archive
```

这些对象是 MCP 的业务事实，不是 Agent 必须逐层模拟的思考步骤。

关键边界：

- ResultSet 是搜索事实集合；Presentation 是实际展示给用户的有序子集。
- 用户序号选择绑定 Presentation，不直接绑定整个 ResultSet。
- Inspect 负责把候选线索核验成 Resolution/Representation 事实。
- Plan 固定 exact Provider 路线；Start 重新核验当前资源事实。
- Archive 只接受服务端 ready `asset_id`。

## 5. Search 与 Inspect

### Search

MCP Search 负责：

- 调用指定平台 Search Adapter；
- 返回真实 Candidate/ResultSet；
- 多轮搜索时保持服务端 ResultSet 事实；
- 去重和平台事实不由模型伪造。

Skill/Main Agent 负责：

- 从目标形成搜索角度；
- 判断什么来源能提供独特价值；
- 生成适合该来源的 query；
- 根据真实结果决定推荐、Inspect、补搜或停止。

### Inspect

Inspect 只在事实会改变推荐或获取决策时使用，例如：

- 是否为真实 primary resource，而非 landing page；
- 文件/媒体格式；
- 是否公开可访问、需要认证或不可用；
- Prepare 前需要 fresh Resolution/Representation。

不为了“流程完整”检查全部候选。

## 6. Platform Registry 与 exact acquisition route 是两层事实

`contracts/platforms/platform-registry.json` 是平台能力目录，描述：

- platform ID；
- Search / Browse Creator / Inspect / Acquire 是否存在；
- 登录形态；
- 宽 acquisition 类型，例如 `webpage`、`platform_video`、`platform_audio`。

它**不是** exact 下载执行路由表。

真正的获取执行路线由两处共同决定：

1. `acquisition/planner.py` 的 `ProviderSpec`：根据当前 `platform + scope + Representation + role/container/resource_type` 选择 exact Provider；
2. `service.py` 的 Provider registrations：声明当前进程实际部署了哪些 `(provider_id, provider_version)`。

因此，类似 Shuge 的实际路线：

```text
platform-registry: shuge 可 Search / Inspect / Acquire

实际候选:
shuge / document / primary_resource
  ↓
AcquisitionPlanner ProviderSpec
  ↓
direct_file
  ↓
generic-direct@1.0.0
```

不需要为了使用 `generic-direct` 再创建 `ShugeDownloader`，也不要求 Platform Registry 复制 Planner 的 exact strategy/provider 事实。

## 7. 当前 ProviderSpec 路线

| Platform / Representation | Scope | Strategy | exact Provider |
| --- | --- | --- | --- |
| SmartEdu document (PDF) | primary_resource | direct_file | `smartedu-resource@1.0.0` |
| SmartEdu video (MP4) | primary_resource | direct_file | `smartedu-resource@1.0.0` |
| SmartEdu audio (MP3/M4A) | primary_resource | direct_file | `smartedu-resource@1.0.0` |
| Douyin video (MP4) | primary_resource | direct_file | `douyin-video@1.0.0` |
| Ximalaya audio (MP3/M4A) | primary_resource | direct_file | `ximalaya-audio@1.0.0` |
| Bilibili video (MP4) | primary_resource | direct_file | `bilibili-video@1.0.0` |
| Anna's Archive document | primary_resource | direct_file | `annas-archive@1.0.0` |
| Shuge document | primary_resource | direct_file | `generic-direct@1.0.0` |
| Generic document | primary_resource | direct_file | `generic-direct@1.0.0` |
| Generic MP4 video | primary_resource | direct_file | `generic-direct@1.0.0` |
| Generic webpage正文 | primary_resource | web_materialize | `generic-web-materializer@1.0.0` |
| Generic landing webpage | landing_page | web_materialize | `generic-web-materializer@1.0.0` |

ProviderSpec 存在不等于平台已经通过真实用户验收。production-ready 结论仍以 0028 的真实 OpenClaw/平台证据为准。

## 8. 当前主要平台获取链

### Bilibili

```text
Search → Inspect → concrete video Representation
→ bilibili-video@1.0.0
→ 解析 DASH video/audio
→ 下载两路媒体
→ ffmpeg 合并
→ MP4 Asset
```

Windows 当前已具备 ffmpeg 合并依赖，但真实用户闭环仍待 0028 验收。

### Douyin

```text
Search → Inspect detail / aweme_id
→ concrete MP4 Representation
→ douyin-video@1.0.0
→ MP4 Asset
```

需要登录态时必须显式暴露认证事实，不得 fallback。

### Ximalaya

```text
Search → 绑定具体 track_id
→ Inspect 可播放音频
→ ximalaya-audio@1.0.0
→ MP3/M4A Asset
```

album 级候选不能在获取阶段静默替换成第一首。

### Anna's Archive

```text
Search（Libgen-backed metadata）
→ 合法 MD5 的 metadata Inspect（不访问合成 Anna 详情页）
→ annas-archive@1.0.0
→ 下载阶段解析真实 Libgen 镜像
→ 文件格式校验
→ document Asset
```

2026-08-14 已修复“合成详情页 403 被误判 AUTH_REQUIRED”的真实问题，等待用户复测。

### Shuge

```text
关键词 / 详情页 / 短链
→ Shuge SearchAdapter
→ OpenList 公共存储搜索
→ `/d/...` 文件候选 + file_path
→ ShugeInspector
→ concrete document Representation
→ generic-direct@1.0.0
→ HTTP 文件下载
```

平台特有逻辑在 Search/Inspect；文件已经是公开直链后复用通用 HTTP Downloader。

## 9. Download Job 调度

当前实现采用 **exact Provider 批次派发**，不是“一 JobItem 一 Service worker”。

```text
一个 Download Job
  ↓
按 exact (provider_id, provider_version) 分组
  ├─ Bilibili batch
  ├─ Ximalaya batch
  ├─ generic-direct batch
  └─ ...
```

- 单个 Provider 的所有 Item 在同一批次内处理；当前 Provider 内部接口仍是单资源调用，因此同 Provider 批次目前顺序执行。
- 不同 exact Provider 的批次可以并行。
- `JobRunner(max_workers)` 控制同时运行的 Job 数，不作为平台内部下载并发参数。
- Service 负责 Job 生命周期、取消、进度、Outcome、Asset/Bundle 收口。
- 未来某个平台要提高内部吞吐，应在对应 Provider/Downloader 完成文件隔离和平台验证后自行实现，不在 Service 增加全局平台并发表。

## 10. Generic Web 保存

当前网页链：

```text
Generic Search
→ GenericWebInspector
→ webpage Representation
→ generic-web-materializer
→ web_fetch.py
→ web_blocks.py
```

Job 工作产物：

```text
index.html
content.md
metadata.json
assets/*
webbundle.zip
```

公开 primary Asset 是可直接打开的 `index.html`。成功取得的同源正文图片可内嵌到 HTML；网页正文抽取质量和复杂页面结构保留仍由 pending 的 0041 benchmark 专门评估。

`web_materialize` 只回答“如何保存网页”，不能把 landing page 冒充正文资源，也不能替模型判断与用户目标的语义相关性。

## 11. 数据库与恢复

migration 1–7 保留旧库升级路径；migration 8 引入当前 acquisition 逐项表；migration 9 删除已废弃的旧 authority 表。

当前 active acquisition 状态以：

- Plan / PlanItem
- Job / JobItem
- Outcome
- Asset / Bundle

为主。历史 Capability Authority / Readiness / Eligibility / 多层 digest 不是当前下载执行链的业务状态权威。

## 12. 安全与真实性边界

必须保持：

- `prepare -> 用户明确确认 -> start`；
- Agent 不提交任意本地路径、脚本或 Provider 替代服务端 Plan；
- Start 重新核验当前 Resolution/Representation；
- Router 只执行 Plan 绑定的 exact Provider；失败不 silent fallback；
- 认证、不可用、策略阻断必须按真实事实暴露；
- Job 未产生真实 ready Asset 时不得报告下载成功；
- Archive 只接受服务端 ready `asset_id`；
- Skill 进入资源任务后，候选发现/Inspect/获取继续使用 `education-resources` 的 `resource_*` 业务数据面，不另开 browser/curl/其他 MCP 作为隐式第二来源。

## 13. 公共 Tool

当前共 14 个：

- `resource_flow_start`
- `resource_flow_status`
- `resource_flow_list`
- `resource_search`
- `resource_presentation_save`
- `resource_selection_save`
- `resource_download_prepare`
- `resource_download_start`
- `resource_job_status`
- `resource_job_cancel`
- `resource_archive`
- `resource_library_search`
- `resource_browse_creator`
- `resource_inspect`

## 14. 当前项目阶段

工程主链已经从“继续搭架构”进入“真实验收与质量收口”：

1. **0028 — Real OpenClaw / real platform E2E**：in_progress；真实用户验收是当前最重要的事实来源。
2. **0029 — Semantic retrieval benchmark / release gate**：pending；需要以 semantic-first Skill 的决策质量为核心，不复活旧状态机。
3. **0041 — Web content extraction benchmark**：pending；独立评估网页正文抽取与结构保留。

已完成的平台接入、Shuge、Anna Inspect、Skill 重构和下载调度历史均归档，不再作为顶层“进行中”任务。
