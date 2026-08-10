# 学习资料库归档结构

## 定位

资料库只归档学习资料，不建立完整儿童成长档案。一级领域回答“这份资料主要学什么”；
使用场景、学段、格式、资料用途、难度和教材版本只能进入各自的结构化字段，不能成为
一级领域。

归档前先根据 Resource 的标题、摘要、来源和已验证 Asset 信息判断证据。服务端拥有标题、
来源、媒体类型、扩展名、大小和 SHA-256 等权威事实；模型不得重复编造或用自己提交的
`source_name` 覆盖这些事实。

## 一级学习领域

一级领域使用以下固定机器 ID。机器 ID 是内部稳定值，中文名称用于用户展示和物理目录；
不得创建新的 ID。

| 机器 ID | 中文展示与目录名称 |
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

每份资料只能有一个主领域，可以有零到 4 个次领域。主领域不能再次出现在次领域中；
次领域去重，并且只能取自同一注册表。

以下内容不是一级领域：亲子陪伴、家长辅导、自主学习、教材同步、幼儿、小学、初中、
视频、图文、音频、讲解、练习、试卷、入门、进阶、竞赛、综合主题和待分类。

确实属于 STEM、项目式学习或研究性学习时，使用
`interdisciplinary_practice`。只是涉及多个学科时，选择最能表达主要学习目标的主领域，
其余放入次领域。“待分类”是分类状态对应的物理兜底位置，不是领域 ID。

## 二级主题

主题是受控自由文本。选择能概括资料实际内容的短语，例如“阅读理解”“图形与几何”
“天文与宇宙”“人工智能”或“项目式学习”。不确定具体主题时使用“其他”。

提交主题时：

- 去除首尾空白并合并连续空白；规范化后去重。
- 不提交空字符串、控制字符、路径分隔符、`.` 或 `..`。
- 不把完整自然语言需求、用户原话或本地路径直接作为主题。
- 每个主题最多 64 个字符，一份资料最多 8 个主题；超出时保留证据最强、检索价值最高的主题。
- 物理目录只使用规范化后的第一个主主题；完整主题列表保存在结构化索引中。

常用主题方向如下，仅用于帮助选择短语，不是可自行扩展一级领域的依据：

| 一级领域 | 主题示例 |
|---|---|
| 语文与中文 | 拼音、识字与写字、词语与语法、阅读理解、写作、口语表达、古诗词、文言文、文学阅读 |
| 数学与思维 | 数与运算、图形与几何、统计与概率、应用题、数学思维、逻辑推理、奥数与竞赛 |
| 英语与外语 | 字母与自然拼读、词汇、语法、听力、口语、阅读、写作、分级阅读 |
| 自然科学 | 动物与植物、人体与生命、物理现象、化学与物质、地球与环境、天文与宇宙、科学实验、科普综合 |
| 人文与社会 | 中国历史、世界历史、中国地理、世界地理、传统文化、社会常识、法治与公民、哲学与思想启蒙 |
| 信息科技 | 计算机基础、信息素养、编程启蒙、人工智能、网络与安全、数字工具使用 |
| 艺术与审美 | 绘画、书法、音乐、舞蹈、戏剧与表演、手工与设计、艺术欣赏 |
| 体育与健康 | 体育知识、运动技能、身体与健康、营养与卫生、心理健康知识、安全常识 |
| 学习方法与通用能力 | 学习方法、记忆方法、专注力训练、时间管理、信息检索、表达与演讲、问题解决、阅读与笔记方法 |
| 综合实践与跨学科 | STEM、项目式学习、研究性学习、综合主题学习、劳动与实践、社会实践 |

## 结构化归档元数据

新归档使用版本化的 `classification` 对象：

```json
{
  "classification": {
    "taxonomy_version": "learning-v1",
    "classification_status": "classified",
    "primary_domain": "natural_science",
    "secondary_domains": [],
    "topics": ["天文与宇宙", "太阳系"],
    "material_purposes": ["explanation"],
    "grade_levels": ["小学"],
    "difficulty": "introductory",
    "curriculum_versions": []
  },
  "collection": "太阳系专题",
  "tags": ["科普", "动画讲解"],
  "notes": ""
}
```

`classification_status` 分类状态：

- `classified`：主领域和主题有充分证据。
- `needs_review`：能保存部分分类，但存在需要后续整理的不确定项。
- `unclassified`：现有证据不足以可靠选择主领域。

