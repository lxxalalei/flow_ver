# 0060 — Resource 多文件自然交付与 SmartEdu 课程包语义

- 状态：in_progress
- 创建日期：2026-08-19
- 完成日期：未完成
- 范围：`mcp/education-resources` Inspect / Acquisition Planner / SmartEdu 课程资源、`learning-resource-flow` 下载语义

## Objective

修复真实 OpenClaw 使用中“SmartEdu 课程 URL 被当成网页，Agent 为了下载自行补一个格式，导致课程中视频与文档被降维成单文件”的问题。

最终语义：**一个 Resource 可以自然产生多个真实文件；`preferred_container="original"` 表示按该逻辑资源的自然交付方式获取，而不是要求 Agent 先猜一个文件扩展名。**

SmartEdu 是第一个暴露问题的平台，但核心语义不写成 `if platform == smartedu` 的通用特判。

## Non-goals

- 不新增 `Component` / `Bundle` / `AssetBundle` DTO 或持久状态层。
- 不新增批量工作流状态机。
- 不在本轮实现 `catalog_expand -> 全部课程自动批量下载` 新 Tool；Batch discovery 与大批量 acquisition 的直接衔接另看真实需求。
- 不扩展 SmartEdu 尚未验证的文件格式；继续只暴露/下载当前已支持的 PDF、MP4/HLS、MP3/M4A。
- 不改变 Session、Job、Archive 架构。

## Business invariants

1. Resource 是用户选择的逻辑对象，File 是最终副作用产物；两者不要求一一对应。
2. Inspect 必须如实暴露平台当前已确认的主表示与自然附带的受支持内容，不因为 landing URL 是网页就隐藏专门平台资源事实。
3. `original` 不制造格式偏好；平台 Provider 可以为一个 Resource 返回多个 `DownloadResult`。
4. 主 Representation 只用于确定 exact Provider / acquisition route；它不意味着最终只能产出一个文件。
5. 明确指定不存在的主格式必须显式失败，不能静默忽略用户要求。
6. SmartEdu 课程的多码率/MP4-HLS 技术变体仍只选一个主视频；PDF/音频等独立内容作为 attachment/companion 保留。
7. 真实 `AUTH_REQUIRED`、IP/网络出口限制、平台失败继续按原边界区分。

## Current architecture

当前底层已经允许一个 Provider 返回多文件：

```text
DownloadResult | DownloadBatchResult
  -> AcquisitionRouter
  -> ArtifactBundle(0..N artifacts)
  -> Job files[]
```

因此不需要新建 Bundle 状态。当前缺口在上游：

```text
SmartEduInspector
  -> _find_files(detail)
  -> _primary_candidate(...)
  -> 只公开一个 primary Representation
```

导致 Agent 看不到同一课程中的 PDF/音频等组成内容。

Acquisition Planner 当前在 `original` 下会优先 primary_resource；这个 primary 应继续作为 Provider 路由锚点，而不是单文件交付声明。

## Expected change surface

Likely to change：

- `adapters/inspect_smartedu.py`
- `acquisition/planner.py`
- focused regression test
- `TOOLS.md`
- `skills/learning-resource-flow/references/acquisition.md`
- MCP README

Should not change：

- `smartedu_download.py` 的现有课程多文件下载主逻辑
- Job / worker / Session / Batch 状态模型
- 其他平台 Adapter

## Acceptance criteria

- AC-01：SmartEdu course detail 同时含 MP4/HLS、PDF、MP3 时，Inspect 公开一个 primary 视频，并公开 PDF attachment、MP3 companion；同一视频的 HLS/MP4 只保留选中的主版本。
- AC-02：上述多 Representation 资源以 `preferred_container="original"` 规划时不报 `REPRESENTATION_AMBIGUOUS`，仍只路由一次 `smartedu-resource` Provider。
- AC-03：明确传不存在的主格式不能静默回退到默认 primary。
- AC-04：公开 Inspect 结果不泄漏 SmartEdu 存储 URL / access token。
- AC-05：Skill/TOOLS 明确“一 Resource -> 0..N Files”和 `original` 自然交付语义；Agent 不因 landing webpage 自行补格式。
- AC-06：现有 SmartEdu Downloader 的课程多文件选择规则保持不变。
- AC-07：真实 Windows OpenClaw 复测时，一个包含视频+资料的 SmartEdu 课程在不指定格式的情况下进入下载，并以 Job `files/failures` 如实呈现多文件结果。

## Complexity exceptions

默认：无。

本轮不新增抽象或 source of truth，只让 Inspect 与已有 DownloadBatchResult 能力对齐。

## 步骤

- [x] completed：确认真实问题来自 Inspect/Agent 语义，不是 Downloader 缺少多文件能力
- [x] completed：SmartEdu course Inspect 暴露自然交付中的主文件 + attachment/companion
- [x] completed：Planner 明确 `original` 以 primary 作路由锚点，并禁止显式缺失格式静默回退
- [x] completed：更新 Skill / TOOLS / MCP README 语义
- [x] completed：新增 focused regression test
- [ ] in_progress：执行 Python focused/full regression 与真实 Windows OpenClaw 课程包复测

## Validation

当前代码写入环境无法 clone/安装仓库（容器 DNS 无法解析 `github.com`），因此本提交不能把未执行的 pytest 冒充通过。

待执行：

```text
pytest tests/test_smartedu_resource_delivery.py
pytest tests/test_smartedu_bundle.py tests/test_platform_inspectors_media.py
full pytest（若作为部署/发布收口）
真实 OpenClaw：课程 URL -> Inspect -> resource_download(original) -> 多文件 Job
```

## 结果

实现完成后仍保持 `in_progress`，直到聚焦测试和至少一次真实 OpenClaw SmartEdu 课程包链路有实际证据。