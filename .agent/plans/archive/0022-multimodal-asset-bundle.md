# Multimodal Asset Bundle

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：Artifact/Asset/Bundle 领域边界、权威持久化、多模态伴随资产、部分失败、归档关系与恢复

## 目标与边界

把 0021 的内部 `ArtifactBundle` 升级为可恢复、可审计的权威多模态资产关系，使视频、
音频、图书和课程可以保留 primary、subtitle、cover、metadata、attachment、transcript、
companion 等角色，并让部分成功可追踪。保持现有 `resource_download_prepare/start`、
用户确认、Job、Archive 和 Library 主流程；只有真实使用证明需要时才增加 bundle 级公共 Tool。

## 步骤

- [x] completed：并行审计 Asset/Job/Archive/Library、平台下载器、多文件返回、公共 Schema 与 0022 兼容边界，冻结领域术语和最小迁移
- [x] completed：实现权威 Asset Role、Bundle、BundleItem 与 PartialFailure 存储和原子恢复
- [x] completed：把 Acquisition ArtifactBundle 接入 Job/Asset 持久化，保留 primary 与 companion 关系
- [x] completed：归一化视频、音频、图书和课程的多资产输出及角色，不绕过现有授权/大小/格式边界
- [x] completed：让 Archive/Library 保持 bundle 关系、幂等和部分失败可追踪，并完成 catalog 1.3.0 兼容加法
- [x] completed：补充迁移、角色、顺序、重复内容、部分失败、取消、重启恢复与归档回归测试
- [x] completed：更新 Skill、MCP、架构、契约兼容说明和总体规划
- [x] completed：根智能体执行定向/全量回归、编译、Schema、链接、差异与安全验收
- [x] completed：完成 0022，规划并启动 0023 E2E Hardening

## 初步领域问题

- `Artifact` 是一次 Acquisition 的临时输出描述，还是可被 Job 恢复的权威记录；何时成为 `Asset`。
- primary 与 bundle container 是否可以是同一个 Asset；一个 Resource/Job 是否允许多个 Bundle。
- subtitle、cover、metadata、transcript、attachment、companion 的互斥、顺序、必需性和 MIME 约束。
- 平台下载器多文件列表缺少角色时如何保守映射，不能靠文件名猜测高风险语义。
- 课程部分失败如何记录成功项、失败项、重试范围与 Job 终态，避免把 partial 伪装成 succeeded。
- Archive 是归档 primary、逐个 Asset，还是复制整个 Bundle；Library Search 如何返回关系而不泄漏路径。

## 验收条件

- 现有单 Asset 和 0021 Web ZIP 路径保持兼容，公开确认流程和 contract major 不变。
- Bundle/Item/Role 由服务端生成并持久化，模型不能提交路径、角色关系或伪造部分成功。
- 视频/音频/图书/课程至少各有一个固定夹具覆盖 primary 与 companion；课程覆盖部分失败。
- 取消、重启恢复、幂等 replay/conflict、归档和 Library Search 不丢 Bundle 关系。
- 公开 Schema 如有兼容加法，必须同步 catalog、compatibility、契约测试与 Skill；无真实需要则不新增 Tool。

## 冻结决策

- 公共 `contract_version` 保持 `1.0.0`、工具仍为 13 个；为 job/archive/library/flow
  增加可选 Bundle 字段时把 catalog 升至 `1.3.0`，不新增 bundle Tool，不增加
  `partial` Job 状态。
- Job `status` 继续表达执行生命周期；新增可选 `completion=complete|partial` 表达结果
  完整度。至少一个 Resource 形成 primary 时 Job 可 `succeeded + partial`；没有可用 primary
  才 `failed`。取消继续是 `cancelled` 并 quarantine 本 Job 未归档资产，不伪装成 partial。
- migration 5 使用 `asset_bundles`、`asset_bundle_items`、`asset_bundle_failures`；
  一个 `Job × Resource` 最多一个 Bundle。失败 Item 的 `asset_id` 为空，绝不创建零字节
  假 Asset；历史资产按 `jobs.asset_ids_json` 回填，首项 primary，其余 attachment，不按文件名猜。
- Artifact 是临时采集描述，Asset 是持久化内容；Bundle 是关系而不是 ZIP。`primary` 唯一，
  角色固定为 primary/subtitle/cover/metadata/attachment/transcript/companion。0021 Web ZIP
  作为 singleton primary 回填，ZIP 内部文件不拆分。
- 保留旧 `DownloadProvider`；新增 enriched batch envelope 承载有序角色和逐项 failure。
  旧单文件映射 primary，旧列表首项 primary、其余保守 attachment。SmartEdu 必须保留当前
  被丢弃的逐项失败与来源关系事实。
- Archive 继续 asset-scoped：任何 ready 成员可按现有 `asset_id` 独立归档，服务端和
  Library 通过 BundleItem 关系恢复 `bundle_id/role/order/completion`。Skill 在用户要求
  完整 Bundle 时依次归档 ready 成员；0022 不强塞新的全 Bundle 原子 Tool。
- 进程重启仍把内存中断 Job 终结为 failed/cancelled 并 quarantine，不自动重放网络副作用；
  migration 5 同步终结 pending Bundle/Item 并保留审计关系。真实杀进程与恢复执行留到 0023。
