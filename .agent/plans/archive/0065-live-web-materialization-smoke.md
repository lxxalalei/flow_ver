# Task Spec 0065：网页物化真实链路 Smoke

- 状态：completed
- 创建日期：2026-08-20
- 完成日期：2026-08-20
- 范围：Generic URL Import / Inspect / Download Job / WebMaterializer 真实联网只读验证

## Goal（必填）

用户/系统能够：确认当前公开网页可以经过真实 MCP 业务链物化为原始 HTML、可读 HTML、Markdown、元数据和 ZIP，并由 Job 状态完整报告。

## Non-goals（必填）

- 本轮不修改网页物化实现，不归档到正式资料库。
- 不测试登录网页、付费墙、JavaScript-only 页面或任意文件下载。
- 不用单元测试夹具代替真实联网链路结论。

## Acceptance Criteria（必填）

### AC-01

```text
Given: 一个公开、可访问的文章 URL
When: 依次执行 Import/Inspect、resource_download 和 Job 轮询
Then: Job 成功或 partial，并返回物化产物及显式 failure/warning
```

### AC-02

```text
Given: 下载完成的网页 bundle
When: 检查 source.html、index.html、content.md、metadata.json、webbundle.zip
Then: 文件存在、非空、位于临时测试目录；ZIP 成员和元数据一致，正文包含来源页面的可识别内容
```

## Business Invariants

- 所有运行数据和产物只写测试临时目录。
- 不调用 archive，不写正式学习资料库。
- 后端真实链路不冒充真实 OpenClaw Agent 用户流程。

## Expected Change Surface

- Likely to change: 本 Task Spec 的状态和结果记录。
- Should not change: 产品代码、测试代码、能力文档。

## Validation Plan

- 使用当前源码与完整依赖环境启动真实 ResourceService。
- 导入并 Inspect 一个公开网页，确认 `materializable` representation。
- 启动真实 detached worker，轮询 Job 到终态。
- 验证全部 bundle 文件、内容、ZIP 与 metadata。
- `git diff --check` 和工作区边界检查。

## 步骤

- [x] completed：选择公开网页并完成 Import/Inspect。
- [x] completed：执行真实异步下载并核验产物。
- [x] completed：记录结论、边界检查并归档计划。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| live Import/Inspect | 2 URLs resolved + materializable | Generic Inspector 能识别两个公开 HTML 页面 | Download 能处理对应响应编码 |
| live Download Job | httpbin succeeded；python.org failed | 未压缩 HTML 完整链可用；gzip HTML 存在真实缺口 | 长期上游稳定性、其他编码 |
| artifact inspection | 5 files validated | source/readable/Markdown/metadata/ZIP 均非空、大小一致、位于临时目录 | 所有网页类型 |
| targeted regression | 19 tests passed | 当前 WebFetch/Materializer/Import/Download 既有契约未失败 | 真实 Content-Encoding 兼容性 |
| real Agent/user flow | 未执行 | | |

## 结果

- `https://httpbin.org/html`：Import/Inspect resolved，Job succeeded；生成 `source.html`、`index.html`、`content.md`、`metadata.json`、`webbundle.zip`，metadata 为 `web-materialization-v2` / Trafilatura / extraction succeeded，ZIP 成员正确，正文抽取到实际 Moby-Dick 段落。
- `https://www.python.org/about/gettingstarted/`：Import/Inspect 同样声明 materializable，但真实 Job failed，错误为 `CONTENT_VALIDATION_FAILED: HTML 响应未通过基本内容特征校验`。
- 根因证据：Python 官网在请求明确发送 `Accept-Encoding: identity` 时仍返回 `Content-Encoding: gzip`；`BoundedWebFetcher` 按压缩字节执行 HTML magic 校验，未解压响应。
- 结论：网页物化基础链可用，但对忽略 identity 的 gzip HTML 站点失效；现有单元测试未覆盖真实 `Content-Encoding`。
- 本轮未修改产品代码、未 archive、未写正式资料库；所有 Job 和产物均在临时目录自动清理。
