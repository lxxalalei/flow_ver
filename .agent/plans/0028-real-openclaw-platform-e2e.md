# 0028 — Windows OpenClaw / 真实资源能力验收

- 状态：in_progress
- 创建日期：2026-08-08
- 更新日期：2026-08-19
- 负责人：用户执行真实 Windows OpenClaw 测试；Coding Agent 只根据真实失败修具体能力

## Objective

验证当前 `learning-resource-flow + education-resources MCP` 能否在 Windows OpenClaw 中稳定完成真实资源任务。

本计划只跟踪**真实 Agent / 用户链路**。平台实现历史、局部单测、fixture、stdio 能启动、Provider 存在都不能替代这里的验收。

## 当前后端基线

当前 release-ready 基线为：

```text
commit: 8ce531274edbec482e913b73dd33313283c322b1
MCP: education-resources 0.4.0
Tool surface: 14 tools
full pytest: 205 passed
compileall: passed
runtime verifier: passed
MCP stdio probe: passed
```

这些证据证明当前后端与 Tool 表面可运行，但**不证明真实 OpenClaw、真实平台登录、真实网络出口或真实下载可用**。后续真实反馈修正必须重新验证受影响链路，不能借用该基线冒充新 diff 已通过。

## 当前真实链路

```text
自然语言需求
  -> resource_search / Host Web Search / resource_browse_creator
  -> Agent 判断候选
  -> 必要时 resource_import_url / resource_inspect / 补搜
  -> 用户选择
  -> 用户明确要求下载
  -> resource_download
  -> resource_job_status
  -> real files / failures
  -> 可选 resource_archive
```

没有：

```text
Flow
ResultSet lineage
Presentation
Selection
Prepare
confirmation token
Start
Asset / Outcome 状态链
```

`resource_id` 只是进程内临时句柄；Download / Batch 的 `job_id` 才是文件型运行状态。一个逻辑 Resource 可以自然产生多个 File，不要求一一对应。

## 当前真实验收队列

按实际使用需要选择，不要求固定顺序。

### 1. Host Web -> 已接入平台

验证 Host Web 找到 Bilibili / Zhihu / SmartEdu 等明确 URL 后：

```text
Host Web Search
-> resource_import_url
-> 正确平台身份
-> 对应 Inspector / Downloader
```

不能再次全部落成 `generic`。

### 2. SmartEdu

分别记录四个边界：

- 公共 Search / Catalog 在已保存 session 环境下仍应匿名；
- 具体 Detail / Download 如果真实需要登录，才进入 Session；
- 如果出现 IP / 网络出口限制，记录失败发生在 detail、media URL、m3u8、segment、key 哪一级，不把它误报成“补 token 即可”；
- 课程链接是逻辑 Course Resource，不等于单网页/单文件。包含视频 + PDF/音频等内容时，Inspect 应公开主表示与 attachment/companion；用户未指定格式时直接 `resource_download(..., original)`，Agent 不应自行补 `mp4` 来绕过“网页不可下载”。Job 的多个 `files` / `failures` 才是课程交付事实。

2026-08-19 真实事故：用户批量获取 SmartEdu 课程时，Agent 将课程 URL 降维为 webpage，随后人为补了格式才继续下载；但同一课程链接实际包含视频和文档。修正由 `0060-resource-multifile-delivery.md` 跟踪。

当前视频/PDF/音频实现存在不等于当前网络出口可用。

### 3. Anna / Libgen

匿名镜像链不得触发 Anna 会员登录；验证搜索、Inspect、下载最终文件。

### 4. AUTH_REQUIRED -> Session

找一个真实需要登录的平台，验证：

```text
真实资源能力返回 AUTH_REQUIRED
-> 用户浏览器登录
-> resource_session_save
-> 重试原资源能力
```

Session Tool 不是 Search / Download 的固定前置步骤。

### 5. Generic Web

验证普通网页最终真实得到：

```text
source.html
index.html
content.md
metadata.json
webbundle.zip
```

人工检查 source snapshot 与 Trafilatura 可读表示；正文抽取失败不能删除已经取得的 source HTML。

### 6. Douyin creator 长任务

复测“停云小阁”场景：搜索/Inspect 直接得到 `creator_sec_uid`，再进入 `resource_browse_creator` 或批量枚举。Agent 不应再为了找 creator_id 读取大型源码/旧 Contract 并触发 compaction。

### 7. Yixi

