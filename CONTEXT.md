# 学习资料归档上下文

本上下文描述学习资料从已验证资产进入资料库、被分类和再次检索时使用的统一语言。

## Language

**学习资料（Learning Resource）**:
用于学习、练习、评估、阅读、参考、实验、项目或授课的可归档内容。
_Avoid_: 儿童全面成长档案、成长资料

**分类（Classification）**:
一份学习资料在固定分类版本下的领域、主题和辅助学习维度描述；证据不足时可以明确待整理或未分类。
_Avoid_: 目录名、标签集合

**主领域（Primary Domain）**:
一份学习资料唯一的主要学习领域，使用分类注册表中的稳定机器 ID 表达。
_Avoid_: 成长领域、使用场景、文件格式

**次领域（Secondary Domain）**:
跨学科学习资料除主领域外涉及的零到多个注册领域，不得与主领域重复。
_Avoid_: 第二主领域、综合主题

**主题（Topic）**:
受控自由文本表达的具体学习内容；一份资料可以有多个主题，其中首个主题用于物理组织。
_Avoid_: 完整自然语言需求、一级领域

**集合（Collection）**:
用户为专题整理而定义的可选资料分组，不改变资料的主领域和主题。
_Avoid_: 一级领域、分类兜底

**归档（Archive）**:
一次已验证 Asset 进入学习资料库并形成可追溯索引关系的结果。
_Avoid_: 任意文件复制、下载成功

**归档内容（Archived Content）**:
由内容指纹识别的一份物理资料内容；多个 Asset 可以关联同一份归档内容。
_Avoid_: Asset、Archive Entry

**归档记录（Archive Entry）**:
一个 Asset 与归档内容、分类和归档时间之间的可检索关系。
_Avoid_: 物理文件、SQLite 行

## 检索与评估语言

**搜索方向（SearchDirection）**:
为覆盖一个明确的学习目标、使用结果或决策缺口而选择的探索路线；描述要获得的价值或证据，不等同于查询词、平台或资源类型。
_Avoid_: 搜索词、平台路线、关键词角度

**检索轮次（SearchRound）**:
在一次当前决策下，针对一个或多个搜索方向完成并统一评估的一组有界检索。
_Avoid_: 查询次数、分页、结果集版本

**覆盖度（Coverage）**:
当前候选与核验证据对任务必要维度的满足程度，不能简化为结果数量或相关性分数。
_Avoid_: 结果数量、召回率、结果集大小

**缺口（Gap）**:
尚未满足或尚未验证，并且可能改变下一步搜索、推荐或获取决策的必要条件。
_Avoid_: 任意未知、任意失败、低分

**信息增益（InformationGain）**:
一轮检索实际新增的决策价值，包括关闭关键缺口、新增可展示候选或新增互补来源。
_Avoid_: 新鲜度、关键词命中、去重数量

**停止决策（StopDecision）**:
一次评估后对继续重规划、向用户澄清、进入展示或带缺口停止所作的明确结论。
_Avoid_: 搜够了、没有更多结果、任务结束

**重规划（Replan）**:
根据覆盖度、缺口和信息增益调整后续搜索方向或来源路线，同时保留原目标和显式约束。
_Avoid_: 重试、换近义词、翻下一页、重新理解用户

## 获取与多资产语言

**采集产物（Artifact）**:
一次 Acquisition 尝试产生、尚未进入权威状态的单个受控文件描述；只有通过路径、大小、
媒体类型、魔数和摘要校验后才能晋升为 Asset。
_Avoid_: Asset、公开业务 ID、任意本地文件

**资产（Asset）**:
服务端确认并持久化的单个不可变内容表示，拥有稳定 `asset_id`；本地路径不属于公共状态。
_Avoid_: Artifact、Resource、归档内容

**资产包（AssetBundle）**:
一个 Job 针对一个 Resource 产生的有序多资产结果；Bundle 是权威关系，不等于 ZIP 文件。
完整或可用的部分结果必须有且只有一个 primary。
_Avoid_: Job 的全部 Asset、压缩包、文件夹

**资产包项（BundleItem）**:
AssetBundle 中一个预期位置的权威成员关系；成功项绑定一个 Asset，失败项不伪造 Asset，
但保留角色、顺序和失败事实。
_Avoid_: Asset 本身、文件名推断、数组下标

**资产角色（AssetRole）**:
服务端根据来源事实赋予 BundleItem 的受控语义：`primary`、`subtitle`、`cover`、
`metadata`、`attachment`、`transcript` 或 `companion`。不能仅靠文件名推断。
_Avoid_: MIME 类型、扩展名、展示标签

**主资产（Primary Asset）**:
AssetBundle 的唯一主要交付物；它决定该 Bundle 是否形成可用结果，但不代表所有 companion
都成功。
_Avoid_: 第一个文件、最大文件、ZIP

**伴随资产（Companion Asset）**:
与同一 Bundle 的 primary 共同使用的非主资产，包括更具体的字幕、封面、元数据、附件和
转录角色；不得跨 Resource 或跨 Job 关联。
_Avoid_: 独立 Resource、任意额外文件

**部分失败（PartialFailure）**:
Bundle 已有可用 primary 和至少一个成功成员，同时一个或多个预期成员失败的持久化结果；
每项失败必须保留稳定错误码、角色、顺序和 retriable 事实，不能伪装为完整成功。
_Avoid_: Job 崩溃、primary 失败、警告文本
