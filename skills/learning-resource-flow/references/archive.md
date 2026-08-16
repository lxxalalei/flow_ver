# 归档

归档是下载后的文件整理能力，不是工作流状态机。

## 分工

- Main Agent：根据资源内容和用户目标判断领域、主题。
- `education-resources` MCP：把下载 Job 已产生的真实文件移动到资料库目录。

调用：

```text
resource_archive(
  job_id=...,
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

只有下载 Job 已经 `succeeded` 或 `partial` 且确实有文件时才归档。分类确实不确定时可以留空 `domain_id`，进入 `99-待分类/其他`。

## 顶层领域

| domain_id | 目录 | 常见主题示例 |
|---|---|---|
| `chinese_language` | 01-语文与中文 | 拼音、阅读理解、写作、古诗词、文言文 |
| `mathematics_reasoning` | 02-数学与思维 | 数与运算、几何、应用题、逻辑推理 |
| `english_foreign_languages` | 03-英语与外语 | 自然拼读、词汇、语法、听说读写 |
| `natural_science` | 04-自然科学 | 动植物、物理、化学、地球环境、天文与宇宙 |
| `humanities_social_studies` | 05-人文与社会 | 历史、地理、传统文化、社会常识 |
| `information_technology` | 06-信息科技 | 计算机、编程、人工智能、网络与安全 |
| `arts_aesthetics` | 07-艺术与审美 | 绘画、书法、音乐、舞蹈、设计 |
| `physical_health` | 08-体育与健康 | 运动、健康、营养、安全常识 |
| `learning_skills` | 09-学习方法与通用能力 | 学习方法、记忆、时间管理、信息检索 |
| `interdisciplinary_practice` | 10-综合实践与跨学科 | STEM、项目式学习、研究性学习、社会实践 |

`topic` 是自由主题目录，不要求必须取示例值。MCP 的实际目录映射以包内 `library-taxonomy.json` 为准。

## 文件目录

归档结果按：

```text
学习资料库/
  顶层领域/
    主题/
      视频|音频|图文|其他/
        实际文件
```

归档只移动文件并返回最终路径。没有 `archive_id`、`AssetBundle`、digest、version、ready state。
