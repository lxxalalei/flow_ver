# MCP Capability Inventory

> 审计日期：2026-08-28
> 适用实现：`education-resources` MCP，12 个公共 Tool
> 性质：运行时契约审计证据，不是第二份 capability registry。机器事实仍以 stdio `tools/list`、真实 Tool 返回和代码实现为准。

## 1. 为什么需要这份清单

审计前，12 个 Tool 的参数字段已有局部说明，但 stdio `tools/list` 返回的顶层 `description` 全部为空。模型能看到“参数怎么填”，却缺少“什么时候应该调用、什么时候不应该调用、会不会产生副作用”的完整入口语义。

本轮只把已经存在的能力写清楚：

- 不新增或删除 Tool；
- 不改变 input schema 的字段集合；
- 不改变 Service、Adapter、Job、Session 或 Archive 行为；
- 不把 Tool 组织成固定流水线；
- 不把本清单读入运行时或复制成新的 Registry。

## 2. 能力总图

```text
开放网页发现 ── Host Web Search
                    │ 已知/选中 URL
                    ▼
MCP 平台发现 ─ resource_search
已知 URL      ─ resource_import_url
已知容器      ─ resource_expand ── job_status / job_read / job_cancel
候选事实      ─ resource_inspect
明确选择      ─ resource_download ─ job_status / job_cancel
网页视觉优化  ─ resource_html_design
真实文件归档  ─ resource_archive
真实认证需要  ─ resource_session_status / resource_session_manage
```

Search、Expand、Inspect、Download 可以组合，但不是固定步骤。Import、Download、HTML Design、Archive 和 Session Manage 都有各自独立的用户意图门槛。

## 3. 12 Tool 审计

| Tool | 用户自然语言意图 | 应调用 | 不应调用 | 输入身份 | 结果与持久性 | 副作用 / 认证 | 典型显式失败 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `resource_search` | “在 B 站/智慧教育/喜马拉雅找……” | 用户目标需要明确 MCP 平台的原生发现能力；同一调用可提交多个平台任务 | 已知 URL；已知容器完整枚举；开放 Web 文章发现；用户未选择却直接下载 | `platform + natural queries` | 返回候选、真实 URL、临时 `resource_id`、`matched_queries`、`runs`、`failures`；不建持久 Job | 无文件副作用；平台真实返回 `AUTH_REQUIRED` 才进入 Session | `PLATFORM_UNAVAILABLE`、`PARTIAL_FAILURE`、平台真实认证/网络错误 |
| `resource_expand` | “列出这个 UP/合集/专辑/教材/课程的全部子资源” | 已知容器需要结构化向下枚举 | 普通搜索；只需代表性 Browse；video/track/file 等叶子反向找父对象 | `resource_id` 或 `source_url` 二选一 | 立即返回持久 Expand `job_id`；完整结果写 `results.jsonl` | 启动后台枚举，但不下载 | `INVALID_ARGUMENT`、`FEATURE_NOT_SUPPORTED`、平台分页/完整性失败 |
| `resource_import_url` | “就处理/保存这个链接”或用户选中 Web URL | 已经有一个具体 HTTP(S) URL，后续需要 MCP 事实或文件动作 | 搜索；批量导入所有 Web 命中；仅推荐 URL 且无需 MCP 深读 | 稳定 `source_url` | 识别平台、注册临时 `resource_id` 并做当前 Inspect；不持久化资源数据库 | 无文件下载；Inspect 可能遇到真实认证/网络失败 | `INVALID_ARGUMENT`、`RESOURCE_NOT_FOUND`、Inspector failures |
| `resource_inspect` | “确认它是不是 PDF/是否可下载/版本是什么” | 未知的当前事实会改变推荐、选择或获取 | 为流程完整 Inspect 全部候选；已知事实足够 | 当前进程 `resource_id` | 返回 resolution status、availability、representations 和 failures；不建 Job | 无文件副作用；可暴露 `requires_auth` 或认证失败 | `RESOURCE_NOT_FOUND`、`AUTH_REQUIRED`、平台 resolution failures |
| `resource_download` | “把第 2 个下载”“把刚才展开的全部下载” | 用户已明确选择资源；对象清楚 | Search/Expand 后自动下载；只是在浏览/推荐；把 partial Expand 冒充全部 | `resource_ids[]` 或完整 succeeded `expand_job_id` 二选一 | 返回持久 Download `job_id`；最终真实文件/失败由 Job 记录 | 明确文件副作用；fresh Inspect 后走 exact Provider | `INVALID_ARGUMENT`、`EXPAND_INCOMPLETE`、`AUTH_REQUIRED`、格式/Provider/网络失败 |
| `resource_job_status` | “下载好了吗”“展开到哪了” | 查询 Expand/Download Job 进度或最终结果 | 读取 Expand 子资源页面；把 queued 当完成 | 持久 `job_id` | 返回 status、progress；终态返回 Download files/failures 或 Job summary | 只读 | `JOB_NOT_FOUND`、`JOB_STATE_INVALID` |
| `resource_job_cancel` | “停止这个下载/枚举” | 用户要求停止，或当前活动操作明确不再需要 | 无理由取消；删除已完成文件 | 活动 `job_id` | 创建 cancel signal；返回 cancelling/cancelled；终态保持原状态 | 取消后台副作用，不删除已产出文件 | `JOB_NOT_FOUND`、`JOB_STATE_INVALID` |
| `resource_job_read` | “查看展开结果第 N 页”“从全集里选几项” | Expand Job 结果需要分页进入上下文或定位部分子资源 | 读取 Download Job 文件；把页大小当完整枚举上限 | Expand `job_id + offset + limit` | 返回一页 items，每项注册临时 `resource_id`；磁盘完整结果不截断 | 只读；单页最多 50 是 Tool Result 大小，不是业务总量 | `INVALID_ARGUMENT`、`JOB_STATE_INVALID` |
| `resource_html_design` | “把下载的网页排得精美一些” | 用户明确要求视觉优化，且已有单个 Generic Web Download Job | 默认网页下载；非网页文件；让模型传正文/HTML/CSS | `action=context/render + job_id + DesignSpec?` | context 返回有界设计摘要；render 更新 `index.html` 和 Job 文件事实 | render 修改已下载 HTML；不改 `source.html` / `content.md` | `INVALID_ARGUMENT`、Job/产物不匹配、DesignSpec 校验失败 |
| `resource_archive` | “把下载结果归档到学习资料库” | Download Job 已 succeeded/partial 且有真实文件，用户需要归档 | 下载前；Expand Job；没有文件；用 ArchiveRecord 代替真实文件 | Download `job_id + domain_id/topic?` | 移动真实文件并同步 Job file path，返回 library/files/failures | 文件移动副作用；Agent 决定语义分类 | `JOB_NOT_FINISHED`、`FILE_NOT_FOUND`、真实文件移动失败 |
| `resource_session_status` | “这个平台登录了吗”或能力返回认证要求 | 真实 `AUTH_REQUIRED` 后；用户主动查看/验证会话 | 每次 Search/Download 前置检查；猜测 IP/风控就是登录问题 | `platforms? + deep?` | 返回 session status、needs_login；deep 只 probe 支持的平台 | deep 可能发远端 probe；不保存/删除 Session | 不支持平台、probe 真实失败 |
| `resource_session_manage` | “保存刚才登录态”“删掉平台登录态” | 用户已自行登录并有浏览器 capture；或明确删除 Session | 代填密码/MFA；Agent 手拼 Cookie/Token；无授权删除 | `action + platform + capture?/expires_at?` | save 只持久化平台 canonical subset；delete 删除该平台 Session | 明确本地凭据副作用；Windows 使用当前用户 DPAPI | `INVALID_ARGUMENT`、capture 校验/平台认证契约失败 |

