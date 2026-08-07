# Education Resources MCP

本目录是教育资源工作区唯一的执行与权威状态服务。当前 Python stdio MCP 已运行
`contracts/` 的 `1.0.0` 控制面，并且公共 catalog **暴露 12 个工具**。

教育资源主链当前只保留 `contracts/` 的 `1.0.0` 契约；历史 历史 v1 已从工作区清理，迁移差异
保留在 `contracts/compatibility.md` 和 Git 历史中。

权威状态链为：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> Asset -> Archive
```

搜索结果与模型实际展示集合严格分离。Skill 负责语义判断、候选审查和实际展示；MCP 负责所有权威状态、副作用、
幂等和安全校验。

平台登录、Cookie、Token、浏览器会话捕获与本地会话保存由独立 `session-manager` 负责，不属于
education-resources 的 11 工具 catalog。education-resources 不向模型暴露登录秘密。

## 目录

```text
contracts/                  # 当前运行的控制面契约
src/education_resource_mcp/
├── adapters/                  # MCP 内部平台 Adapter
├── server.py                  # stdio MCP 入口
├── service.py                 # 领域服务
├── storage.py                 # SQLite 权威状态
├── jobs.py                    # 异步任务
├── downloader.py              # 受控 HTTP(S) 下载
└── policy.py                  # 网络与路径安全
tests/                         # 单元、契约、安全和 stdio 测试
```

## 本地安装

使用独立虚拟环境，不要安装到系统 Python：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

当前 WSL 开发环境使用：

```text
/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv
```

## 启动

```bash
EDUCATION_RESOURCE_MCP_DATA_DIR=/absolute/path/to/data \
EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR=/absolute/path/to/session-manager-data \
EDUCATION_RESOURCE_MCP_SEARXNG_URL=http://127.0.0.1:8888 \
  .venv/bin/education-resource-mcp
