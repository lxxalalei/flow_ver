# 0042 — 现有网页资源语义与可见归档修正

- 状态：completed
- 创建日期：2026-08-13
- 完成日期：2026-08-13
- 范围：当前 Generic Web Inspect 语义、静态 Web Materializer 主产物、网页归档可见形态
- 关系：不执行、不替代 `.agent/plans/0041-web-content-extraction-benchmark.md`

## Goal

在不引入新的网页抽取依赖、不重写 `web_blocks.py` 的前提下，修正当前网页链路中两个已经确认的业务问题：

1. Generic HTML 只有在页面自身提供明确的文章/学习资源结构化元数据时，才从保守 `landing_page` 提升为 `primary_resource`；普通 HTML 继续保持 `landing_page`，不靠自研正文启发式猜测。
2. `WEB_MATERIALIZE` 的公开 primary Asset 改为可直接打开、图片自包含的 HTML，而不是 `webbundle.zip`；ZIP、Markdown、metadata 和独立图片继续作为 Job 工作产物/完整 bundle 保留，不扩展公共 Asset 模型。

最终目标是让资料库归档网页时得到 `generic-<资源标题>.html` 这一类用户可直接打开的图文文件，同时保留当前 bundle 生成能力供后续 0041 评估与演进。

## Non-goals

- 不执行 0041 的 Trafilatura / Readability / Defuddle / Crawl4AI benchmark。
- 不新增第三方依赖。
- 不重写正文抽取、Block IR 或 Markdown 生成算法。
- 不新增 page classifier、评分器、Extractor registry、fallback chain 或新状态模型。
- 不改变 Search、Flow、ResultSet、Presentation、Selection、Plan、Job、Archive 的公共契约。
- 不把 ZIP 解包成资料库目录，也不新增目录型 Archive；本阶段只把用户主归档物改成自包含 HTML。
- 不放宽当前图片抓取来源策略；跨域/CDN 图片问题留待后续单独评估。

## Acceptance Criteria

- [x] JSON-LD / OpenGraph 明确标识 Article/NewsArticle/BlogPosting/TechArticle/ScholarlyArticle/LearningResource 的 Generic HTML 可得到 `scope=primary_resource, role=primary`。
- [x] 没有上述明确页面语义证据的普通 HTML 仍保持 `landing_page, landing`。
- [x] Web Materializer 仍生成 `index.html`、`content.md`、`metadata.json`、`assets/*`、`webbundle.zip`。
- [x] `index.html` 成为 Web Materializer 的 primary artifact，且已成功获取的正文图片以内嵌 data URI 形式存在，因此文件脱离 Job 目录后仍可独立打开。
- [x] `webbundle.zip` 仍存在且包含原有 Markdown/metadata/assets；不作为公开 primary Asset。
- [x] Service 对 `WEB_MATERIALIZE` 继续只持久化一个公开 primary Asset，因此不增加公共 Asset 数量和归档交互复杂度。
- [x] Archive 现有逻辑无需新增目录语义即可把网页归档成 `.html`，`resource_format=document` / `图文`。
- [x] 直接受影响的 Generic Inspector、Web Materializer、Service acquisition/archive 回归用例已同步；本次环境未实际执行 pytest，限制见 Validation Evidence。

## Steps

1. `completed` — 冻结当前行为、确认最小修正边界与直接回归测试。
2. `completed` — 修正 Generic Inspector：只依据明确结构化页面类型证据提升 HTML 为 primary。
3. `completed` — 修正 Web Materializer：生成自包含 primary HTML，保留原有 ZIP bundle。
4. `completed` — 更新直接相关测试与必要文档说明。
5. `completed` — 完成净差异与代码契约静态复核；记录当前环境无法执行 pytest 的限制，并确认无 0041 scope drift。

## Implementation Summary

### Generic Web Inspect

`adapters/inspect_generic.py` 继续使用现有 bounded preview 和 metadata parser，只增加确定性的页面类型事实：

- OpenGraph `og:type=article`；
- JSON-LD `@type` 为 `Article`、`NewsArticle`、`BlogPosting`、`TechArticle`、`ScholarlyArticle`、`LearningResource`。

命中这些明确证据时，HTML Representation 为 `primary_resource / primary`；普通 HTML 仍为 `landing_page / landing`。没有加入正文长度、DOM 密度、`<article>` 标签、链接密度或评分阈值等自研启发式。

### Web Materializer / Archive