## 4. 组合调用的最小语义

### 开放 Web 发现与获取

```text
Host Web Search
→ 用户选择或关键事实确需深读
→ resource_import_url
→ 必要时 resource_inspect
→ 用户明确获取后 resource_download
```

Web 候选可以直接展示和被选择，不应为了获得 `resource_id` 批量 Import。

### 平台容器的部分选择

```text
resource_expand
→ resource_job_status 直到终态
→ resource_job_read 读取需要的页
→ 用户选择部分 resource_id
→ resource_download(resource_ids=[...])
```

### 平台容器的完整获取

```text
resource_expand
→ succeeded
→ 用户明确选择全部
→ resource_download(expand_job_id=...)
```

partial/failed/cancelled Expand 不能代表“完整全部”。

### Generic Web 视觉优化

```text
明确选中 URL → Import → Download
→ 用户明确要求视觉优化
→ resource_html_design(context)
→ Agent/HTML Design Skill 产生 DesignSpec
→ resource_html_design(render)
```

### 认证恢复

```text
真实能力返回 AUTH_REQUIRED
→ resource_session_status(platform)
→ 用户自行登录并完成浏览器 capture
→ resource_session_manage(save)
→ 重试原能力
```

Session 不是 Search/Download 的固定前置步骤。

## 5. Description/schema 审计结论

### 已修正

- 12 个 Tool 增加顶层 runtime description；
- 每个 description 都包含能力用途、主要触发条件和至少一个关键非触发边界；
- 显式标出 Search/Expand 不授权 Download；
- 显式区分 Job Status 与 Expand Job Read；
- 显式区分普通网页 Download 与可选 HTML Design；
- 显式声明 Session 只在真实认证需要或用户主动管理时使用。

### 保持不变

- Tool 数量和名称；
- input schema 字段集合、默认值和类型；
- output schema；
- Service/Adapter/Downloader 行为；
- Job/Session/Archive 持久结构。

### 后续由 Elicitation 验证，而不是继续加文案

- 模型能否区分 Host Web Search 与 MCP 平台 Search；
- Browse 与完整 Enumerate 能否分别选择 Search/Expand；
- 用户选择部分/全部 Expand 结果时能否选对 Download 输入；
- 临时 `resource_id` 失效时能否用真实 URL 恢复；
- 是否避免 Session preflight 和未授权副作用；
- HTML Design 是否只在用户明确视觉需求时触发。
