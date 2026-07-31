# 工作区双核心整理

- 状态：completed
- 创建日期：2026-07-30
- 完成日期：2026-07-30
- 范围：根工作区、`skills/`、本地 MCP、契约、legacy 兼容代码、OpenClaw 注册与文档

## 目标

把当前 OpenClaw 开发工作区收敛为两个 active 产品部分：

```text
skills/learning-resource-flow/   # 唯一对话入口
mcp/education-resources/         # 本地 stdio MCP、契约、Adapter、状态和测试
```

旧六阶段 Skill 及其未提交修改移动到 `legacy/skill-pipeline-v1/skills/`，只用于审计、对照和显式回滚，
不再位于 active Skill 发现目录。MCP 不再依赖 legacy 目录中的 Generic Adapter。

## 步骤

- [x] completed：盘点当前工作树、跨目录硬编码路径和 OpenClaw 注册。
- [x] completed：建立迁移前外部备份并记录目标目录映射。
- [x] completed：迁移 MCP 与契约，内聚 Generic 搜索 Adapter，修复代码和测试路径。
- [x] completed：精简 active Skill，把旧六阶段实现隔离到 `legacy/skill-pipeline-v1/skills/`。
- [x] completed：更新 AGENTS、README、开发计划和 OpenClaw MCP 注册。
- [x] completed：清理受控缓存产物并运行 Skill、Python、MCP、OpenClaw 和文档验证。
- [x] completed：将本计划全部结清并记录剩余风险。

## 目标目录

```text
.
├── skills/
│   └── learning-resource-flow/
├── mcp/
│   └── education-resources/
│       ├── pyproject.toml
│       ├── README.md
│       ├── contracts/v1/
│       ├── src/education_resource_mcp/
│       │   └── adapters/
│       └── tests/
├── legacy/
│   └── skill-pipeline-v1/skills/
├── docs/
└── .agent/
```

## 安全与回滚

- 移动前在仓库外创建带时间戳的工作树备份，不包含 `.git/`、运行缓存或下载数据。
- 当前备份：`/home/admin_quanxiao/.local/share/quanxiao/workspace-backups/collector-flow-ver-pre-two-part-cleanup-20260730.tar.gz`。
- 保留所有旧 Skill 的现有内容和未提交修改，不执行格式化、重置或丢弃。
- 不恢复当前被删除的 `.gitignore`；缓存只按已确认的精确目录清理。
- MCP 注册切换失败时可用备份配置和 legacy 目录恢复旧路径。
- OpenClaw 默认 `main` Agent 已绑定本工作区与唯一 Skill；旧
  `education-resources-dev` 条目已从配置退役，但其用户级会话目录未删除。

## 验证

- Skill frontmatter 与结构校验。
- MCP Python 语法、完整单元测试、stdio 协议和契约测试。
- `openclaw config validate`、`mcp status`、`mcp doctor --probe`、`mcp probe --json`。
- 默认模型最小 Agent 回合，确认工作区只发现 `learning-resource-flow` 且仍能加载 9 个 MCP 工具。
- Markdown 链接、文件存在性、尾随空白和可执行范围内的 `git diff --check`。

## 结果

- active 业务代码已收敛为 `skills/learning-resource-flow/` 与
  `mcp/education-resources/` 两部分；顶层 `skills/` 只有一个 `SKILL.md`。
- MCP 的 `contracts/v1/`、Generic Web Adapter、HTTP helper、源码和测试已经内聚到
  服务目录，运行时不再依赖 legacy Skill。
- 迁移前七个 Skill 与未提交修改完整保存在
  `legacy/skill-pipeline-v1/skills/`；与外部备份逐文件比较一致。
- active Skill 已去除 Stage manifest、脚本路径、旧内部 Skill 和 legacy fallback，
  只保留自然语言对话、9 工具编排、确认边界、错误恢复和用户响应规范。
- OpenClaw MCP cwd 与 editable install 已切到新路径。默认 `main` Agent 已成为
  `education-resources`，用户可直接运行 `openclaw chat --local`。
- Gateway 明文 token 已迁移到权限 `600` 的 File SecretRef；Secret 审计为 clean。
- 清理了所有已定位的 `__pycache__`、`.pyc`、`.pytest_cache` 和源码 egg-info；未恢复
  用户删除的 `.gitignore`。

## 验证结果

- Skill `quick_validate.py`：通过。
- 两个独立子 Agent 对搜索与“修改选择后不得沿用旧计划”场景的前向测试：通过。
- MCP 语法检查：通过。
- MCP `unittest`：28 项通过。并行验证时曾有 1 项 Job 测试超过内部 3 秒轮询窗口；
  目标用例和完整套件顺序复跑均通过，未修改业务超时。
- `openclaw config validate`：通过。
- Gateway health：正常，默认 Agent 为 `main`。
- `openclaw secrets audit`：clean，明文和未解析引用均为 0。
- MCP doctor：`education-resources: ok`。
- MCP probe：9 个工具，`diagnostics=[]`。
- 真实 GLM Agent smoke：加载唯一 Skill 和 9 个 MCP 工具，实际调用
  `resource_flow_start` 成功，未使用 fallback，未搜索、下载或归档。
- Markdown：检查 67 个文件，本地链接全部存在；`git diff --check` 通过。

## 剩余风险

- 当前只启用 Generic 公开网页搜索和公开 HTTP(S) 下载；旧平台代码在 legacy 中，
  尚未按 MCP Adapter 契约逐个平台迁移。
- Legacy 对等测试、数据导入导出和完整回滚演练尚未完成。
- `.gitignore` 仍处于用户删除状态；后续测试可能重新生成缓存，提交前需继续检查。
- 旧 `education-resources-dev` Agent 的用户级会话目录为回滚保留，本次只从配置中退役，
  未执行不可恢复删除。
