# 学习资料归档体系基础重构

- 状态：completed
- 创建日期：2026-08-06
- 完成日期：2026-08-06
- 范围：`Asset -> Archive -> 学习资料库目录 -> SQLite 归档索引 -> Library Search`，以及 active Skill 的归档规则、v2 兼容迁移、恢复测试和归档文档

## 目标与边界

本计划把归档对象收敛为“学习资料”，建立稳定机器分类、受控物理目录、内容级去重、
可重试归档状态机、结构化 SQLite 索引和稳定游标检索。只修改 active
`skills/learning-resource-flow/`、`mcp/education-resources/`、本计划和必要的架构文档；
不扩展搜索 Adapter、Session、Cookie、下载器、ResultSet/Presentation/Selection、
OpenClaw UI、legacy Skill、推荐排序或完整儿童成长体系。

## 审计结论

- 分支为 `codex/growth-resource-taxonomy-rework`，远端为 `lxxalalei/flow_ver`，修改前 tracked 工作树干净。
- Archive 正式 Schema 与 Pydantic/tools/list 漂移；Library Search 的 Schema、模型、SQL 和 cursor 行为不一致。
- 当前 `archive_entries` 没有 Schema version、归档状态、内容实体或结构化分类索引；分类、主题、标签和 collection 主要依赖 `metadata_json LIKE`。
- 当前文件先落盘后写 SQLite，没有 pending/ready 提交协议、跨 Asset 内容去重或对账恢复；未知格式错误进入“图文”。
- 当前 Library Search 返回绝对路径，不实现已声明的 cursor，也没有稳定次排序和 ready/文件存在性保护。
- 当前 Skill 仍使用“成长资料库”、旧中文领域、“亲子陪伴”“综合主题”“待确认”等一级分类，且入口没有要求归档前读取结构说明。
- 没有阻止实施的实质性障碍。环境缺少 `python` 命令和项目依赖是验证条件，不阻止使用 `python3` 与仓库现有依赖边界实施。

## 契约兼容决策

- 保持 v2 主契约和现有 `contract_version=2.0.0` 调用，不删除已出现的 `title`、`collection`、`tags`、`notes`、`primary_domain`、`topics`、`source_name`。
- 新调用采用嵌套 `classification`；旧平铺字段只作为 deprecated 兼容输入，统一规范化为 `learning-v1`。冲突输入拒绝，无法映射的旧值进入 `needs_review` 并保留原始元数据。
- 新 Library 输出在 v2 内增加结构化分类、中文展示名和安全相对路径。因为现有 Schema 使用 `additionalProperties: false`，旧严格输出校验器可能不接受新增字段；这是已知的 v2 shape 扩展风险，不描述为完全无感兼容。仓库目前没有已知外部固定 Schema 消费者；若后续存在，应单独引入版本协商而不是静默改义。
- 同一过滤字段中的多个值采用 OR，不同字段之间采用 AND；关键词只对标题、主题、标签和备注做受控模糊匹配，结构化维度全部精确匹配。
- 新文件写入统一使用 `learning-v1`；迁移不移动、删除或批量重命名现有文件。

## 步骤

- [x] completed：只读检查 AGENTS、分支、工作树、0014/0015、计划规范、开发路线、现有契约/实现/Skill 和修改前测试基线
- [x] completed：建立唯一 `learning-v1` taxonomy 注册表、Python 分类模型、v2 Archive/Library Schema 和跨层一致性测试
- [x] completed：实现带明确 Schema version 的幂等 SQLite 前向迁移、内容实体、归档状态和结构化关联索引，并覆盖旧数据库迁移
- [x] completed：重构文件目录生成、权威命名、格式识别、路径/符号链接安全、内容级去重及 pending -> ready 原子提交与对账恢复
- [x] completed：实现只读 ready 资料的精确多维过滤、关键词查询、稳定排序和签名不透明 cursor 分页，移除绝对路径输出
- [x] completed：重写学习资料库 Skill 规则，补充领域术语、MCP/README/兼容说明和开发路线的真实状态
- [x] completed：补齐分类、目录、去重、故障注入、迁移、检索、Schema 和完整 archive -> library_search 测试，并由根 Agent 做跨层集成修复
- [x] completed：运行完整可行验收、记录 OpenClaw 可用性与未执行项、确认工作树并完成本计划

## 修改前基线

- `python -m compileall -q src tests`：退出 127，当前系统没有 `python` 命令。
- `python -m unittest discover -s tests -v`：退出 127，原因相同。
- 等价 `python3 -m compileall -q src tests`：通过，退出 0。
- 等价 `python3 -m unittest discover -s tests -v`：退出 1，运行 82 项；77 通过、2 失败、1 error、2 skipped。
- 既有 error：缺少 `pydantic`，`test_contract_outputs` 无法导入。
- 既有 2 项失败：macOS `/var` 与 `/private/var` 临时目录别名断言。
- 既有 2 项 skipped：未安装 `mcp`，stdio 测试跳过。

## 验证

- JSON 全量解析和 `$ref`/本地文件引用检查。
- taxonomy 注册表、JSON Schema、Pydantic、tools/list 和中文目录映射一致性测试。
- `python3 -m compileall -q src tests`。
- `python3 -m unittest discover -s tests -v`，并与修改前既有失败逐项对比。
- Archive、路径安全、内容去重、故障注入、pending 对账、Library Search 游标和迁移定向测试。
- 最小 `archive -> library_search` 结果通过 v2 输出 Schema。
- Markdown 本地链接和文件存在性检查。
- `git diff --check` 与 `git status --short --branch`。
- 若当前环境存在可用 OpenClaw 和依赖，再运行 MCP config validate、status、doctor/probe 和最小归档检索回合；否则明确记录未执行原因，不复用历史结果。

## 结果

- 已完成 `learning-v1` 十领域注册表、嵌套归档分类、固定中文目录、服务端权威命名、
  真实格式识别、内容级去重、`pending -> ready` 提交和启动对账恢复。SQLite 最新 Schema
  version 为 2，旧归档原始字段与文件保持不变，已知中文领域回填机器 ID，未知值进入
  `needs_review`。
- Library Search 只查询 Archive、内容和 Asset 均为 `ready` 的记录；结构化维度精确过滤，
  同字段 OR、跨字段 AND，关键词只模糊匹配标题、主题、标签和备注；排序固定为
  `archived_at DESC, archive_id DESC`，使用与过滤条件绑定的 HMAC 签名 keyset cursor。
- 使用临时隔离 venv 补齐当前机器缺少的项目依赖后，`python -m compileall -q src tests`
  通过，`python -m unittest discover -s tests -v` 运行 123 项并全部通过；分类、路径、归档
  服务、迁移和 SQLite 检索定向测试运行 39 项并全部通过。
- 16 个 v2 JSON 文件解析和 Schema 自检通过，296 个 `$ref` 本地引用无缺失；11 个修改中
  Markdown 文件的本地链接检查无缺失；新建 SQLite 为 version 2，并发现 15 个归档常用
  索引；`git diff --check` 通过。
- 当前 macOS 环境没有 `openclaw` 命令，因此没有运行本次 OpenClaw config validate、status、
  doctor/probe 或 OpenClaw 进程级归档回合；没有沿用开发路线中记录的历史验证结果。本地
  stdio MCP 契约测试和完整 archive -> library_search 服务回合均已通过。
- 未创建分支、提交、推送或 PR；用户原有修改均保留。
