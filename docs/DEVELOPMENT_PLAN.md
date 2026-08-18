# 开发路线

当前机器事实见 [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)。接下来一轮系统收敛的详细实施计划见 [0058-system-convergence-and-resource-fidelity.md](../.agent/plans/0058-system-convergence-and-resource-fidelity.md)。

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
3. Host Web Search 找到的已接入平台 URL 能进入对应专门 Inspector / Downloader；
4. 用户明确要求下载时，正确资源能产生真实文件；
5. 登录、网络阻断、平台不可用和下载失败按真实原因暴露；
6. 网页资源保存不会把模型阅读预算变成资源本体截断；
7. OpenClaw 能持续完成完整任务，不因为 Tool Result、源码恢复或后端状态反复 compaction / 中断。

## 架构约束

### 1. Agent / Skill 负责语义，MCP 负责能力

Skill / Main Agent 负责：

- 需求理解；
- 搜索任务设计；
- 来源职责；
- 候选判断；
- 内容 Gap / Coverage Gap；
- 停止判断；
- 用户选择；
- 获取意图；
- 归档分类。

MCP 暴露真实能力，不拥有用户研究流程。

当前资源能力包括：

```text
Search
Browse Creator
Import URL
Inspect
Download
Job Status / Cancel
Batch Collect / Read
Archive
```

当前另有独立 Session MCP；0058 计划将其部署边界合回 `education-resources`，但保留 Session 代码职责隔离。

### 2. 后端只保存执行真正需要的状态

保留：

```text
resource_id -> 当前进程内临时资源句柄
job_id      -> 下载 / Batch 的真实运行状态
SessionStore -> 平台必要登录态
```

不恢复 Flow、ResultSet、Presentation、Selection、Plan、Asset、Outcome、authority/binding/digest 或 SQLite workflow 状态。

### 3. 下载链保持直接

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

### 4. Session 不是资源流程前置步骤

只有：

```text
真实资源能力返回 AUTH_REQUIRED
```

或用户主动要求管理登录态时，才进入 Session 能力。

平台存在登录能力，不等于所有 Search / Inspect / Download 都必须登录。

### 5. Provider route 是一次性执行细节

选定哪一个实际 Downloader 就调用哪一个；失败时返回真实失败，不静默切换不等价 Provider。

不建立 provider binding/version/digest/authority snapshot。

### 6. 网页“完整保存”和“模型阅读”分离

网页资源最终保存多少内容，不由模型上下文预算决定。

后续目标：

```text
source snapshot
  -> 内容抽取
  -> sanitized HTML / Markdown / metadata
```

抽取可显式截断给模型阅读；source snapshot 不得因为阅读预算被静默裁掉。

## 当前优先级

### P0 — 系统边界收敛与关键断链接通

按 0058 执行：

1. Session 代码独立、MCP 进程合并；
2. 删除 shared-store bridge / standalone-local 双路径；
3. SessionStore 去掉没有真实价值的 idempotency/fingerprint/replay 复杂度；
4. 浏览器 capture 先筛选再校验 canonical session；
5. Host Web URL Import 恢复明确平台身份。

这一阶段优先级高于继续增加平台。

### P0 — 真实 OpenClaw 闭环

由 [0028-real-openclaw-platform-e2e.md](../.agent/plans/0028-real-openclaw-platform-e2e.md) 持续记录真实用户证据。

重点链路：

```text
自然语言需求
  -> Search / Host Web
  -> Agent 判断
  -> 可选 Inspect / 补搜
  -> 用户选择
  -> Download
  -> JobStatus
  -> 文件
```

以及：

```text
AUTH_REQUIRED
  -> 用户浏览器登录
  -> Session save
  -> 原资源能力重试
```

后端单测不能替代这一层。

### P1 — Web Resource 保真

在当前自研 `web_blocks.py` 基线之上先做真实网页 benchmark，再决定主抽取实现。

目标不是长期多 extractor fallback，而是：

- 保存 source snapshot；
- 正文/标题/列表/表格/代码结构可读；
- 保留重要链接；
- 支持现实 CDN 图片；
- 复杂媒体至少保留引用/元数据；
- 模型阅读预算与资源完整性分离；
- 无法完整保存时显式报告。

### P1 — 检索语义质量

真实闭环稳定后继续评估：

- need reconstruction；
- dispatch design；
- source routing；
- query quality；
- relevance / usefulness / target fit；
- Coverage Gap；
- 补搜与停止。

这些仍属于 Agent / Skill，不新增后端 SemanticReview / Gap / StopDecision 状态。

当前 Skill 先冻结；只有真实 OpenClaw 多个 case 出现同类系统性退化才修改。

### P2 — 平台稳定性与扩展

先修已接入平台真实故障，再考虑新增来源。

新增平台只回答：

```text
怎么搜？
怎么确认真实资源？
怎么下载？
```

没有真实用户需求，不因为 Registry 完整性提前接入。

### P2 — 资料库整理体验

Archive 已是当前真实能力，不再视为“未来才可能增加”的模块。

后续若用户确实需要更强的资料库浏览、重分类、批量整理，再单独增加明确文件整理能力；不提前恢复 Asset / Bundle / Library workflow 状态链。

## 验证原则

- 小改动只跑直接受影响的单元/静态检查；
- 子系统改动跑相关 integration；
- Tool schema 变化做 MCP stdio probe；
- Web 质量用真实样本 benchmark 和人工检查；
- 用户链路变化必须在适用时做真实 OpenClaw；
- 全量回归只在 release / 高风险跨切面改动时考虑。

验证是证据，不是产品规格；不要因为测试方便而改变正确业务行为。