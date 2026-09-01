# OpenClaw 多维度测试报告 0074

- **日期**：2026-08-29
- **工作区 HEAD**：`9db22dc`（codex/growth-resource-taxonomy-rework）
- **部署**：education-resources 0.4.0（同步于 2026-08-29，网关 18789 健康，mcp doctor ok）
- **执行**：venv pytest + OpenClaw CLI agent（--cli direct，deepseek-v4-flash）+ 真实 MCP/Host 环境

## 总览

| 套件 | 定义数 | 执行 | 通过 | 超时 | 跳过 | 耗时 |
|---|---|---|---|---|---|---|
| 单元测试（pytest） | 305 collected | 305 | 304 | 0 | 1 | ~4 min |
| 语义基线 semantic-baseline | 11 | 9 | 9 | 0 | 2（手动模式） | 22.3 min |
| 语义回归 semantic-regression | 32 | 31 | 30 | 1 | 1（手动模式） | 70.9 min |
| 内核定向 semantic-kernel-targeted | 5 | 5 | 5 | 0 | 0 | 9.5 min |
| 能力引出 mcp-capability-elicitation | 18 | 18 | 18 | 0 | 0 | 72.6 min |
| 真实旅程 real-user-journeys | 6 | 4 | 3 全轮次 | 1（1 turn） | 2（缺 fixtures） | ~40 min |
| **合计** | **377** | **372** | **369** | **2** | **6** | |

> 通过 = rc=0 且无 harness 超时；单元测试通过数含 1 skip。

## 语义基线 A/B（current-a0a729c vs current-b668bf9）

| Case | 旧版 | 新版 | 判定 |
|---|---|---|---|
| locate-exact-edition | 找不到在线初版扫描，给未核实候选 | 未找到可继续使用的在线初版扫描，版本证据仍不足 | **大胜** |
| research-open-volcano | 235s | 81s，同质量候选组织 | 提速 3 倍 |
| browse-creator-preview | 画像 4 类 | 27 条视频画像 5 类，不升级全量采集 | 相当/略优 |
| enumerate-container-all | 78 条全枚举 | 78 条 + 发布日期 | 相当 |
| constraint-printable-card | 低年级观鸟卡 | 同候选，推荐理由更清楚 | 相当 |
| transform-known-webpage | 导入+下载+重排归档 | 完整流程 + 自包含确认 | 相当 |
| clarify-textbook-version | 正确澄清教材版本 | 更精简（1 调用） | 相当 |
| research-platform-constrained | 筛真实喷发实拍 | 同质量 | 相当 |

无 Layer A hard invariant 违规。本轮差异面：SKILL.md 大幅收敛重写（c4dcf9d 语义内核收敛 + 3ed59b7 匿名浏览路由）。

## 回归 / 内核 / 能力引出要点

- 判定类（澄清/格式/受众/停止）全部快速合规：topic-missing-clarify 56s、textbook-version-confirm 37s、no-gap-then-stop 93s
- invariant 类合规：download-no-ritual-confirm（不制造仪式性二次确认）、handle-invalidation-recover（对象重定位）、creator-browse-preview-only（浏览不升级枚举）、no-guess-hidden-index、no-fabricated-context-url
- 能力引出 18/18：search/import/expand/browse/inspect/download/job/archive/session/html-design 全工具面覆盖，5 个 case 各 1 次瞬时工具失败均自动恢复

## 发现与修复落点

### ⚠️ 落点 1：B 站 creator 全量枚举超 15 分钟预算（双套件独立复现）
- 回归 `reg-creator-full-enumeration`：harness_timeout 1195s
- 旅程 `creator-browse-then-enumerate` turn-02：harness_timeout 1393s（45 调用、88K input tokens、gateway-fallback 信封）
- 疑似根因：creator 匿名分页风控（412，见 0073 记录）拖慢 expand job 轮询
- 建议：优化 job 轮询节奏/降频、分页限速，或对全量枚举给出渐进式交付

### 覆盖缺口（需真实资源 fixtures）
- `course-expand-select-child`：缺 `COURSE_CONTAINER_URL`（真实课程容器）
- `auth-required-session-resume`：缺 `AUTH_REQUIRED_RESOURCE_URL` + `SESSION_CAPTURE_JSON`（登录态资源 + 会话捕获）

## 证据位置

- 语义/回归/内核/能力：`.openclaw-test/semantic-baseline/{current,regression,kernel,capability}-a0a729c/`（每 case：request.txt / stdout.json / stderr.txt / meta.json + manifest.json）
- 旅程：`.openclaw-test/real-user-journeys/journey-a0a729c-*/`（含 real-user-journey-report.md）
- 本次全部产物在 gitignore 的 `.openclaw-test/`，不进版本库

