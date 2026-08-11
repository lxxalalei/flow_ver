# 0036 — 平台获取能力恢复

- 状态：superseded
- 创建日期：2026-08-11
- superseded by：[`../0037 获取状态链简化`](../0037-acquisition-state-simplification.md)
- 保留价值：具体平台恢复候选与真实纵切目标继续作为 0028/后续 Platform Expansion 的输入

## 为什么被 supersede

0036 原计划把“先恢复平台能力，再决定是否删除 Descriptor / Readiness / Eligibility”等作为执行顺序，并重新提出通用文件大小/哈希验收门禁。

2026-08-11 随后完成的架构复核确认：

1. 获取层的主要复杂度来自服务端自己维护 Descriptor → Readiness → Eligibility → 多层 digest 的自证状态链；
2. 这些状态没有直接增加用户搜索、选择、获取或归档能力；
3. 真实平台恢复不需要先保留这套状态体系，反而会让每新增一个 Provider 都复制控制面复杂度；
4. 0030 已明确删除文件 SHA-256/声明大小一致性和通用下载大小上限作为成功验收门禁，0036 不应静默恢复该决定。

因此 0036 的架构部分被 0037 覆盖，不再单独执行。

## 仍然有效的产品目标

以下目标继续保留，并并入 0028 / 0037 后续平台扩展：

```text
Search
  -> Inspect
  -> Present
  -> Select
  -> Prepare
  -> Confirm
  -> Start
  -> Job succeeded
  -> Asset / Bundle
  -> Archive
  -> Recover
```

需要逐步恢复真实平台 Provider，尤其是视频、音频、图书/文档和课程资源；不能长期只有 generic 网页路线。

历史候选仍包括：CCTV、Open163、Yixi、NLC、Bilibili、Douyin、Ximalaya、SmartEdu，以及其他已有 Search/Inspect Adapter 且合法边界清晰的平台。

具体平台是否恢复必须重新检查当前 endpoint、认证、依赖、许可、Representation 和真实输出，不能因为 legacy 下载器存在就直接标 ready。

## 新的接入方式

0037 后平台恢复统一按：

```text
Platform Search / Inspect
  -> fresh Resolution / Representation
  -> ProviderSpec
  -> exact Provider
  -> Plan
  -> 用户确认
  -> Job / Outcome / Asset
```

新增平台不再要求 Capability Descriptor 持久 binding、Readiness Snapshot、Eligibility Decision 或 authority/plan/execution/outcome digest 链。

需要检查 Provider 当前是否可执行时，在 Prepare/Start 做运行时检查并返回明确失败即可。

## 继续保留的安全边界

- SSRF / DNS/IP / 逐跳重定向；
- 受控 Job 输出目录和路径逃逸检查；
- 非空文件、真实 MIME / magic / container 检查；
- 取消、超时、幂等；
- `prepare -> 用户明确确认 -> start`；
- 登录、验证码、付费墙、DRM 和访问控制；
- Archive 只接受服务端 ready `asset_id`。

文件 `sha256` / `byte_size` 可以继续作为 Asset 元数据和去重信息，但不恢复“声明值必须匹配”或通用下载体积上限作为额外成功门禁。

## 后续入口

- 当前执行：[`0037 获取状态链简化`](../0037-acquisition-state-simplification.md)
- 真实平台/Agent 验收：[`0028 Real OpenClaw and Real Platform E2E`](../0028-real-openclaw-platform-e2e.md)
- 长期路线：[`../../../docs/DEVELOPMENT_PLAN.md`](../../../docs/DEVELOPMENT_PLAN.md)

0036 的原始详细内容保留在 Git 历史中，不再作为 current execution authority。
