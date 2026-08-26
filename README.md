# 教育资源 OpenClaw 工作区

用户用自然语言查找、比较、获取和整理教育与学习资源。

```text
用户自然语言
  -> skills/
  -> Host Web Search / mcp/education-resources/
  -> Search / Expand / Inspect / Download / Archive
```

## Active 结构

```text
skills/                              # 用户入口：理解需求、搜索规划、候选判断
mcp/education-resources/              # 唯一 stdio MCP：资源 + 辅助 Session 能力
docs/                                # 当前架构与开发路线
.agent/plans/                         # 当前执行计划
legacy/                               # 只读历史
```

`education-resources` 当前暴露 10 个资源 Tool 和 2 个 Session Tool，共 12 个。Session 只是辅助登录态能力，不是搜索/下载的固定前置流程；只有真实资源能力返回 `AUTH_REQUIRED` 或用户主动管理登录态时才使用。

MCP 不承担 Flow、ResultSet、Presentation、Selection、Plan、Asset、authority/digest 等工作流状态。用户选择和获取意图属于正常对话；后端只保存执行真正需要的临时资源句柄、Expand/Download Job 和平台 SessionStore。

## Web 与专门平台

普通网页发现默认走宿主 Web Search。选中具体 URL 后调用：

```text
resource_import_url(source_url="https://...")
```

Import 会把明确的 Bilibili、Douyin、Ximalaya、SmartEdu、Zjer、CCTV、LibGen、Zhihu URL 交给对应平台能力；无法明确识别的网页按 Generic Web 处理。

Generic Web 下载现在保留原始 `source.html`，再使用 Trafilatura 生成 `index.html` / `content.md` 等可读表示。正文抽取失败不会删除已经取得的源响应。

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

如果用户随后明确说“把第 2 个下载下来”，Agent 直接调用 `resource_download`，不再经过 Selection/Prepare/Token/Start 状态链。

## Skill 语义 baseline

当前语义优化由 `.agent/plans/0074-skill-semantic-decision-kernel.md` 跟踪。为了让 old/new A/B 只改变 Skill 工作区，不改变 runner，本轮先固定旧 Skill 基线：

```text
3a20c1e14358631201e99fb54e007ccfcf118d94
```

在 Windows 上可以先建立只读实验 worktree：

```powershell
git worktree add ..\flow_ver-baseline 3a20c1e14358631201e99fb54e007ccfcf118d94
Copy-Item skills\examples\semantic-baseline-fixtures.example.json .openclaw-test\semantic-fixtures.json
```

然后把 `.openclaw-test\semantic-fixtures.json` 中的占位 URL 换成当前真实可访问的测试资源，再运行：

```powershell
python skills\examples\run_semantic_baseline.py `
  --workspace ..\flow_ver-baseline `
  --expect-head 3a20c1e14358631201e99fb54e007ccfcf118d94 `
  --label baseline-3a20c1e `
  --fixtures .openclaw-test\semantic-fixtures.json
```

runner 使用 `openclaw agent exec` 逐 case 执行独立 Agent turn，只记录原始 JSON、stdout/stderr、测试 worktree commit、模型与 Tool 摘要，不在脚本里给语义质量打分。需要真实多轮上下文或故障注入的 case 会明确跳过，单独人工/会话验收。

结果写入已被 git 忽略的：

```text
.openclaw-test/semantic-baseline/<label>/
```

fixture 只放公开测试 URL，不要写入凭据、Cookie、Token、浏览器档案或下载产物。

## 边界

stdio MCP 是进程边界，不是用户研究工作流。登录凭据保存在 MCP 数据目录下的单一 SessionStore；下载文件写入 Job 工作区。升级自旧独立 session-manager 时不维持双 Store 兼容，已有登录态可能需要重新捕获一次。
