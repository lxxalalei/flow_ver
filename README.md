# 教育资源 OpenClaw 工作区

用户用自然语言查找、比较和下载教育与学习资源。

```text
用户自然语言
  -> skills/learning-resource-flow/
  -> mcp/education-resources/ (stdio MCP)
  -> 搜索 / 必要检查 / 下载
```

## Active 结构

```text
skills/learning-resource-flow/       # 用户入口：理解需求、搜索规划、候选判断
mcp/education-resources/              # stdio MCP：释放搜索/Inspect/下载脚本能力
docs/                                # 当前架构与开发路线
.agent/plans/                         # 当前执行计划
legacy/                               # 只读历史
```

MCP 不再承担 Flow、ResultSet、Presentation、Selection、Plan、Archive 等工作流状态。用户选择和确认属于正常对话；后端只保存调用脚本真正需要的轻量资源句柄和下载 Job。

## 阅读顺序

1. [docs/CURRENT_ARCHITECTURE.md](docs/CURRENT_ARCHITECTURE.md)
2. [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)
3. [.agent/plans/](.agent/plans/)

## 开始

```bash
openclaw chat --local
```

例如：

```text
帮我找适合小学三年级学习太阳系的中文图文资源，先搜索，不要下载。
```

如果用户随后明确说“把第 2 个下载下来”，Agent 直接调用 MCP 的 `resource_download`，不再经过 Selection/Prepare/Token/Start 状态链。

## 边界

stdio MCP 是进程边界，不是安全沙箱。登录凭据由独立 SessionStore 管理；下载文件写入 MCP 数据目录的 Job 工作区。
