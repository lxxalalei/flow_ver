---
name: resource-selector
description: 学习资源候选筛选与用户选择 Skill。读取 Intent 与 Platform 的真实搜索结果，利用模型语义判断执行相关性和儿童安全过滤、跨平台相似判断、证据化质量评分与排序，向用户展示候选，并在明确选择后写入 Stage 4。用于搜索完成后的候选审查，不执行搜索或下载。
---

# resource-selector

## 目标

把 Stage 3 的原始召回变成一组真正适合当前需求、可解释且便于用户选择的候选。这里依赖模型理解语义，不把标题关键词命中、平台热度或固定字段数量当成质量判断。

本 Skill 负责跨平台去重、业务过滤、统一质量评分、排序展示和用户选择交接。

读取：

- `{session_dir}/stage1_intent.json`
- `{session_dir}/stage3_search_results.json`

私有工作文件：

- `selector_input.json`：脚本完成的精确去重和相似提示。
- `selector_review.json`：模型逐条审查后的候选、过滤结果和展示顺序。

只有用户明确选择或取消后才写 `stage4_selection.json`。首次展示候选时不得提前生成 Stage 4。

## 第一次调用：审查并展示

### 1. 准备候选

运行：

```bash
python3 resource-selector/scripts/prepare_candidates.py {session_dir}
```

脚本只处理确定性事务：校验会话、按相同 ID/URL 精确去重、提示高标题相似对、保留平台错误。它不判断相关性、安全性或质量。

### 2. 重新理解需求

完整阅读 Intent，不要只拿 `core_topic` 做字符串匹配。明确：

- 用户真正要学习什么、用于什么场景。
- 年龄、年级、难度和学习目标。
- 明确要求的形态、文件类型、语言、来源、免费或版本条件。
- 哪些是硬约束，哪些只是偏好，哪些完全没有要求。

用户没有限制形态时，视频、音频、图文和课程可以共同进入候选；不要自行把某种形式设为唯一正确答案。

### 3. 逐条语义审查

对 `selector_input.json:data.candidates` 每一条都作出明确处理。

先判断是否过滤：

- 资源本身是否在教、练或解释当前主题，而不是只碰巧包含某个词。
- 学段和难度是否明显冲突。例如“四年级数学”不能保留“高等数学课程”。
- 标题和现有描述是否提供足够证据。只有“练习四”且没有年级、学科证据时，不能仅因平台权威而推定相关。
- 是否含成人、色情、暴力、诈骗、危险模仿或其他儿童不宜内容。儿童安全冲突直接过滤。
- 是否违反免费、语言、文件格式或来源等硬约束。
- 是否为空页面、广告、失效链接或无法定位的内容。

搜索引擎可能返回完全偏题甚至儿童不宜的结果；不要因为它来自 generic 就降低过滤标准。平台热度只能证明受关注，不能证明相关、适龄或教学质量。

保留后按照 `references/quality-rubric.md` 评分。评分理由必须引用当前资源已有证据，例如官方来源、标题所示册次、课时数、作者、免费状态或信息缺失；不得编造内容、答案、字幕、教材版本、可打印性和下载能力。

`possible_duplicates` 只是提示。只有能确认是同一内容或同一课程镜像时才去重；相似但版本、册次、教师或媒介不同的资源应分别保留。

### 4. 写入模型审查

写入 `{session_dir}/selector_review.json`：

```json
{
  "_meta": {
    "schema_version": "selector-review/v1",
    "session_id": "继承上游",
    "created_at": "ISO 8601"
  },
  "data": {
    "candidates": [
      {
        "resource_id": "bilibili:BV1example",
        "relevance": "high",
        "quality_score": 82,
        "summary": "用一句话总结这个资源是什么、适合谁、有什么特点",
        "reasons": ["标题明确覆盖小学四年级数学上下册", "系列课程信息完整"],
        "notes": ["教材版本需用户确认"]
      }
    ],
    "excluded": [
      {
        "resource_id": "generic:example",
        "reason": "与四年级数学无关，且包含儿童不宜内容"
      }
    ]
  }
}
```

要求：

- 每个预处理候选恰好出现在 `candidates` 或 `excluded` 一次。
- `candidates` 按 `quality_score` 降序排列，这个顺序就是展示编号。
- 保留项只使用 `high` 或 `medium` 相关性；低相关直接过滤。
- `quality_score` 低于 40 的资源不得保留。
- `summary`：用一句话（不超过50字）总结这个资源是什么、适合谁或有什么特点。基于标题、描述和已知信息生成，不要照搬原文，不要编造不存在的内容。每个候选都必须有 `summary`。
- `reasons` 服务用户理解推荐依据；`notes` 只记录真正影响选择的未知或风险。

运行：

```bash
python3 resource-selector/scripts/validate_review.py \
  {session_dir}/selector_input.json \
  {session_dir}/selector_review.json
```

校验失败时根据错误修复一次。不要通过删除未审查资源绕过校验。

### 5. 展示并暂停

运行：

```bash
python3 resource-selector/scripts/render_review.py {session_dir}
```

渲染器默认按资源类型分组展示（视频 → 音频 → 文档 → 习题 → 课程 → 网页），每组以 `{type_icon} {category_name}（{count} 条）` 标题起始。每条候选严格四行格式，以 emoji 引导。详细格式见 `references/display-templates.md`。

**必须原样使用渲染器输出的文本**，不得改写为 markdown 表格、精简格式或其他排版。把渲染器输出和选择说明原样返回 Flow，由 Flow 将 Stage 4 标记为 `waiting_user` 并向用户展示。本轮停止，不调用 Downloader，不生成 Stage 4。

## 第二次调用：处理用户选择

Flow 把用户选择原话和 `{session_dir}` 交回本 Skill。读取既有 `selector_review.json`，不要重新搜索或重新评分。

支持：

- 编号或多个编号。
- 全部。
- 按平台、资源类型或等级选择。
- 查看更多：继续展示 review 中尚未展示的候选。
- 取消。

先把用户原话解析成明确的 `resource_id`。有歧义时只追问选择范围，不擅自下载。确认选择后运行：

```bash
python3 resource-selector/scripts/finalize_selection.py \
  {session_dir} --indices 1,3
```

也可使用 `--resource-id`、`--all` 或 `--cancel`。脚本从 review 取得最终分数和风险说明，原子写入 `stage4_selection.json`，不会复制完整资源对象。

## 边界

- 不生成搜索词，不调用平台接口。
- 不下载或探测下载链接。
- 不把未知信息推断成确定事实。
- 不因平台名气或播放量直接给高分。
- 不在用户确认前生成选择结果。

## 按需读取

- `references/quality-rubric.md`：评分与证据不足处理。
- `references/display-templates.md`：候选展示和选择说明。
- `../docs/pipeline-data-contract.md`：正式 Stage 4 输出边界。
