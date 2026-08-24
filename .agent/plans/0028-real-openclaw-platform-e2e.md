# 0028 — 真实 OpenClaw 与真实平台验收

- 状态：in_progress
- 创建日期：2026-08-08
- 更新日期：2026-08-25
- 父计划：[0067-resource-capability-surface-unification.md](0067-resource-capability-surface-unification.md)
- 范围：真实 Agent / 用户链路、真实平台网络行为、Session 登录恢复、Job durability 与真实文件

## Objective

验证当前唯一能力路线在真实 OpenClaw 用户任务中成立：

```text
用户自然语言
  -> Agent / Skill 语义判断
  -> Search / Host Web
  -> 必要时 Expand / Import / Inspect
  -> 用户明确选择并要求下载
  -> Download Job
  -> 真实文件
  -> 可选 Archive
```

本计划只记录真实 Agent、真实平台和真实文件证据。平台实现、fixture、Service 直调、单元测试、stdio probe 或 Tool 存在都不能替代这里的验收。

## Non-goals

- 不定义第二套公共 Tool 或架构路线；公共面以 0067 和运行时 schema 为准。
- 不恢复 Flow、ResultSet、Presentation、Selection、Plan、Eligibility、Authority、Asset 或 digest 状态链。
- 不用真实验收失败推动无关重构；失败只回到对应 Adapter、Inspector、Downloader、Session 或 Job 边界修正。
- 不索取、记录或提交密码、验证码、Cookie、Token、浏览器档案和下载资产。

## Business invariants

- Search / Expand 只产生候选，不授权下载。
- Inspect 只在未知事实影响选择或获取时使用，不是固定步骤。
- 用户已经明确选择并要求下载时直接调用 `resource_download`，不制造二次确认状态机。
- Download 内部 fresh Inspect，并精确执行当前 Provider 路线；失败不静默切换到不等价资源。
- 一个逻辑 Resource 可以自然产生多个真实文件。
- Expand 完整结果落 `results.jsonl`；`resource_job_read` 只控制上下文页大小，不截断数据。
- `AUTH_REQUIRED`、网络出口限制、平台风控、内容失效和文件校验失败必须按真实原因区分。
- 没有真实文件不得报告下载成功。

## Current architecture

- 当前公共面为 9 个资源 Tool + 4 个 Session Tool，共 13 个。
- `resource_id` 是进程内句柄；Expand / Download 的 `job_id` 是真实长任务句柄。
- SessionStore 位于同一个 `education-resources` MCP 中，不是 Search / Download 前置步骤。
- `resource_import_url` 对已接入的明确 URL 形态恢复平台身份，未知 URL 保持 `generic`。
- 当前主计划是 0067；CCTV 专项实现由 0068 跟踪，本计划统一承接它们的真实验收。

## 验收矩阵

### 1. Host Web 与 URL Import

- Host Web 找到已接入平台 URL；
- Import 恢复正确平台身份；
- 进入专门 Inspector / Downloader；
- 最终得到真实文件；
- 未知网页仍按 Generic Web 处理。

### 2. SmartEdu

- 公共 Search 在保存过 Session 时仍保持匿名；
- textbook Expand 得到真实 course 候选；
- 一个包含主视频与资料附件的 course 使用 `original` 产生符合真实内容的多文件 Job；
- 不把 IP/网络出口拒绝误报成登录问题；
- `course -> file[]` 只有在 0067 建立稳定子资源身份后再验收，不用短期 CDN URL 假装完成。

### 3. LibGen

- Search 返回 active `platform=libgen`；
- 书籍身份以 MD5 为核心；
- 不触发登录；
- 镜像失败切换到下一 LibGen mirror，不跳转 Anna 页面重新识别；
- 下载得到真实电子书文件。

### 4. Session 登录恢复

- 真实资源操作先返回 `AUTH_REQUIRED`；
- 用户自行完成浏览器登录；
- capture 原样交给 `resource_session_save`，由 MCP 内部筛选；
- 重试原资源操作成功或返回新的真实失败；
- Agent 不接触密码、验证码、短信码或 MFA。

### 5. Generic Web

- 真实页面得到原始 `source.html`；
- Trafilatura 生成 `content.md` 与 Reader `index.html`；
- Reader 不依赖远程正文图片资源；
- 抽取或图片获取失败时保留 source，并按 partial / warning 如实返回；
- 人工打开至少一个中文页面检查可读性。

### 6. 结构展开平台

- Bilibili：creator / collection Expand 到完整 video 候选，video 下载得到真实 MP4；
- Douyin：creator / collection Expand 到完整 video 候选，长任务不因上下文膨胀中断；
- Ximalaya：creator Expand 到完整 album 候选，album Expand 到 track，track 下载得到真实音频，album 直接 Download 明确失败；
- Zjer：course Expand 到 video，video 下载得到真实 MP4；
- CCTV：column / series Expand 到 video，video 下载得到真实 MP4；

### 7. Job durability 与取消

- Expand / Download Job 在 Gateway/MCP 重启场景中的结果有真实结论；
- worker 消失时状态不永久停留 running；
- 用户取消能到达真实终态；
- 不新增 checkpoint、resume token 或第二套 Job 状态机掩盖失败。

### 8. Expand 结果选择与批量下载

- 用户只选择部分子资源时，通过 `resource_job_read` 获取对应 `resource_id` 后下载；
- 用户明确选择完整 succeeded Expand Job 的全部结果时，使用 `expand_job_id` 提交普通多资源 Download Job；
- partial / failed / cancelled Expand Job 不得冒充“全部”；
- Search / Expand 完成不会自动开始下载。

## 每次真实测试最少记录

```text
User request:
Platform / route:
Search / Import / Expand completed:
Inspect needed/completed:
Download explicitly requested:
Job terminal status:
Actual files:
Session involved:
Compaction or interruption:
Observed error and stage:
```

## Acceptance criteria

- AC-01：至少一个真实平台从自然语言需求走到真实文件。
- AC-02：Host Web -> Import -> 专门平台 -> 文件真实通过一次。
- AC-03：Generic Web 真实生成 source + readable views，并完成一次人工检查。
- AC-04：一个 SmartEdu 多文件课程使用 `original` 得到与真实内容一致的 Job 结果。
- AC-05：一个真实 AUTH_REQUIRED 平台完成用户登录 capture -> save -> 原操作重试。
- AC-06：一个曾易 compaction 的完整展开任务成功结束，或失败已定位到具体平台/能力。
- AC-07：Gateway/MCP 重启下 Job durability 得到真实结论。
- AC-08：Bilibili、Douyin、Ximalaya、Zjer、LibGen、CCTV 的已实现核心路径各有至少一次真实 smoke，无法执行的明确记录外部条件。
- AC-09：测试过程中没有恢复旧状态链、静默 fallback 或数据截断。

## 步骤

- [x] completed：合并 0058、0060、0061、0062、0063 的剩余真实验收责任，并更新为当前 13 Tool / Expand 路线。
- [ ] in_progress：按验收矩阵执行真实 OpenClaw / 平台 smoke，逐项记录证据与失败阶段。
- [ ] pending：把真实失败返回对应局部实现计划修正，并按影响范围复测。
- [ ] pending：满足完成标准后记录结果、标记 completed 并归档。

## Validation status

已有单元、integration、stdio 和历史真实网页物化证据只能证明局部实现，不满足本计划的真实 Agent / 平台门槛。当前尚未形成覆盖上述矩阵的统一真实验收记录。

## Result

未完成。当前作为 0067 的唯一真实验收子计划继续跟踪。