`acquisition/web_materializer.py` 仍生成完整 Job 工作集：

```text
index.html
content.md
metadata.json
assets/*
webbundle.zip
```

变化仅在用户主产物：

- `index.html` 的 Artifact role 为正式 `primary`，并成为唯一 primary artifact；
- 已成功抓取并校验的同源图片以 `data:<mime>;base64,...` 内嵌进 `index.html`；
- CSP 相应允许 `img-src ... data:`；
- Markdown 和 metadata 仍使用/记录 Job 内 `assets/*`；
- `webbundle.zip` 仍生成，但 role 为非 primary 的 `bundle` 工作产物。

Service 原有 `WEB_MATERIALIZE` 逻辑只持久化 bundle 的 primary artifact，因此无需修改 Service、Asset Schema 或数据库。Archive 原有后缀/格式映射已经支持 `.html`，因此无需增加目录型 Archive 或解 ZIP 特例。

## Validation Evidence

### 已完成的静态/契约验证

- 复核 `ArtifactBundle` 约束时发现：primary artifact 的 role 只能是 `primary` 或 legacy `bundle`。初版将 HTML 标记为 `sanitized_html + primary=True` 会被模型拒绝；已修正为正式 `role=primary`，没有放宽模型约束。
- 复核 Search → Service 规范化：Generic Search 的 `网页` 在持久化 ResultSet 前会规范为 `article`，与现有 generic primary webpage `ProviderSpec` 匹配，因此无需新增 Planner 转换。
- 复核默认 Provider 注册：`generic-web-materializer@1.0.0` 已支持 `primary_resource` 与 `landing_page` 两个 scope，无需修改路由。
- 复核 Archive：HTML 后缀已属于 document/图文格式，当前单文件发布路径可以直接复用。
- 从本计划创建提交到实现收口提交做 compare，净代码/测试/文档变化限定为：
  - `docs/CURRENT_ARCHITECTURE.md`
  - `acquisition/web_materializer.py`
  - `adapters/inspect_generic.py`
  - `tests/test_acquisition_service.py`
  - `tests/test_generic_inspector.py`
  - `tests/test_web_materializer.py`
- `inspect_generic.py` 的最终净变化仅为新增显式网页语义证据及对应分支，原有非网页 MIME/magic 行为与注释已恢复，避免顺带改变 PDF/音视频检查逻辑。

### 回归用例同步

- Generic Inspector：JSON-LD Article -> primary；OpenGraph article -> primary；普通 HTML -> landing。
- Web Materializer：HTML 是唯一 primary；ZIP 保留为工作 bundle；HTML 图片为 data URI；Markdown 仍引用 assets；CSP 保留。
- Service acquisition/archive：公开 Asset 为 `text/html`，Job 中 ZIP 仍存在，Archive 最终文件后缀为 `.html` 且图片自包含。

### 未执行项与原因

本次没有实际执行 pytest：

- 当前 GitHub 分支没有 status checks，也没有该提交对应的 workflow run；
- 当前执行容器无法解析 `github.com`，无法 clone/sync 分支到可执行目录后运行窄测试。

因此本计划的“completed”表示实现、直接回归用例和静态契约复核已经完成，不表示上述 pytest 已经在真实运行环境通过。后续同步到 Windows/OpenClaw 环境时，可优先运行这三个直接测试文件，而不需要跑全量测试。

## Complexity Check

Problem: 当前 HTML 一律落到 `landing_page`，同时 Web Materializer 的唯一公开 Asset 是 ZIP，导致用户资料库最终看到 ZIP 而不是可直接阅读网页。

Why current structure cannot solve it: Inspector 已有 metadata parser 但没有利用明确页面类型；Materializer 已生成 HTML 但把 ZIP 标为 primary，Service 又刻意只持久化 Web primary。

Simplest alternative considered: 只改文档解释现状，或归档时特殊解 ZIP。

Why insufficient: 前者不修复用户最终文件形态；后者会把目录发布/恢复/去重语义引入 Archive，复杂度远大于把现有 HTML 变成自包含主产物。

New source of truth introduced: 无。

New invariant introduced: Web Materializer 的 primary artifact 是可独立打开的 sanitized HTML；ZIP 是工作 bundle，不是用户主 Asset。

Failure modes introduced: 仅 data URI HTML 体积增加；图片仍受现有数量/单图/总量保护限制，未成功抓取的图片继续显示 placeholder。