```

stdio 的 stdout 只用于 MCP 协议。诊断日志应写入 stderr，业务文件只写入配置的数据目录。

`EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR` 指向独立 `session-manager` 的数据目录。设置后，
education-resources 会通过 `openclaw-session-manager` 包只读消费同一份安全凭据（Windows 下包括当前用户 DPAPI），
不会维护第二份 Cookie/Token。显式设置该目录但运行环境未安装 `openclaw-session-manager` 时，MCP 会启动失败而不是静默读取空的旧存储。

未设置 `EDUCATION_RESOURCE_MCP_DATA_DIR` 时，默认使用：

```text
~/.local/share/quanxiao/education-resource-mcp-data
```

## 公共工具

暴露以下 12 个工具：

1. `resource_flow_start`
2. `resource_flow_status`
3. `resource_search`
4. `resource_presentation_save`
5. `resource_selection_save`
6. `resource_download_prepare`
7. `resource_download_start`
8. `resource_job_status`
9. `resource_job_cancel`
10. `resource_archive`
11. `resource_library_search`

主流程为：

```text
resource_flow_start
-> resource_search（提交 task_version，filters 使用 SearchFilters 对象）
-> 模型实际展示审查后的 ResultSet 子集
-> resource_presentation_save（允许保存空 Presentation）
-> 用户选择
-> resource_selection_save（只提交当前 Presentation positions）
-> resource_download_prepare（完整绑定 Presentation/Selection，返回 plan_digest）
-> 用户明确确认
-> resource_download_start（提交完整绑定和 plan_digest）
-> resource_job_status / resource_job_cancel
-> resource_archive
-> resource_library_search
```

`resource_flow_status` 可在任意恢复点调用，返回：

```text
current_result_set
current_presentation
current_selection
current_plan
current_job
```

它不会返回 confirmation token/hash、Cookie、Token、数据库路径、临时目录、下载路径或归档本地路径。

完整不变量见 `contracts/domain-contract.md`；历史迁移差异见
`contracts/compatibility.md`；精确工具集合见 `contracts/tool-catalog.json`。

## 学习资料库归档

归档链路只处理学习资料：

```text
ready Asset
-> pending Archive
-> 受控临时文件与内容校验
-> 学习资料库原子落盘
-> ready SQLite 索引
-> resource_library_search
```

### learning-v1 分类

分类注册表以 [`contracts/taxonomy/learning-v1.json`](contracts/taxonomy/learning-v1.json)
为机器单一来源。一级领域 ID 固定为：

| 机器 ID | 中文目录 |
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

`亲子陪伴` 和 `待分类` 都不是领域。新归档在 metadata 中写入：

```json
{
  "classification": {
    "taxonomy_version": "learning-v1",
    "classification_status": "classified",
    "primary_domain": "natural_science",
    "secondary_domains": [],
    "topics": ["天文与宇宙"],
    "material_purposes": ["explanation"],
    "grade_levels": ["小学"],
    "difficulty": "introductory",
    "curriculum_versions": []
  },
  "collection": "太阳系专题",
  "tags": ["科普"],
  "notes": ""
}
```

分类状态为 `classified`、`needs_review` 或 `unclassified`。主领域只有一个，次领域只能从
注册表选择且不能与主领域重复；主题是清洗、去重和限长的受控自由文本。学段、难度和
教材版本只有存在证据时填写。旧平铺 `primary_domain`、`topics`、`source_name` 和旧中文
领域作为 deprecated 输入兼容；无法可靠映射时保留原始元数据并进入 `needs_review`。

### 目录、权威字段与内容去重

标准物理结构为：

```text
学习资料库/<固定中文领域目录>/<主主题>/<视频|图文|音频|其他>/<文件>
```

`needs_review` 和 `unclassified` 使用 `学习资料库/99-待分类/其他/<格式>/`。格式目录由
服务端依据已经验证的媒体类型和扩展名决定，未知格式进入 `其他`。默认文件名为
`[来源]-[标题].[扩展名]`；来源、标题、媒体类型、大小和 SHA-256 来自 Resource/Asset
权威字段，不信任模型提供的来源事实，也不接受客户端本地路径。

内容身份使用 SHA-256、文件大小及必要时媒体类型。不同 Asset 指向同一内容时不重复复制，
但保留每个 Asset 的可追溯归档关系并返回 `deduplicated`。同名不同内容追加稳定短哈希，
不覆盖既有文件。

### SQLite、迁移与恢复

SQLite 通过 `schema_migrations` 使用幂等前向迁移，当前最新版本为 2：v1 记录既有控制面
列迁移，建立学习资料归档基础。旧数据库首次打开时保留现有 Flow、Resource、Job、
Asset、Archive、幂等键和审计记录；旧归档元数据被规范化并建立结构化索引，无法映射的
分类进入 `needs_review`，迁移不移动或批量重命名现有资料文件。

`archive_contents` 按 SHA-256 与文件大小唯一标识物理内容，保存已验证媒体类型、资源格式、
安全相对路径、受控临时相对路径以及 `pending`、`ready`、`failed`、`missing`、`corrupt`
状态。`archive_entries` 保留旧列并增加内容关联、归档状态、分类标量、归档/更新时间和错误；
次领域、主题、资料用途、学段、教材版本和标签分别进入关联表，供精确过滤和索引使用。

归档使用 `pending -> ready` 提交协议：建立待提交索引、写受控临时文件、复核大小和
SHA-256、原子移动，再提交 ready 状态。失败不会产生可检索的 ready 记录；内部对账可重试
遗留 pending，并把索引缺文件标记为 `missing`、内容校验异常标记为 `corrupt`。公共检索只
返回 Archive 与内容均为 ready 且文件存在的记录。

### Library Search

`resource_library_search` 支持 `query`、`taxonomy_versions`、`classification_statuses`、
`primary_domains`、`secondary_domains`、`topics`、`material_purposes`、`grade_levels`、
`difficulties`、`curriculum_versions`、`platforms`、`resource_types`、`resource_formats`、
`collections`、`tags`、`archived_after` 和 `archived_before`。单个字段的多个值采用 OR，
不同字段之间采用 AND；结构化字段精确匹配，关键词仅对标题、主题、标签和备注做受控
模糊匹配。

结果稳定按 `archived_at DESC, archive_id DESC` 排序。`limit` 控制页大小；有下一页时
返回 `has_more=true` 和不可解析、不可修改的签名 `next_cursor`。输出包含 `classification`、
`primary_domain_display_name` 和 `学习资料库/` 内的安全 `relative_path`。deprecated
`library_path` 如为 兼容仍出现，也只能是同一安全相对路径；不返回数据库路径、任务目录
或绝对路径。

## 搜索、下载和登录边界

当前 Generic 和平台搜索 Adapter 已内聚到 MCP 包，不依赖 `legacy/`。下载只允许通过服务端策略校验的 HTTP(S) 来源，
并强制执行网络边界、重定向、大小、内容类型和真实格式校验。

需要认证的平台返回 `AUTH_REQUIRED` 后，应暂停资源状态转换，调用独立 `session-manager` 完成合法登录与会话保存，
再通过 `resource_flow_status` 恢复当前 Flow。不得把 Cookie 或 Token 作为 education-resources 工具参数传递。

## 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

通过 OpenClaw 验证：

```bash
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

成功条件是 doctor 报告 `ok`，probe 精确发现 11 个工具且 `diagnostics=[]`。