辅助字段规则：

- 资料用途只使用 `explanation`、`practice`、`assessment`、`reading`、`reference`、
  `experiment`、`project`、`lesson_material`。
- 难度只使用 `introductory`、`intermediate`、`advanced`、`competition`。
- 资料用途最多 8 项；学段或年级最多 8 项、每项最多 32 个字符；教材版本最多 8 项、
  每项最多 64 个字符。文本按主题规则清洗并拒绝控制字符和路径保留符。
- 学段、年级、难度和教材版本只有存在内容或用户明示证据时才填写；缺失字段保持为空，不为归档补问。
- `collection` 是用户自定义专题集合，不等于领域；`tags` 只用于辅助检索，不能替代领域、主题或资料用途。
- `collection` 最多 128 个字符；tags 最多 32 项、每项最多 64 个字符；`notes` 最多 2000 个字符。
- `notes` 只记录对后续使用确有帮助的简短说明，不复制完整需求。
- 新调用不提交模型猜测的本地路径、格式目录、标题、来源、媒体类型、大小或 SHA-256。

旧平铺 `primary_domain`、`topics`、`source_name` 和旧中文领域仅用于 兼容读取。
已知值由 MCP 映射到 `learning-v1`；无法可靠映射的记录进入 `needs_review` 并保留原始
元数据。新归档统一写入嵌套分类结构。

## 物理目录与命名

资料库根目录固定为 `学习资料库/`，标准相对结构为：

```text
学习资料库/
└── 04-自然科学/
    └── 天文与宇宙/
        └── 视频/
            └── B站-太阳系动画讲解.mp4
```

`needs_review` 或 `unclassified` 资料进入：

```text
学习资料库/
└── 99-待分类/
    └── 其他/
        └── 对应格式/
            └── 文件
```

格式目录固定为 `视频`、`图文`、`音频`、`其他`。MCP 根据已验证的真实媒体类型和扩展名
决定目录；未知格式进入 `其他`，不能默认进入“图文”，模型也不能指定格式目录。

文件名默认采用 `[来源]-[标题].[扩展名]`。来源和标题由 MCP 从 Resource 的权威字段取得；
没有来源时不产生多余分隔符。同名同内容复用已有内容，同名不同内容追加稳定短哈希，
绝不覆盖已有不同内容文件。所有目录和文件名清洗、路径边界、组件长度、总长度及符号链接
检查均由 MCP 执行。

## 去重、提交和恢复

归档只接受成功 Job 返回的 ready `asset_id`，不接受模型提供的本地路径。MCP 使用
SHA-256、文件大小及必要时媒体类型识别相同内容；不同 Asset 命中相同内容时不重复复制，
但保留新 Asset 到既有归档内容的可追溯关系，并返回 `deduplicated`。

MCP 以 `pending -> ready` 状态完成受控临时文件、大小和哈希复核、原子移动及 SQLite
提交。失败时不得产生 ready 记录；启动或维护对账会处理遗留 pending、缺失文件和孤立文件。
Skill 只解释 MCP 返回的真实状态，不能自行宣称已经归档、去重或恢复。

## 资料库检索

`resource_library_search` 只返回 `ready` 且文件存在的归档资料。关键词使用 `query`；结构化
过滤字段为 `taxonomy_versions`、`classification_statuses`、`primary_domains`、
`secondary_domains`、`topics`、`material_purposes`、`grade_levels`、`difficulties`、
`curriculum_versions`、`platforms`、`resource_types`、`resource_formats`、`collections`、
`tags`、`archived_after` 和 `archived_before`。

- 同一过滤字段的多个值采用 OR；不同字段之间采用 AND。
- 结构化字段使用精确匹配，不使用 JSON 子串匹配。
- 自由关键词只对标题、主题、标签和备注做受控模糊匹配。
- 默认稳定排序为 `archived_at DESC, archive_id DESC`。
- `limit` 限制单页数量；`has_more=true` 时使用不透明、可校验的 `next_cursor` 继续，
  不自行解析或修改 cursor。
- 结果返回 `classification` 和 `primary_domain_display_name`。旧记录无法可靠映射时明确显示待整理状态。
- 不请求或展示数据库路径、任务目录和绝对归档路径；需要说明位置时只使用 MCP 返回的
  `学习资料库/` 根目录内安全 `relative_path`。deprecated `library_path` 即使出现也只能是
  同一安全相对路径，不能把它当作服务器绝对路径。
