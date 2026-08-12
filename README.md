# 教育资源 OpenClaw 工作区

用户用自然语言查找、比较、获取并归档教育与学习资源。

```text
用户自然语言
  -> skills/learning-resource-flow/
  -> mcp/education-resources/ (stdio MCP)
  -> 搜索 / 核验 / 选择 / 获取 / 归档
```

## Active 结构

```text
skills/learning-resource-flow/       # 唯一用户入口
mcp/education-resources/              # stdio MCP：搜索、获取、归档
docs/                                # 当前架构与开发路线
.agent/plans/                         # 执行计划
legacy/                               # 只读历史
```

## 阅读顺序

1. [docs/CURRENT_ARCHITECTURE.md](docs/CURRENT_ARCHITECTURE.md) — 当前架构事实
2. [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) — 开发路线
3. [.agent/plans/](.agent/plans/) — 执行计划（需要继续开发时进入）

## 开始

```bash
openclaw chat --local
```

例如：

```
帮我找适合小学三年级学习太阳系的中文图文资源，先搜索，不要下载。
```

## 安全边界

stdio MCP 是进程边界不是安全沙箱。不绕过登录、验证码、付费墙、DRM 或访问控制。凭据和下载资产位于源码工作区之外。
