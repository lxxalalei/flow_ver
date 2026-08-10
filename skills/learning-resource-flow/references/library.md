# Library Guidance

本文件负责 Asset/AssetBundle 进入学习资料库后的归档、分类、用户可理解的本地目录视图和再次查找语义。

## 基本对象

- **Resource**：用户想获得和使用的逻辑内容实体；
- **Representation**：Resource 的一种可获取表示；
- **Asset**：服务端已验证并持久化的单个内容表示，拥有稳定 `asset_id`；
- **AssetBundle**：同一 Job、同一 Resource 的有序多资产关系；
- **Archive**：已验证 Asset 进入资料库并形成可检索关系的结果。

本地绝对路径、ZIP、文件名和扩展名都不是公共业务身份；但服务端返回的资料库安全相对路径是归档结果的一部分，可以用于向用户说明资料存放位置。

## 归档前提

`resource_archive` 只接受 MCP 已生成并验证、属于合法 Job/Outcome 的 `asset_id`。模型不能提交任意本地文件路径或把未完成 Job 的临时文件归档。

Bundle 中 primary / subtitle / cover / metadata / attachment / transcript / companion 等角色由服务端事实决定，不靠文件名猜测。

只有 `resource_archive` 返回成功后，才能向用户说明“已归档”“已去重”或具体资料库相对位置；不要根据聊天记忆、预期目录或本地文件存在性自行宣称归档完成。

## 分类

当前资料库使用机器 taxonomy 作为稳定分类注册表。机器权威见 [`contracts/taxonomy/learning-v1.json`](../../../mcp/education-resources/contracts/taxonomy/learning-v1.json)；Skill 不复制或维护第二份领域 ID、目录名、枚举和长度上限。

分类时根据当前 Resource/Asset 的真实内容证据和用户已明确提供的信息，按契约允许的字段表达：

- `primary_domain`：唯一主要领域；
- `secondary_domains`：零到多个跨学科领域；
- `topics`：具体学习主题；
- `material_purposes`：有证据支持的资料用途；
- `grade_levels`：只有内容或用户明示能支持时填写；
- `difficulty`：只有证据足够时填写；
- `curriculum_versions`：只在确有教材/版本证据时填写；
- `collection` / `tags` / `notes`：用于用户专题和辅助检索，不改变领域事实。

证据不足时使用服务端允许的 `needs_review` / `unclassified` 语义，不为了填满字段随意猜测，也不为了归档补问与当前使用无关的年龄、年级或版本。

资源语义类型与物理资产格式不要混淆：book/video/article/course 是 Resource 语义；PDF/EPUB/MP4/HTML 等是 Representation/Asset 层事实。

## 本地目录视图

资料库不是“只写 SQLite 的抽象索引”。当前 MCP 会把已经验证的 Asset 发布到配置的本地 library root，并由服务端根据机器 taxonomy、分类结果和真实媒体事实生成安全相对目录。

概念上的目录形态是：

```text
学习资料库/
└── <主领域目录或待分类>/
    └── <主主题或其他>/
        └── <图文 / 视频 / 音频 / 其他>/
            └── <服务端生成的安全文件名>
```

具体领域目录、待分类目录和 taxonomy 版本以机器契约为准，不在 Skill 中硬编码第二份清单。媒体目录由服务端根据已验证的 MIME/扩展名等事实决定；标题、来源、扩展名和同名冲突处理也由 MCP 负责。

Skill 的职责是：

1. 基于证据给出正确的分类语义，而不是设计路径；
2. 不提交本地绝对路径、文件名、格式目录或手工拼出的 `relative_path`；
3. 归档成功后，只使用 MCP 返回的安全相对路径向用户说明位置；
4. `needs_review` / `unclassified` 时明确告诉用户“已归档，但分类待整理”，不要说成分类完成。

本地目录是 Archive 的用户可理解物理视图，不是另一套业务 source of truth。Archive 状态、分类元数据、Asset 关系和去重事实仍以服务端 SQLite / MCP 返回为准。

## 多资产

同一 Resource 可以有多个 Asset，例如：

```text
Video Resource
├── MP4 primary
├── subtitle
├── cover
└── metadata
```

```text
Web Resource
├── local HTML primary/representation
├── Markdown
├── images
└── metadata
```

Bundle 是关系，不等于压缩包。底层可以使用 bundle package 存储，但面向用户的 Viewer 应优先打开实际 primary representation，而不是要求用户理解存储容器。

归档仍按服务端返回的 ready Asset 执行。一个 Bundle 的 companion/attachment 是否需要一起归档，应根据用户目标和服务端真实 Bundle 关系判断，不能虚构“Bundle 原子归档”能力。

## 再次查找

`resource_library_search` 只查询已归档的服务端事实。面向用户可以按主题、分类、资源类型、来源、用途、学段/版本、collection/tag 等契约实际支持的字段解释结果，但不要根据聊天记忆伪造“已经归档”。

结构化过滤、分页和稳定排序以当前 Tool Schema/服务端返回为准，不在 Skill 中复制字段上限、排序规则或 cursor 结构。需要继续翻页时只使用 MCP 返回的不透明 cursor。

用户询问“文件在哪”时，只展示服务端返回的资料库安全相对路径；不暴露数据库路径、任务目录、staging 目录或服务器绝对路径。

## 去重与状态

保持三层去重语义分离：

1. Candidate：canonical URL / native ID；
2. Resource identity：ISBN / DOI / native ID / 保守 fingerprint；
3. Asset content：SHA-256 + size 等内容事实。

不要因为两个文件内容相似就自动把两个不同版本的 Resource 合并。

服务端可能复用已有物理内容并返回 `deduplicated=true`；这表示内容去重成功且当前 Asset/Archive 关系仍被保留，不表示本次归档被忽略。归档失败或仍处于未完成状态时，不把 staging/pending 文件描述成可用资料。
