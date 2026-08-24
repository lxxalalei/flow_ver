# 0060 — Resource 多文件自然交付与 Skill-first 批量获取收敛

> 处置：superseded by [0067-resource-capability-surface-unification.md](../0067-resource-capability-surface-unification.md)。多文件自然交付继续有效；旧 Batch 公共面不再有效，剩余真实验收已并入 [0028-real-openclaw-platform-e2e.md](../0028-real-openclaw-platform-e2e.md)。

- 状态：in_progress
- 创建日期：2026-08-19
- 完成日期：未完成
- 范围：`mcp/education-resources` Inspect / Download / Batch handoff、SmartEdu 课程资源、`learning-resource-flow` 下载语义

## Objective

修复两类同源的真实 OpenClaw 问题：

1. SmartEdu 课程 URL 被当成网页，Agent 为了下载自行补一个格式，导致同一课程中的视频与文档被降维成单文件；
2. Batch 能把目录/创作者/时间范围完整枚举出来，但若用户选择其中全部或部分，Agent 还需要分页搬运 URL、逐个 Import/Download，导致 MCP 过细、上下文膨胀。

最终语义：

- **一个 Resource 可以自然产生多个真实文件**；`preferred_container="original"` 表示按该逻辑资源的自然交付方式获取，而不是要求 Agent 先猜扩展名；
- **Batch 只产生候选，不代表用户已经选择下载**；用户明确选择后，现有 `resource_download` 复用同一多资源 Job 完成机械循环，不新增 Batch Acquisition 工作流。

SmartEdu 是第一个暴露多文件问题的平台，但核心语义不写成 `if platform == smartedu` 的通用工作流特判。

## Non-goals

- 不新增 `Component` / `Bundle` / `AssetBundle` DTO 或持久状态层。
- 不新增 Selection / Confirm / Prepare / Start / Batch Acquisition 状态机。
- 不新增 `resource_acquire_many` / `resource_batch_download` 等新 Tool；复用现有 `resource_download`。
- 不让 Batch 枚举完成自动触发下载；用户选择仍然是 Skill/Agent 语义前置。
- 不在本轮设计复杂内容筛选 DSL；“只要视频和课件”等细粒度语义继续由 Skill 理解，只有当前 Tool 能准确表达时才执行，不用猜格式代替选择。
- 不扩展 SmartEdu 尚未验证的文件格式；继续只暴露/下载当前已支持的 PDF、MP4/HLS、MP3/M4A。
- 不改变 Session、Archive 架构。

## Business invariants

1. Resource 是用户选择的逻辑对象，File 是最终副作用产物；两者不要求一一对应。
2. Inspect 必须如实暴露平台当前已确认的主表示与自然附带的受支持内容，不因为 landing URL 是网页就隐藏专门平台资源事实。
3. `original` 不制造格式偏好；平台 Provider 可以为一个 Resource 返回多个 `DownloadResult`。
4. 主 Representation 只用于确定 exact Provider / acquisition route；它不意味着最终只能产出一个文件。
5. 明确指定不存在的主格式必须显式失败，不能静默忽略用户要求。
6. SmartEdu 课程的多码率/MP4-HLS 技术变体仍只选一个主视频；PDF/音频等独立内容作为 attachment/companion 保留。
7. `resource_batch_collect` 的 `succeeded` 只证明候选枚举任务完成，不证明用户授权下载这些候选。
8. 用户明确选择 batch 的一部分时，`resource_batch_read` 只需把必要页候选恢复成当前进程 `resource_id`；用户明确选择完整 succeeded batch 的全部时，可直接把 `batch_job_id` 交给 `resource_download`。
9. `batch_job_id` 直接下载只接受完整 `succeeded` batch；`partial` / `failed` / `cancelled` 不得冒充“全部”。
10. 单资源直接下载仍保持快路径，不强制先走额外 Contents/Inspect；Download 内部 fresh Inspect 保留。
11. 真实 `AUTH_REQUIRED`、IP/网络出口限制、平台失败继续按原边界区分。

## Current architecture

当前底层已经允许一个 Provider 返回多文件：

```text
DownloadResult | DownloadBatchResult
  -> AcquisitionRouter
  -> ArtifactBundle(0..N artifacts)
  -> Job files[]
```

现有 `resource_download(resource_ids=[...])` 也已经是多 Resource 后台 Job：detached worker 对每个 Resource 执行 fresh Inspect -> exact Provider -> 0..N Files。因此不需要再造 `Acquire Many` Tool。

Batch 当前把完整枚举写入：

```text
batch job
  -> results.jsonl
```

本轮只补两个 handoff：

```text
部分选择：
resource_batch_read
  -> page candidate + process-local resource_id
  -> resource_download(resource_ids=[用户选中的...])

全部选择：
complete succeeded batch
  -> resource_download(batch_job_id=...)
  -> 读取完整 results.jsonl
  -> 普通多 Resource download job
```

用户选择仍位于两者之间，不形成后端 Selection 状态。

## Expected change surface

