# 0072 — 平台展开实现边界收敛

- 状态：completed
- 创建日期：2026-08-26
- 完成日期：2026-08-26
- 范围：`mcp/education-resources/src/education_resource_mcp/adapters/`

## Objective

保持公共 Tool、Resource、Job 和平台行为不变，把平台专属展开实现从集中式 `adapters/expansion.py` 移回各平台模块；同时把 SmartEdu 被 Inspect、Expand、Download 共同使用的纯平台事实从 Downloader 中提取为单一实现。

## Non-goals

- 不新增 MCP Tool、Provider、Registry、持久状态或兼容层；
- 不改变搜索、展开终止、Inspect、下载选择、Session 或归档语义；
- 不顺手重写平台 HTTP 协议、分页算法或错误码；
- 不拆 CCTV vendor，不清理 legacy，不删除测试。

## Business invariants

- `resource_expand` 的 input/output、Job、JSONL、分页和取消语义不变；
- Search/Expand 不产生下载授权；
- 平台真实分页终止、完整性检查和显式失败语义不变；
- SmartEdu 整课多文件与文件级资源身份必须使用同一套纯解析逻辑；
- 平台模块不依赖公共 Job/Service 内部状态。

## Current architecture

- `adapters/expansion.py` 同时承担平台路由和六个平台具体实现；
- `smartedu_download.py` 同时包含纯 Detail 解析/身份逻辑和网络物化；
- `inspect_smartedu.py`、SmartEdu Expand 反向导入 Downloader 内部函数；
- 公共 Job 层位于顶层 `expand.py`，本轮不移动。

## Expected change surface

- 新增各平台 `*_expand.py`，承接现有平台函数；
- 新增 `smartedu_resource.py`，承接 SmartEdu 纯事实解析、身份和选择；
- `adapters/expansion.py` 只保留平台到 expander 的分派；
- 更新相关 import、聚焦测试和架构说明。

## Acceptance criteria

- AC-01：`adapters/expansion.py` 不再包含任何平台 HTTP、分页、HTML/API 解析实现；
- AC-02：Bilibili、Douyin、Ximalaya、SmartEdu、Zjer、CCTV Expand 聚焦测试行为不变；
- AC-03：SmartEdu Inspector/Expander/Downloader 共用 `smartedu_resource.py`；
- AC-04：MCP stdio Tool schema 不变；
- AC-05：SmartEdu 聚焦测试和 MCP 全量测试通过。

## Complexity exceptions

```text
Problem:
平台路由文件已经集中六个平台协议，SmartEdu 三个调用方又依赖 Downloader 内部纯函数。

Why current structure cannot solve it:
继续增加平台会让路由层承担协议实现；SmartEdu 事实变化需要跨模块同步。

Simplest alternative considered:
只在现有大文件中按段落整理。

Why that alternative is insufficient:
不能恢复依赖方向，也不能让平台实现独立演进和定向测试。

New source of truth introduced:
无。现有函数原样迁移；smartedu_resource.py 成为既有纯平台事实的唯一实现位置。

New invariant introduced:
平台 expander 只返回 Resource 候选，不接触 Job 持久化。

Failure modes introduced:
仅 import/dispatch 接线错误，由现有平台聚焦测试与全量回归覆盖。
```

## 步骤

- [x] completed：提取 SmartEdu 纯事实与 Expander。
- [x] completed：迁移其余平台 Expander，收窄集中路由文件。
- [x] completed：更新测试/文档并运行回归。
