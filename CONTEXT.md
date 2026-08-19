# CONTEXT.md

本文件只提供教育/学习资源领域的轻量词汇提示，帮助 Agent 保持用户语言一致；它不定义运行时 Tool 契约，也不承担工作流状态规范。

当前技术事实优先级：

1. OpenClaw 运行时实际暴露的 MCP Tool schema 与真实返回；
2. `docs/CURRENT_ARCHITECTURE.md`；
3. `skills/learning-resource-flow/SKILL.md` 及 active references；
4. 本文件仅作术语辅助。

## 领域词汇

**学习资源（Learning Resource）**

用于学习、练习、评估、阅读、参考、实验、项目或授课的内容。可以是网页、视频、音频、图书、文档、课程等不同形态。

**候选（Candidate）**

某次搜索或发现得到、尚待 Agent 判断是否适合用户目标的具体资源。候选数量本身不代表目标已经满足。

**表示（Representation）**

同一资源当前可实际检查或获取的具体形态，例如 PDF、MP4、音频或网页。只有真实 Inspection / Provider 事实才能证明某个表示当前可用。

**Gap**

当前结果距离用户目标仍缺少的具体价值或覆盖。可以是内容缺失，也可以是开放式任务中过度集中于单一媒介/来源造成的覆盖盲区。

**Job**

下载或大规模 Batch 等真实长任务的运行身份，用于进度、取消和重启后的状态。Job 不是用户研究流程、选择或计划的持久业务状态。

**归档（Archive）**

把真实下载 Job 已产生的文件整理到学习资料库。分类由 Agent 根据内容语义决定；证据不足时可以进入待分类。

## 用词约束

- 默认产品定位使用“教育资源”“学习资源”“学习资料”，不泛化成儿童全面成长档案。
- 面向用户优先使用自然语言，不暴露 MCP Tool 名、`resource_id`、`job_id`、本地路径等执行细节，除非处于开发/调试语境。
- 不恢复 Flow、ResultSet、Presentation、Selection、Plan、Asset、AssetBundle、authority/digest/binding 等旧架构术语作为 active 业务模型。
- 如果本文件与真实 Tool 返回或当前架构冲突，以运行事实为准并修正本文件。
