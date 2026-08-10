# CONTEXT.md

本文件只提供教育/学习资源领域的轻量词汇提示，帮助 Agent 保持用户语言一致；它不定义运行时契约，也不承担 Retrieval Authority、Capability Authority 或状态机规范。

严格技术语义分别以以下内容为准：

- 检索事实、SemanticReview、Gap、StopDecision：[`docs/RETRIEVAL_AUTHORITY.md`](docs/RETRIEVAL_AUTHORITY.md)
- MCP 公共状态、Schema、错误码、Capability：[`mcp/education-resources/contracts/`](mcp/education-resources/contracts/README.md)
- 当前实现事实：[`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md)

## 领域词汇

**学习资源（Learning Resource）**  
用于学习、练习、评估、阅读、参考、实验、项目或授课的内容实体。它可以有网页、视频、音频、图书、文档、课程等不同形式，也可以拥有多个可获取的表示。

**主题（Topic）**  
资源具体涉及的学习内容。主题不是完整用户需求，也不是固定一级分类。

**分类（Classification）**  
资源进入资料库后，在固定 taxonomy 版本下形成的领域、主题和辅助维度描述。证据不足时可以保持待整理或未分类。

**主领域（Primary Domain）**  
一份归档学习资源唯一的主要学习领域，使用 taxonomy 中的稳定机器 ID 表达。

**次领域（Secondary Domain）**  
跨学科资源除主领域外涉及的零到多个领域，不与主领域重复。

**集合（Collection）**  
用户为专题整理而建立的可选分组，不改变资源本身的分类事实。

**归档（Archive）**  
已验证 Asset 进入学习资料库并形成可追溯索引关系的结果。归档不是任意文件复制，也不等于下载成功。

**Asset**  
服务端确认并持久化的单个不可变内容表示，拥有稳定 `asset_id`。本地路径不是公共业务状态。

**AssetBundle**  
一个 Job 针对一个 Resource 形成的有序多资产关系。Bundle 是服务端关系，不等于 ZIP、文件夹或文件名约定。

**Primary Asset**  
AssetBundle 中的主要交付物。是否为 primary 由服务端来源与权威链决定，不能靠扩展名、大小或数组位置猜测。

**Companion Asset**  
与同一 Resource 的 primary 配合使用的字幕、封面、元数据、附件、转录等非主资产。

## 用词约束

- 默认产品定位使用“教育资源”“学习资源”“学习资料”，不把系统泛化成儿童全面成长档案或泛成长内容平台。
- 面向用户优先使用自然语言，不暴露 Flow、ResultSet、Plan、Job、Capability Descriptor 等内部术语，除非是在开发/调试语境。
- 若本文件与机器契约或当前架构冲突，以机器契约和当前实现为准，并修正本文件，而不是反向解释代码。
