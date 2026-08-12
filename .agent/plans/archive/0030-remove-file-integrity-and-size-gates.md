# 0030 — 移除文件哈希校验与下载大小上限

- 状态：completed
- 分支：`codex/growth-resource-taxonomy-rework`

## Goal

下载与归档流程不再因为每资源/每 Bundle 字节上限、Provider 声明大小与实际文件大小不一致，
或文件 SHA-256 与声明值不一致而拒绝已经成功生成的文件。

## Non-goals

- 不修改 selection/plan/authority/execution/outcome 等业务状态 digest；后续单独处理。
- 不修改 SSRF、重定向、路径越界、格式、认证、取消、超时和幂等边界。
- 不删除 `byte_size` 与 `sha256` 元数据以及当前归档去重字段；本次只移除它们作为文件验收门禁的用途。
- 不删除 HTML/图片解析过程的内存读取边界、DOM/文本块数量边界或路径长度边界。

## User / Business Behavior

```text
Given: Provider 已在服务端受控目录中产生一个非空文件
When: 下载任务收集文件并在之后归档
Then: 不因文件大小或 SHA-256/声明字节数不一致而拒绝该文件
```

## Business Invariants

- Provider 输出仍必须是服务端受控目录内的普通文件。
- 空文件、真实格式不匹配、访问控制失败和任务取消仍显式失败。
- 文件元数据继续供展示、索引和现有归档去重使用，但不作为验收证明。

## Expected Change Surface

Likely to change:

- 下载 prepare 契约与服务选项。
- PlanItem/Representation 中的 `effective_max_bytes`。
- AcquisitionRequest、Provider 协议、Router 和各下载 Provider。
- 归档文件发布/恢复时的 checksum/size 比对。
- 直接相关的 Schema、文档和测试。

Should not change:

- 搜索、SemanticReview、Gap、StopDecision。
- capability/eligibility/digest 链的其余字段。
- Library 分类与目录结构。

## Acceptance Criteria

1. `resource_download_prepare` 不再接受或生成 `max_bytes_per_resource` / `effective_max_bytes`。
2. Provider 下载采用固定大小数据块流式写入，直到 EOF 或取消，不以累计字节数拒绝文件。
3. Router 不比较 Provider 的 `byte_size`/`sha256` 与落盘文件；只读取实际元数据供下游记录。
4. 归档发布与恢复不再把文件大小或 SHA-256 差异标记为损坏。
5. 相关契约测试、下载/Router/归档测试通过，且 `git diff --check` 通过。

## Validation Plan

- 运行 acquisition models/router、下载 Provider、service prepare 和 archive 的定向测试。
- 运行相关 JSON Schema 契约测试。
- 运行 Python 语法检查与 `git diff --check`。
- 不默认运行全仓回归；不执行真实平台下载或真实 Agent 流程。

## Complexity Exception

不新增抽象、状态、兼容层或 fallback；直接删除现有门禁与参数传播。

## Completion Record

```text
[x] implemented
[x] statically checked
[x] targeted unit tested
[x] subsystem/integration tested
[ ] backend E2E tested
[ ] real Agent/user-flow tested
[ ] full regression tested

Not validated: Schema 测试缺少 `jsonschema`；stdio E2E 缺少 `mcp`；平台 Adapter 测试缺少 `bs4`；未执行真实平台大文件下载与真实 Agent 流程
Known remaining risks: 不再限制下载体积后，调用方需要自行保证磁盘容量；HTML/图片解析仍保留独立内存边界。
```
