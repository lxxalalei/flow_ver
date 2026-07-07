# 流水线数据契约快照

本文只汇总当前各生产 Skill 的输入输出，便于 Flow 维护和排查。运行时以各生产 Skill 的 `SKILL.md`、输出 Schema 或写入脚本为准；其他 Skill 不需要加载本文。

## 通用规则

- 使用绝对 `session_dir` 传递持久化阶段数据。处理当前用户交互时，可以额外传递该轮用户原话；阶段 Skill 必须先把它转换为正式输出文件，再继续下游流程。
- 每个持久化文件使用 `_meta`、可选 `_summary` 和 `data`。
- `_meta` 至少包含 `schema_version`、`session_id`、`created_at`。
- 同一会话的所有文件使用相同 `session_id`。
- 资源通过稳定的 `resource_id` 关联；后续阶段不复制已有的完整资源对象。
- 未知可选字段省略，不写空占位值。

## 文件与所有者

| 文件 | 版本 | 写入者 | 读取者 |
|---|---|---|---|
| `request.json` | `request/v1` | learning-resource-flow | resource-intent |
| `stage1_intent.json` | `intent-spec/v1` | resource-intent | resource-search、resource-selector、library-manager |
| `stage2_search_plan.json` | `search-plan/v1` | resource-search | resource-platforms |
| `stage3_search_results.json` | `platform-results/v1` | resource-platforms | resource-selector、resource-downloader、library-manager |
| `stage4_selection.json` | `selection/v1` | resource-selector | resource-downloader、library-manager |
| `stage5_download.json` | `download/v1` | resource-downloader | library-manager |
| `stage6_archive.json` | `archive/v1` | library-manager | learning-resource-flow |

`manifest.json` 由 Flow 独立维护，不作为业务数据输入。

## 阶段边界

### request/v1

- `data.raw_request`：用户原始需求。
- `data.conversation_evidence[]`：只包含 `role` 和原文 `content`。

### intent-spec/v1

- `_summary.status` 与 `data.status` 一致，值为 `ready` 或 `needs_clarification`。
- `data` 必含 `raw_request`、`slots`、`constraints`、`search_concepts`。
- 槽位出现时必须有非空 `value`；数组槽位不得为空或重复。
- `needs_clarification` 时必须有唯一问题；`ready` 时必须有 `core_topic`。

### search-plan/v1

- `data.search_tasks[]` 每个平台最多一项。
- 每项包含 `platform`、`priority`、非空 `searches[]`。
- 每次搜索包含 `query`、`max_results` 和可选 `params`。
- 计划恰好包含一个 `generic` 任务；generic 搜索的 `params.engines` 必须包含 `duckduckgo`，可按需额外包含 `bing` 或 `baidu`。

### platform-results/v1

- `_summary.resource_count` 等于 `data.resources` 数量。
- 每条资源必含 `resource_id`、`platform`、`title`、`source_url`。
- `data.errors[]` 只记录真实错误，包含 `platform`、`error_code`、`message`、`retryable`；零结果不是错误。

### selection/v1

- `data.status` 为 `selected` 或 `cancelled`，并与 `_summary.status` 一致。
- `selected` 时 `data.selected[]` 非空，每项至少包含 `resource_id` 和 `quality_score`。
- `cancelled` 时选择数组为空。

### download/v1

- 每个已选 `resource_id` 恰好有一条 `data.results[]`。
- `download_status` 为 `success`、`degraded` 或 `failed`。
- 成功和降级必须有真实文件；降级和失败必须有结构化 `error`；失败文件数组为空。
- `_summary` 的成功、降级和失败计数从结果数组计算。

### archive/v1

- 每条 Stage 5 结果恰好有一条同 `resource_id` 的归档结果。
- `archive_status` 为 `archived`、`skipped` 或 `failed`。
- `archived` 必须有资料库路径；`skipped` 只表示重复并必须有 `duplicate_of`；`failed` 必须有 `archive_error`。
- `_summary` 的归档、跳过和失败计数从结果数组计算。
