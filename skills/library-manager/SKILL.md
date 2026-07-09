---
name: library-manager
description: 成长资料库管理 Skill。用于将 Stage 5 下载或降级结果去重、按成长领域分类、移动并写入资料库索引，也用于检索、维护和统计已有资料。负责资料库状态，不负责搜索、筛选或下载。
---

# library-manager

## 职责

归档模式负责：

- 读取 Stage 1、3、4、5 文件并按 `resource_id` 组合归档信息。
- 执行资料库入库前去重。
- 选择资料库分类和文件名。
- 移动文件、保存降级内容或来源记录。
- 更新索引和元数据。
- 写入 `stage6_archive.json`。

此外支持按主题、成长领域、年龄、类型、来源和标签检索现有资料，以及执行删除、统计和整理。

不负责重新搜索、修改 Selector 评分或重新下载资源。

本 Skill 拥有 `archive/v1` 的输出格式。归档时通过 `resource_id` 关联所需上游文件，不要求 Stage 5 重复来源、需求或质量字段。

## 资料库结构

默认资料库根目录为 `~/成长资料库`；用户明确指定其他位置时使用其指定路径。根目录不存在时由模型创建，并在首次归档时创建 `{library_root}/.library/index.json`。不要求用户预先创建配置文件。分类、目录粒度、文件命名、附属文件、待确认目录、备份和空间管理全部按需读取 `references/library-structure.md`；本文件不重复维护目录规则。

资料库内部至少维护：

- 资源文件或降级内容。
- 元数据索引。
- 内容指纹和 URL 等去重信息。

模型负责归档时的分类、命名、移动、索引维护和结果写入；`scripts/dedup.py` 用于需要时的确定性去重，不替代模型的语义判断。

## 归档流程

### 1. 读取输入

- 输入：同会话的 `stage1_intent.json`、`stage3_search_results.json`、`stage4_selection.json` 和 `stage5_download.json`。
- 输出：`{session_dir}/stage6_archive.json`，Schema 为 `archive/v1`。
- 按 `resource_id` 读取需求语义、来源、质量和下载结果；不要求 Stage 5 重复这些字段。

### 2. 入库前去重

按可靠性由高到低组合判断：

1. `resource_id` 完全一致。
2. 文件内容指纹一致。
3. 规范化 `source_url` 一致。
4. 标题、作者、时长或文件信息高度相似。

需要时使用 `scripts/dedup.py` 完成内容指纹、URL 和标题相似度检查。无法确认时不要静默删除，可以标记并保留。

发现重复时按配置决定保留现有、替换、合并元数据或跳过；因重复跳过时记录 `duplicate_of`。

### 3. 分类和命名

根据资源现有的主题、成长领域、学科方向、适龄、类型和版本信息选择目录。每个资源只选择一个一级主分类，按资源核心内容和主要学习目标判断，不按家长辅助、亲子共用等使用方式判断；跨领域关联写入现有标签或索引，不复制文件到多个一级目录。只有不存在明确主次关系时才使用“综合主题”。分类、适龄或主题证据不足时使用“待确认”。

文件名应简短、可识别并保留扩展名。详细规则只读取 `references/library-structure.md`。

### 4. 保存不同下载状态

- `success`：移动完整文件并更新最终资料库路径。
- `degraded`：保存预览、正文、摘要或链接记录，并保留降级说明。
- `failed`：根据现有元数据决定保存来源链接、跳过或记录归档失败，不伪造本地文件。

### 5. 更新索引

索引至少保留：

- `resource_id`、标题、平台和来源 URL。
- 主题、类型、适龄、标签和版本等已有元数据。
- Selector 质量信息。
- 下载状态、文件信息和降级信息。
- 资料库路径、归档时间和去重状态。

为支持按自然语言交叉检索，每条索引资源还必须使用以下稳定字段：

- `primary_domain`：资源所在的一级主分类。
- `secondary_domains`：跨领域关联；没有则为空数组。
- `audience`：`child`、`parent`、`family` 或 `unknown`。
- `age_or_grade`：已有的年龄、年级或 `全龄通用`；无法判断时为 `unknown`。
- `topics`：1-3 个规范主题词。
- `resource_type`：资源类型。
- `formats`：实际可用的文件或访问格式数组，例如 `PDF`、`MP4`、`MP3`、`HTML` 或 `link`；无法判断时为 `unknown`。

这些字段服务检索，不要求为每个字段新建目录，也不替代已有来源、版本、质量和下载状态等元数据。

主索引位于 `{library_root}/.library/index.json`。首次创建时写入 `{"schema_version":"library-index/v1","resources":[]}`；后续由模型在每次归档、整理或删除时维护。索引更新与文件移动应作为同一归档操作；任一关键步骤失败时记录 `archive_error`。

### 6. 写入结果

每条 Stage 5 结果只写一条归档结果：

- `archive_status`：`archived` / `skipped` / `failed`
- `library_paths`：使用可访问的绝对路径。
- `duplicate_of`（`skipped` 时必填；`skipped` 只表示重复资源未再次归档）
- `archive_error`（仅失败时）

```json
{
  "_meta": {
    "schema_version": "archive/v1",
    "session_id": "继承上游",
    "created_at": "ISO 8601"
  },
  "_summary": {
    "archived_count": 1,
    "skipped_count": 0,
    "failed_count": 0
  },
  "data": {
    "results": [
      {
        "resource_id": "bilibili:BV1example",
        "archive_status": "archived",
        "library_paths": ["/absolute/成长资料库/自然与科学/8-10岁/example.mp4"]
      }
    ]
  }
}
```

## 检索模式

检索已有资料时读取资料库索引，不创建新的流水线 stage 文件。先将用户的自然语言问题映射到 `primary_domain`、`secondary_domains`、`audience`、`age_or_grade`、`topics`、`resource_type` 和 `formats` 的组合，再结合标题、来源和其他元数据返回结果；不要只按目录路径猜测。支持组合条件：

- 主题或关键词。
- 成长领域、学科方向和适龄。
- 资源类型和文件格式。
- 平台、质量等级和下载状态。
- 标签、版本和归档时间。

返回结果必须包含标题、资料库路径、来源和关键元数据。用户要求打开、复制或删除时再执行对应操作。

## 维护模式

- 删除：同步处理文件、索引、指纹和关联附属文件；执行前要求用户明确确认。
- 整理：可以重新分类、重命名、补索引或检测重复，不重新评分内容。
- 统计：按成长领域、适龄、类型、平台、质量和存储占用汇总。
- 备份：遵循 `references/library-structure.md` 的备份范围，不复制临时下载目录。

## 完成条件

- 每条 Stage 5 结果都有一条同 `resource_id` 归档结果。
- 已归档资源的 `library_paths` 可访问，索引与实际文件一致。
- 跳过和失败均有可解释原因。
- `_summary` 的三项计数必须能从 `data.results` 核对；只向 Flow 返回 `_summary` 和输出路径。

写入后运行：

```bash
python3 library-manager/scripts/validate_output.py {session_dir}
```

校验失败时修复一次；仍失败则向 Flow 返回失败。

## 参考资料

- `references/library-structure.md`：目录、命名、附属文件、备份和空间管理。
- `scripts/dedup.py`：下载文件指纹、URL、标题和资料库索引去重实现。