Likely to change：

- `service.py`
- `server.py`
- focused regression test
- `docs/CURRENT_ARCHITECTURE.md`
- `skills/learning-resource-flow/references/acquisition.md`
- 本计划 / 真实 OpenClaw 验收记录

Should not change：

- `smartedu_download.py` 的现有课程多文件下载主逻辑
- Job worker 的逐 Resource 下载循环
- Session / Archive 状态模型
- 其他平台 Adapter
- Tool 总数（仍 14）

## Acceptance criteria

### 多文件资源

- AC-01：SmartEdu course detail 同时含 MP4/HLS、PDF、MP3 时，Inspect 公开一个 primary 视频，并公开 PDF attachment、MP3 companion；同一视频的 HLS/MP4 只保留选中的主版本。
- AC-02：上述多 Representation 资源以 `preferred_container="original"` 规划时不报 `REPRESENTATION_AMBIGUOUS`，仍只路由一次 `smartedu-resource` Provider。
- AC-03：明确传不存在的主格式不能静默回退到默认 primary。
- AC-04：公开 Inspect 结果不泄漏 SmartEdu 存储 URL / access token。
- AC-05：现有 SmartEdu Downloader 的课程多文件选择规则保持不变。

### Batch -> Download handoff

- AC-06：`resource_batch_read` 返回的每个合法候选同时获得当前进程 `resource_id`，用户选部分时可直接交给现有 `resource_download(resource_ids=[...])`。
- AC-07：完整 `succeeded` batch 在用户明确选择“全部”后，可 `resource_download(batch_job_id=...)` 形成一个普通 download job；request 中包含全部已枚举 Resource，不需要 Agent 分页搬运全部 URL。
- AC-08：`resource_ids` 与 `batch_job_id` 必须二选一；两者都没有或同时提供都显式失败。
- AC-09：`partial` / `failed` / `cancelled` batch 不能直接作为“全部”下载来源。
- AC-10：不新增 Tool；stdio Tool 数保持 14。
- AC-11：Skill/Tool 文案明确 Batch 是候选集合，必须先有用户选择；批量后台执行只是减少机械循环。

### 真实验收

- AC-12：真实 Windows OpenClaw 中，一个包含视频+资料的 SmartEdu 课程在不指定格式的情况下进入下载，并以 Job `files/failures` 如实呈现多文件结果。
- AC-13：真实 Batch 场景中，用户先看到/理解候选范围，再明确选择“全部”或部分；只有之后才出现 download job。选择全部时 Agent 不再分页搬运整批 URL。

## Complexity exceptions

默认：无。

本轮不新增 source of truth，只把已有 `results.jsonl`、进程内 `resource_id` 与现有多 Resource Download Job 接起来。

当前 `resource_download(batch_job_id=...)` 会在提交下载 Job 时把 batch 的资源事实读入 `request.json`。这没有结果条数硬上限，也不静默截断；若未来真实规模证明 request 体量成为瓶颈，再改为 worker 流式读取 batch source，不提前做第二套 Job 类型。

## 步骤

- [x] completed：确认真实问题来自 Inspect/Agent 语义，不是 Downloader 缺少多文件能力
- [x] completed：SmartEdu course Inspect 暴露自然交付中的主文件 + attachment/companion
- [x] completed：Planner 明确 `original` 以 primary 作路由锚点，并禁止显式缺失格式静默回退
- [x] completed：确认现有 `resource_download` 已是多 Resource 后台 Job，不新增 Acquire Many Tool
- [x] completed：BatchRead 页候选恢复为当前进程 `resource_id`
- [x] completed：完整 succeeded batch 可作为 `resource_download` 的另一种已选资源来源
- [x] completed：明确 incomplete batch 不可冒充“全部”
- [x] completed：更新 Skill / runtime Tool schema / 当前架构文档
- [x] completed：新增 batch handoff focused regression test
- [ ] in_progress：执行 Python focused/full regression 与真实 Windows OpenClaw 课程包 + Batch 选择复测

## Validation

当前 ChatGPT 工作容器没有该 Git 仓库运行副本，且此前容器网络出口无法直接 clone/安装，因此不能把未执行的 pytest 冒充通过。

待执行：

```text
pytest tests/test_smartedu_resource_delivery.py
pytest tests/test_batch_download_handoff.py tests/test_batch_base.py tests/test_batch_catalog.py
pytest tests/test_mcp_stdio.py
full pytest（部署/发布收口时）

真实 OpenClaw 1：课程 URL -> 用户选中 -> resource_download(original) -> 多文件 Job
真实 OpenClaw 2：catalog/creator batch -> 用户明确选择全部 -> resource_download(batch_job_id) -> 一个多 Resource Job
真实 OpenClaw 3：batch -> 用户只选部分 -> batch_read resource_id -> resource_download(resource_ids)
```

## 结果

实现完成后仍保持 `in_progress`，直到聚焦测试和至少一次真实 OpenClaw SmartEdu 课程包/Batch 选择链路有实际证据。
