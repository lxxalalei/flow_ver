# Library Guidance

本文件负责 Asset/AssetBundle 进入学习资料库后的归档、分类和再次查找语义。

## 基本对象

- **Resource**：用户想获得和使用的逻辑内容实体；
- **Representation**：Resource 的一种可获取表示；
- **Asset**：服务端已验证并持久化的单个内容表示，拥有稳定 `asset_id`；
- **AssetBundle**：同一 Job、同一 Resource 的有序多资产关系；
- **Archive**：已验证 Asset 进入资料库并形成可检索关系的结果。

本地路径、ZIP、文件名和扩展名都不是公共业务身份。

## 归档前提

`resource_archive` 只接受 MCP 已生成并验证、属于合法 Job/Outcome 的 `asset_id`。模型不能提交任意本地文件路径或把未完成 Job 的临时文件归档。

Bundle 中 primary / subtitle / cover / metadata / attachment / transcript / companion 等角色由服务端事实决定，不靠文件名猜测。

## 分类

当前资料库使用机器 taxonomy 作为稳定分类注册表。分类时区分：

- `primary_domain`：唯一主要领域；
- `secondary_domains`：零到多个跨学科领域；
- `topics`：具体学习主题；
- `collection`：用户可选专题分组，不改变分类事实。

证据不足时允许待整理/未分类，不为了填满字段随意猜测。

资源语义类型与物理资产格式不要混淆：book/video/article/course 是 Resource 语义；PDF/EPUB/MP4/HTML 等是 Representation/Asset 层事实。

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

## 再次查找

`resource_library_search` 只查询已归档的服务端事实。面向用户可以按主题、分类、资源类型、来源等条件解释结果，但不要根据聊天记忆伪造“已经归档”。

## 去重

保持三层去重语义分离：

1. Candidate：canonical URL / native ID；
2. Resource identity：ISBN / DOI / native ID / 保守 fingerprint；
3. Asset content：SHA-256 + size 等内容事实。

不要因为两个文件内容相似就自动把两个不同版本的 Resource 合并。
