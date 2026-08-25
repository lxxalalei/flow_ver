# 0071 — SmartEdu 课程文件级资源

- 状态：completed
- 创建日期：2026-08-26
- 范围：SmartEdu `course → file[]` 的 Expand、Inspect、Download

## Goal

保留课程自然多文件下载，同时让具有平台稳定身份的课程视频、文档和音频成为可展开、可单独检查和下载的逻辑资源。子资源只保存课程详情页与平台文件键；每次 Inspect/Download 都重新读取 Detail 取得当前地址。

## Non-goals

- 不新增 MCP Tool、Provider、持久 Resource Store 或永久 `resource_id`；
- 不保存或暴露带签名的 CDN URL；
- 不把数组序号、文件名或临时 URL 伪装成稳定身份；
- 不把同一视频的画质/容器变体暴露成多个逻辑子资源；
- 不改变课程整体自然交付包的既有行为。

## Acceptance Criteria

- 课程 Expand 输出有稳定平台文件键的逻辑子资源，并显式统计无法稳定识别的条目；
- 相同文件在 Detail 重排、签名 URL 变化后保持同一文件键；
- 文件级 Inspect 只公开一个当前主表示，并保留其课程内角色事实；
- 文件级 Download fresh Inspect 后只下载所选文件；缺失或变化显式失败；
- 完整 Expand Job 可继续通过既有 `expand_job_id` 全部下载；
- 课程整体下载和教材展开行为不回归。

## Steps

- [x] completed：实现稳定文件键与 course Expand。
- [x] completed：实现文件级 Inspect 与单文件 Download。
- [x] completed：补齐测试和文档。
- [x] completed：完成聚焦与 MCP 回归。
