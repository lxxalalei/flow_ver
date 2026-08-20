# 0064 — 单文件离线网页 Reader

- 状态：completed
- 创建日期：2026-08-20
- 完成日期：2026-08-20
- 范围：Generic Web Materializer 的清洗后 `index.html` 图片内嵌、失败语义、元数据与聚焦测试

## Goal

用户下载网页资料后，只复制或打开一个 `index.html`，正文和清洗后保留的图片即可完整呈现，不再依赖远程图片地址。

## Non-goals

- 不克隆原网页的脚本、广告、导航、跟踪器或原站 CSS。
- 不把视频、音频、iframe 等大型或可执行媒体纳入本轮。
- 不替换 Trafilatura、Simple.css 或现有 MCP 工具契约。
- 不删除 `source.html`、`content.md`、`metadata.json` 或 `webbundle.zip`。

## Acceptance Criteria

### AC-01

```text
Given: 清洗正文包含可获取且格式有效的 HTTP(S) 图片
When: WebMaterializer 生成 index.html
Then: 图片以正确 MIME 的 data URL 内嵌，index.html 不再包含该远程图片引用
```

### AC-02

```text
Given: 同一图片在正文中重复出现
When: 生成单文件 Reader
Then: 网络只获取一次，所有出现位置均使用同一内嵌 data URL
```

### AC-03

```text
Given: 某张图片不可获取或格式无效
When: 生成单文件 Reader
Then: 不保留会继续联网的图片引用，以可读占位替代，并将任务标为 partial、在 metadata/warnings 中显式报告
```

### AC-04

```text
Given: 生成成功的单文件 Reader
When: 检查 index.html 和 webbundle.zip
Then: index.html 的图片策略仅允许 self/data，ZIP 中的同一 index.html 也保持自包含
```

## Business Invariants

- `source.html` 继续精确保留首次网页响应字节。
- 图片获取继续经过现有公共网络、重定向、超时、取消和真实格式校验边界。
- 不静默丢弃失败图片；失败必须进入 partial 和结构化元数据。
- Reader 不引入 JavaScript、CDN 或新的运行时依赖。

## Expected Change Surface

Likely to change:

- `mcp/education-resources/src/education_resource_mcp/acquisition/web_materializer.py`
- `mcp/education-resources/src/education_resource_mcp/service.py`
- `mcp/education-resources/src/education_resource_mcp/job_worker.py`
- `mcp/education-resources/tests/test_web_materializer.py`
- Reader 架构/计划文档中关于图片与单文件语义的说明

Should not change:

- 搜索、平台 Adapter、Flow/Selection/Job 状态模型与外部 MCP Tool Schema

## Validation Plan

- WebMaterializer 图片成功、重复、失败、ZIP 聚焦测试。
- 相关 rendering/download integration。
- 使用带图中文网页执行真实物化，确认 `index.html` 不含远程图片资源属性且图片为 `data:`。
- 不运行与该子系统无关的全仓测试。

## Completion Record

```text
[x] Level 1 — 小改动：直接受影响单元测试、语法/静态检查
[x] Level 2 — 子系统改动：受影响模块测试和直接相关 integration
[ ] Level 3 — milestone/用户链路改动：受影响回归、相关 E2E、适用时真实流程
[ ] Level 4 — release/跨切面改动：有具体风险依据时运行全量回归
[x] 未执行真实 Agent/用户流程验证（未执行时勾选）

Not validated: OpenClaw 真实 Agent 对话链路、全仓回归。

Known remaining risks: 仅内嵌 Trafilatura 保留且通过格式校验的 JPEG/PNG/GIF/WebP；远端限流或不支持格式会得到占位和 partial。Base64 会增大 HTML 体积。
```

## Validation Evidence

- `test_web_materializer.py`、`test_rendering_download.py`、`test_zhihu_materialize_routing.py`、`test_job_durability.py`、`test_batch_download_handoff.py`：24 passed。
- `py_compile`：物化器、Service、Job Worker 与聚焦测试通过。
- `git diff --check`：通过。
- 真实中文“长城”页：25 个图片候选中 18 个内嵌，7 个因远端 429 在三次尝试后转为占位；生成 HTML 的远程资源属性为 0，ZIP 内外 `index.html` 完全一致。
- 真实中文“岩浆”页：上游对 2 张图片持续返回 429；Job 正确返回 partial，HTML 不保留远程图片引用。