使用历史真实样本 `speech_id=1435`《教育就是生长》，验证公开 MP4 从候选走到实际文件。0051 的实现历史已归档，不再使用其中的 Prepare / Start / Asset 术语。

### 8. Zjer

使用 `courseCateId=34941` 验证 experimental 课程视频：稳定课程/课时身份 -> fresh Inspect -> 下载时刷新临时签名 URL -> 实际 MP4 文件。普通关键词搜索在原生接口未确认前继续如实 `FEATURE_NOT_SUPPORTED`。

### 9. Job durability

在真实 Windows 计划任务网关环境验证：下载进行中执行实际 `sync-to-openclaw.ps1` / gateway restart 后，文件型 Job 状态仍诚实可读；worker 存活则继续，真实中断则显示 `interrupted`，不得伪造成功。

### 10. Batch

批量能力的实现历史已经归档；这里只验证真实用户链需要的代表场景，例如 Bilibili creator/time-range、SmartEdu catalog expand。全量结果必须留在 `results.jsonl`，对话只分页读取；损坏 JSONL 必须显式失败。

SmartEdu `catalog_expand` 当前解决完整枚举，不等于已经提供“把整个 catalog 自动全部下载”的资源工作流；若真实需求确认需要直接衔接，再另做最小批量 acquisition 能力，不把这次课程包修正扩大成新状态机。

## 每次测试最少记录

```text
User request:
Platform / route:
Search or discovery completed: yes/no
Inspect needed/completed: yes/no
Download requested: yes/no
Job terminal status:
Actual files:
Compaction happened: yes/no
Task interrupted: yes/no
Observed error:
Failure stage (if known):
```

不要为了记录完整而要求用户提供 digest、Plan、Outcome 等已删除状态。

## 必须保持的边界

- Agent 只有在用户已经明确表达下载意图时调用 `resource_download`；
- 不制造 Prepare / confirmation token / Start；
- 下载内部 fresh Inspect，并使用当前 exact Provider；
- 一个 Resource 可以产生多个真实文件；primary 只是 Provider 路由锚点，不是“一资源只能一个文件”的声明；
- 默认 `original` 不制造格式要求，Agent 不因 landing webpage 自行猜扩展名；
- Provider 失败返回真实失败，不 silent fallback 到不等价来源；
- `AUTH_REQUIRED`、网络阻断、平台风控、内容变化和文件校验失败必须区分；
- 没有真实文件不得报告成功；
- 平台真实问题优先修 Adapter / Inspector / Downloader，不增加通用状态机掩盖问题。

## 历史计划接管

以下实现计划已移入 `archive/`，剩余真实用户验收统一由本计划接管：

- `0051-yixi-video-acquisition.md` -> Yixi 1435；
- `0052-zjer-course-video-acquisition.md` -> Zjer 34941；
- `0054-douyin-creator-id-exposure.md` -> Douyin creator / compaction；
- `0056-download-job-subprocess-durability.md` -> Windows gateway restart；
- `0057-native-batch-capability-parity.md` -> 代表性 Batch 用户链；
- `0059-post-convergence-review-fixes.md` 已完成，只作为 release-ready 后端验证历史。

当前新的 `0060-resource-multifile-delivery.md` 是由 2026-08-19 真实 SmartEdu 用户反馈产生的局部修正，不是旧计划恢复。

旧计划中的 Prepare / Confirm / Start / Asset、独立 session-manager、旧测试基线等文字仅代表当时历史，不再是当前架构依据。

## Completion criteria

本计划至少满足：

1. 一个真实平台在 Windows OpenClaw 中从自然语言需求走到实际下载文件；
2. Host Web -> 已接入平台 URL -> Import -> 专门能力真实通过一次；
3. Generic Web 真实生成 source snapshot + readable views 并人工检查；
4. 一个此前易 compaction 的长任务完整完成，或剩余中断已定位到具体能力/平台；
5. Windows gateway restart 下 Job durability 得到真实结论；
6. 登录相关测试能区分真实 `AUTH_REQUIRED` 与 IP/网络出口/平台策略问题；
7. 一个包含至少主视频 + 文档附件的 SmartEdu 课程，在不指定格式的情况下通过 `original` 产生符合真实内容的多文件 Job，Agent 不再自行补格式。

如果失败，只根据实际 Search / Inspect / Download / Job 错误修具体能力，不恢复通用工作流状态机。
