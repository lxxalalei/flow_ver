# 开发路线

当前机器事实见 [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)。

## 产品目标

用户通过自然语言完成资源研究与获取：

```text
表达需求
  -> 必要澄清
  -> 搜索
  -> 候选判断 / 必要 Inspect
  -> 展示
  -> 用户选择
  -> 用户明确要求下载
  -> 下载
  -> 得到真实文件
```

成功标准很直接：

1. 搜到的资源符合目标；
2. Agent 能根据真实结果决定补搜、Inspect 或停止；
3. 用户明确要求下载时，正确资源能被实际下载；
4. 登录、不可用、下载失败等情况真实暴露；
5. OpenClaw 不因为后端状态和大 Tool Result 反复 compaction、中断。

## 架构约束

### 1. MCP 是能力层，不是工作流引擎

MCP 只释放：

```text
Search
Browse Creator
Inspect
Download
Job Status
Job Cancel
```

需求理解、搜索策略、相关性、Gap、展示和用户选择由 Skill/Main Agent 处理。

### 2. 后端只保存执行真正需要的状态

当前只保留：

```text
resource_id -> 当前进程内搜索候选
job_id      -> 下载进度 / 文件 / 失败
```

不恢复 Flow、ResultSet、Presentation、Selection、Plan、digest、SQLite migration 等状态模型。

### 3. 下载链直接

```text
用户明确要求下载
  -> resource_download
  -> fresh Inspect
  -> Provider route
  -> Downloader
  -> Job
  -> files
```

没有 Prepare/Token/Start。

### 4. Provider route 是实现细节

不同平台确实需要不同 Downloader，因此保留一次性的 Provider route。

保留的规则：选定哪一个实际 Downloader 就调用哪一个；失败时返回真实失败，不静默换成不等价 Provider。

不保留 provider binding/version/digest/authority snapshot。

### 5. Representation 只是当前下载事实

Inspect 仍需区分：

- primary resource；
- landing page；
- document/video/audio/webpage；
- container / MIME；
- availability / auth required。

但这些事实不持久化成 Resolution 状态机。真正下载前重新 Inspect 即可。

## 当前路线

### P0 — 真实 OpenClaw 闭环

当前最高优先级不是继续搭架构，而是重新跑今天会中断的真实任务：

```text
自然语言需求
  -> Search
  -> Agent 判断
  -> 可选 Inspect / 补搜
  -> 用户选择
  -> Download
  -> JobStatus
  -> 文件
```

重点记录：

- Tool Result 大小；
- 是否触发 compaction；
- Agent 是否还能持续完成一个完整任务；
- 是否出现真实脚本错误；
- 哪个平台需要登录；
- 下载是否产生正确文件。

### P1 — 搜索质量

真实闭环稳定后，再评估：

- relevance；
- 用户目标满足度；
- Gap 判断；
- 补搜是否有效；
- 是否过早停止；
- 不同来源是否真正互补。

这些属于 Agent/Skill 行为，不新增后端 SemanticReview/Gap/StopDecision 状态。

### P1 — 网页资源保存质量

Generic Web 的正文抽取、图片保留、复杂页面处理继续单独评估。它是网页下载能力质量问题，不扩展成整个 MCP 的工作流架构。

### P2 — 平台扩展

新增平台时只回答三个问题：

```text
怎么搜？
怎么确认真实资源？
怎么下载？
```

如果没有真实用户需求，不因为“平台 Registry 完整性”提前接入。

### P2 — 文件整理能力

如果后续用户确实需要“归档/整理资料库”，单独增加一个明确的文件整理能力即可。

不要为了未来可能的 Library/Viewer 需求，提前恢复 Asset/Archive/Bundle/Taxonomy 状态链。

## 验证原则

优先验证真实业务行为。一个改动只跑与其直接相关的测试；不为已删除的架构保留专项门禁，也不让旧测试强迫实现恢复旧状态模型。

真实 OpenClaw 用户链优先级高于 fixture 形式完整度。
