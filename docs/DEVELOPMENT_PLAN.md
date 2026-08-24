# 开发路线

当前机器事实见 [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)。历史系统收敛实施记录已归档至 [0058-system-convergence-and-resource-fidelity.md](../.agent/plans/archive/0058-system-convergence-and-resource-fidelity.md)；当前路线只看 0067、0028 与 0068。

## 产品目标

用户通过自然语言完成资源研究与获取：

```text
表达需求
  -> 必要澄清
  -> 设计搜索任务
  -> Host Web / 专门平台搜索
  -> 候选判断 / 必要 Inspect
  -> 用户选择
  -> 用户明确要求下载
  -> 下载 Job
  -> 真实文件
  -> 可选归档
```

成功标准：

1. 搜到的资源符合真实目标，而不是只关键词命中；
2. 开放式任务能覆盖主要学习价值，不因为几个同类结果过早停止；
3. Host Web 找到的已接入平台 URL 能进入对应专门 Inspector / Downloader；
4. 用户明确要求下载时，正确资源能产生真实文件；
5. 登录、网络阻断、平台不可用和下载失败按真实原因暴露；
6. 网页正文抽取不会改变或裁掉已取得的原始网页资源；
7. OpenClaw 能持续完成完整任务，不因为 Tool Result、源码恢复或后端状态反复 compaction / 中断。

## 当前架构约束

### Agent / Skill 负责语义，MCP 负责能力

Skill / Main Agent 负责需求理解、搜索任务、来源职责、候选判断、Gap、停止、用户选择、获取意图和归档分类。

当前唯一 active MCP 为 `education-resources`，暴露：

```text
9 个资源 Tool
+ 2 个 Session Tool
```

Session 不是资源流程前置步骤。只有真实 `AUTH_REQUIRED` 或用户主动管理平台会话时才使用。

### 后端只保存执行真正需要的状态

```text
resource_id  -> 当前进程内临时资源句柄
job_id       -> Download / Expand 的真实运行状态
SessionStore -> 平台必要登录态
```

不恢复 Flow、ResultSet、Presentation、Selection、Plan、Asset、Outcome、authority/binding/digest 或 SQLite workflow 状态。

### 下载链保持直接

```text
用户明确要求下载
  -> resource_download
  -> fresh Inspect
  -> exact Provider route
  -> Downloader
  -> Job
  -> files
```

没有 Prepare / Token / Start。

### Generic Web 当前路线

```text
BoundedWebFetcher
  -> source.html
  -> Trafilatura
       -> index.html
       -> content.md
       -> metadata.json
```

本轮已经放弃“先建设完整 extractor benchmark 再决定主实现”的路线，也不再扩展自研 Block IR。当前先直接使用成熟 Trafilatura；如果以后真实需求要求自包含离线网页，再单独评估 Monolith。

## 当前优先级

### P0 — 完成统一能力面验收

当前唯一主路线是 [0067-resource-capability-surface-unification.md](../.agent/plans/0067-resource-capability-surface-unification.md)：先让 active 文档、Tool schema、平台对象与最小充分验证统一到 Search / Expand / Inspect / Download。CCTV 是同一路线下的专项扩展，记录在 [0068-cctv-platform-integration.md](../.agent/plans/0068-cctv-platform-integration.md)，不形成第二套公共能力。

0067 的静态与 targeted 验收完成后，由其验收子计划 [0028-real-openclaw-platform-e2e.md](../.agent/plans/0028-real-openclaw-platform-e2e.md) 统一记录真实 OpenClaw、平台、Session 与 Job durability 证据。0028 不定义第二套架构，只验证 0067 的当前能力面。

重点复测：

```text
Host Web -> 已接入平台 URL -> Import -> 专门 Inspector/Downloader
SmartEdu 已保存 session -> 公共 Search 仍匿名
LibGen -> 不触发登录
AUTH_REQUIRED -> Session save -> 原资源能力重试
Generic Web -> source.html + readable views
Douyin 长任务 -> 是否仍 compaction/中断
```

后端单测不能替代这一层。

### P1 — 已有平台稳定性

根据真实 OpenClaw 失败修已接入平台的 Search / Inspect / Download，不继续用新架构掩盖具体平台错误。

新增平台只回答：

```text
怎么搜？
怎么确认真实资源？
怎么下载？
```

没有真实用户需求，不因为 Registry 完整性提前接入。

### P1 — 检索语义质量

真实闭环稳定后继续观察：

- need reconstruction；
- dispatch design；
- source routing；
- query quality；
- relevance / usefulness / target fit；
- Coverage Gap；
- 补搜与停止。

这些仍属于 Agent / Skill，不新增后端 SemanticReview / Gap / StopDecision 状态。

当前 Skill 先冻结；只有真实 OpenClaw 多个 case 出现同类系统性退化才修改。

### P2 — Web Resource 后续需求

当前先使用 raw `source.html` + Trafilatura readable views。

只有出现明确用户需求时再评估：

- Monolith：自包含单 HTML 离线保存；
- 更复杂动态网页的浏览器渲染；
- 关联附件/媒体的额外获取。

不要预先引入 SingleFile/Chromium/ArchiveBox 或多 extractor fallback。

### P2 — 资料库整理体验

Archive 已是当前真实能力。后续若用户确实需要更强的资料库浏览、重分类、批量整理，再单独增加明确文件整理能力；不提前恢复 Asset / Bundle / Library workflow 状态链。

## 验证原则

- 小改动只跑直接受影响的单元/静态检查；
- 子系统改动跑相关 integration；
- Tool schema 变化做 MCP stdio/tool probe；
- 第三方库集成先核官方 API，再做少量代表性 fixture；
- 用户链路变化必须在适用时做真实 OpenClaw；
- 全量回归只在 release / 高风险跨切面改动时考虑。

验证是证据，不是产品规格；不要因为测试方便而改变正确业务行为。
