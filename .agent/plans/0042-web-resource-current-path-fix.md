# 0042 — 现有网页资源语义与可见归档修正

- 状态：in_progress
- 创建日期：2026-08-13
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

- [ ] JSON-LD / OpenGraph 明确标识 Article/NewsArticle/BlogPosting/TechArticle/ScholarlyArticle/LearningResource 的 Generic HTML 可得到 `scope=primary_resource, role=primary`。
- [ ] 没有上述明确页面语义证据的普通 HTML 仍保持 `landing_page, landing`。
- [ ] Web Materializer 仍生成 `index.html`、`content.md`、`metadata.json`、`assets/*`、`webbundle.zip`。
- [ ] `index.html` 成为 Web Materializer 的 primary artifact，且已成功获取的正文图片以内嵌 data URI 形式存在，因此文件脱离 Job 目录后仍可独立打开。
- [ ] `webbundle.zip` 仍存在且包含原有 Markdown/metadata/assets；不作为公开 primary Asset。
- [ ] Service 对 `WEB_MATERIALIZE` 继续只持久化一个公开 primary Asset，因此不增加公共 Asset 数量和归档交互复杂度。
- [ ] Archive 现有逻辑无需新增目录语义即可把网页归档成 `.html`，`resource_format=document` / `图文`。
- [ ] 直接受影响的 Generic Inspector、Web Materializer、Service acquisition/archive 回归得到窄验证。

## Steps

1. `in_progress` — 冻结当前行为、确认最小修正边界与直接回归测试。
2. `pending` — 修正 Generic Inspector：只依据明确结构化页面类型证据提升 HTML 为 primary。
3. `pending` — 修正 Web Materializer：生成自包含 primary HTML，保留原有 ZIP bundle。
4. `pending` — 更新直接相关测试与必要文档说明。
5. `pending` — 执行最小充分验证，复核无 0041 scope drift 后归档本计划。

## Complexity Check

Problem: 当前 HTML 一律落到 `landing_page`，同时 Web Materializer 的唯一公开 Asset 是 ZIP，导致用户资料库最终看到 ZIP 而不是可直接阅读网页。

Why current structure cannot solve it: Inspector 已有 metadata parser 但没有利用明确页面类型；Materializer 已生成 HTML 但把 ZIP 标为 primary，Service 又刻意只持久化 Web primary。

Simplest alternative considered: 只改文档解释现状，或归档时特殊解 ZIP。

Why insufficient: 前者不修复用户最终文件形态；后者会把目录发布/恢复/去重语义引入 Archive，复杂度远大于把现有 HTML 变成自包含主产物。

New source of truth introduced: 无。

New invariant introduced: Web Materializer 的 primary artifact 是可独立打开的 sanitized HTML；ZIP 是工作 bundle，不是用户主 Asset。

Failure modes introduced: 仅 data URI HTML 体积增加；图片仍受现有数量/单图/总量保护限制，未成功抓取的图片继续显示 placeholder。
