# 0028 — Windows OpenClaw / 真实资源能力验收

- 状态：in_progress
- 创建日期：2026-08-08
- 更新日期：2026-08-16
- 负责人：用户执行真实 Windows OpenClaw 测试；Coding Agent 根据真实失败修代码

## Objective

验证当前**薄 MCP**在 OpenClaw 中能否稳定完成真实资源任务，而不是验证旧 Flow/Contract 状态机。

fixture、单元测试、Provider 类存在都不能替代真实用户闭环。

## 当前真实链路

```text
自然语言需求
  -> resource_search / resource_browse_creator
  -> Agent 判断候选
  -> 可选 resource_inspect / 补搜
  -> Agent 在对话中展示
  -> 用户选择
  -> 用户明确要求下载
  -> resource_download
  -> resource_job_status
  -> files / failures
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
Asset/Archive 状态链
```

## 重点观察

当前最重要的问题来自 2026-08-16 的真实使用：OpenClaw 在一个任务中频繁 compaction/中断，无法完成完整工作。

因此每次测试优先记录：

```text
User request:
Platform:
Search completed: yes/no
Inspect needed/completed: yes/no
Download requested: yes/no
Job terminal status:
Actual files:
Compaction happened: yes/no
Task interrupted: yes/no
Observed error:
```

不要为了记录完整而要求用户提供内部 ID、digest、Plan、Outcome 等已删除状态。

## 当前平台队列

按用户想测的资源直接选平台，不要求固定顺序：

1. **Douyin**：重点复测“搜索停云小阁 → 获取 creator_id → Browse Creator 全部视频”，观察上下文是否还会因为 Tool Result/源码恢复而爆炸；需要登录时真实返回认证问题。
2. **Bilibili**：搜索/Inspect/DASH 下载/ffmpeg 合并。
3. **SmartEdu**：PDF、MP4、MP3/M4A。
4. **Ximalaya**：具体 track 下载，不把 album 静默换成第一首。
5. **Shuge**：公开文档搜索与直接下载。
6. **Yixi**：可继续使用 `speech_id=1435`《教育就是生长》样本验证公开 MP4。
7. **Zjer**：可继续使用 `courseCateId=34941` 验证 experimental 课程视频。
8. **Anna's Archive**：复测此前元数据 Inspect 修复后的真实电子书链。
9. **Generic Web**：单独验证网页搜索、Inspect 和 HTML 保存质量。

## 必须保持的真实边界

- Agent 只有在用户已经明确说要下载时才调用 `resource_download`；
- 不再为了确认再创建后端 Plan/token；
- 下载前 Service fresh Inspect；
- 选中的实际 Downloader 失败时返回真实失败，不 silent fallback；
- AUTH_REQUIRED / unavailable / policy blocked 如实返回；
- 没有真实文件不得报告成功。

## Coding Agent 工作方式

- 不代替用户做 OpenClaw 用户验收；
- 不主动重启用户 Windows gateway；
- 不为每次失败先加新架构或新状态；
- 优先根据真实失败定位搜索脚本、Inspector 或 Downloader；
- 一个小修只跑相关测试；
- 不让已删除的旧 Contract/Flow 测试迫使实现恢复旧架构。

## 已知真实事故

### Douyin 登录与上下文爆炸

2026-08-15 曾出现两类问题：

1. Agent 错用 page `document.cookie`，拿不到 httpOnly Cookie；随后又把大 Cookie 对象经模型转述，导致输出截断。后续确认 OpenClaw 原生 browser cookies 本身能通过 Playwright context 获取完整 Cookie，自建 CDP 方案已撤销。
2. “拉取停云小阁全部视频清单”时缺 creator_id 来源，Agent 转而读多个大型源码/Contract，输入上下文被推高并触发 compaction。0054 已让真实搜索/Inspect 返回 creator handle。

本轮 MCP 简化进一步删除了 Flow/Contract/Registry 状态体系，目标之一就是避免 Agent 为恢复内部协议再去读源码。

### Anna's Archive Inspect

2026-08-14 Search 能返回候选，但 Inspector 误访问合成 Anna 详情页并将 403 判为 AUTH_REQUIRED。0049 已改成合法 MD5 元数据 Inspect；仍需真实复测下载。

更详细的历史定位保留在 Git 历史和 `.agent/plans/archive/`，本计划不复制整套旧架构说明。

## Completion criteria

至少完成以下两件事：

1. 一个真实平台在 Windows OpenClaw 中从自然语言搜索走到实际下载文件；
2. 一个此前容易中断的较长任务（优先 Douyin creator browse 场景）能完成，或能明确定位剩余中断来自哪里。

如果仍然失败，下一步根据实际 Search/Inspect/Download 错误修具体能力，不再恢复通用工作流状态机。
