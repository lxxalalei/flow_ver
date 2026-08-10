# Acquisition Core + Web Materializer

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：内部 Acquisition 模型/Router、现有 direct downloader 包装、Generic Web 文章物化、资产元数据与安全回归

## 目标与边界

把现有下载执行内部升级为 `Selection -> AcquisitionPlan -> AcquisitionJob -> Materialized Assets`，
但保持公共 `resource_download_prepare` / `resource_download_start`、用户确认、Plan digest、Job、
Archive 和 Library 契约不变。首批 Web Materializer 只处理普通文章、古诗文页、知乎式长文和
普通图文博客；优先可读 Markdown/HTML，不把 HTML 规定为所有资源的统一格式，不默认启动浏览器。

## 步骤

- [x] completed：并行审计现有 Downloader/Rendering/Inspection/Job/Asset/Archive 边界与 0021 规划，冻结最小架构
- [x] completed：实现内部 AcquisitionRequest/Strategy/Artifact/Bundle/Result 与 Router，并包装 direct_file
- [x] completed：实现 Generic Web block extraction、sanitizer、受控同源/策略资产获取、HTML/Markdown renderer
- [x] completed：接入现有 prepare/start Job，保持确认、幂等、取消、max_bytes 与 Archive 边界
- [x] completed：补充文章/古诗文/长文/图文博客、安全、失败恢复和契约回归测试
- [x] completed：更新 Skill、架构、MCP 文档与总体规划
- [x] completed：根智能体执行定向回归、编译、链接、差异与安全验收
- [x] completed：完成 0021，规划并启动 0022 Multimodal Asset Bundle

## 初步架构问题

- 现有 `DownloadProvider.download`、`RenderingDownloader` 与新 Acquisition Router 的适配层位置。
- Generic Inspector 的受控响应事实能否复用，避免 Materializer 绕过逐跳 SSRF、MIME 和大小策略。
- readable Markdown、sanitized HTML、图片/CSS 资产的角色、命名、相对引用和总字节预算。
- 单个 Resource 多 Asset 如何在不提前增加公共 bundle Tool 的前提下绑定 Job、Archive 和恢复状态。
- 网络失败、认证需求、动态渲染需求与静态提取失败的结构化降级顺序。

## 验收条件

- 公共工具名、确认流程和 contract major 不变；模型仍不能提交 URL、路径、命令或策略。
- 静态 Web 物化逐跳执行网络策略，限制响应、解码、DOM、文本和资产总量；不执行页面脚本。
- 输出至少提供可读 Markdown 与 sanitized HTML，引用只指向同一受控 bundle 内资产。
- direct_file 与既有视频/音频/图书下载不回归；取消、幂等、失败清理和 Archive 仍可恢复。

## 冻结决策

- 0021 不增加公共 Tool、Schema 字段或 SQLite migration；现有 Plan/Job/Asset 多行能力足够接入。
- `_run_download_job` 是唯一控制面接入点；Router 内部区分 `direct_file`、
  `web_materialize` 和非默认的 `web_capture`。
- `html`/`text` 首选静态 Web Materializer；CDP/MHTML 不再因“这是网页”自动执行。动态空壳返回
  结构化失败，只有未来明确的受控 snapshot profile 才能进入 browser capture。
- Static fetch 每跳执行 URL/DNS 策略、显式 redirect、超时、MIME 和流式字节上限；首次实现
  不复用 Inspector 的脱敏输出，也不把 body、URL 或响应证据暴露到 Tool JSON。
- Materializer 从安全 Block IR 重新生成 Markdown/HTML，只本地化同源、受控、通过 MIME/魔数的
  图片。Job 目录保留 `index.html + content.md + metadata.json + assets/`，并生成一个 ZIP
  primary artifact；ZIP 可作为单一 Asset 归档以保持相对链接。正式 role/bundle 关系在 0022
  再持久化。
