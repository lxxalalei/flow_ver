# 0063 — 清洗网页 Reader HTML 模板

> 处置：completed/superseded。当前 Generic Web 事实以 [`docs/CURRENT_ARCHITECTURE.md`](../../../docs/CURRENT_ARCHITECTURE.md) 为准；剩余真实页面验收已并入 [0028-real-openclaw-platform-e2e.md](0028-real-openclaw-platform-e2e.md)。

- 状态：in_progress
- 创建日期：2026-08-20
- 完成日期：未完成
- 范围：Generic Web Materializer 的清洗后 `index.html` 阅读模板、主题依赖、聚焦测试与架构说明

## Goal

网页抓取后继续由 Trafilatura 负责正文清洗；清洗结果不再直接作为裸 HTML 交付，而是统一放入一套适合阅读、移动端和打印的 HTML Reader 模板中。`source.html` 仍保持原始响应不变。

目标产物：

```text
HTTP HTML
  -> source.html                  # 原始响应，完全不改
  -> Trafilatura 清洗
       -> content.md              # 语义正文
       -> cleaned HTML fragment
            -> Reader template
                 -> index.html    # 好看的单文件阅读页
  -> metadata.json
  -> webbundle.zip
```

## Open-source evidence

调查的成熟 classless CSS / 文档主题包括：

- Simple.css：MIT，classless，响应式，支持图片、表格、代码、引用、dark mode、print；
- Pico.css：MIT，语义 HTML/classless 版本成熟，但更偏完整 CSS framework；
- Water.css：MIT，体积很小，适合简单静态页面；
- Sakura：MIT，文本阅读友好；
- cleanrmd：把清洗/渲染后的文档套用 classless CSS 主题，内置 Simple.css/Pico/Water/Sakura 等，架构思路与本需求高度一致。

本轮采用 **Simple.css 2.3.7** 作为 vendored 基础主题，并加入少量本项目 Reader 覆盖样式。理由：现有 Trafilatura 输出已经是语义 HTML，classless CSS 可直接工作；无需前端框架、JS、npm 或运行时网络依赖。

## Non-goals

- 不替换 Trafilatura，不重新实现正文抽取器。
- 不下载原网页的全部 CSS/JS/CDN 资源，不做浏览器级网页克隆。
- 不引入 React/Vue/Tailwind/Bootstrap/npm 构建链。
- 不把主题做成用户可配置的主题系统。
- 不增加 JS、交互组件或阅读进度等功能。
- 不改变 `source.html`、`content.md` 的事实语义。
- 不新增 MCP Tool。

## Business invariants

1. `source.html` 必须继续是 fetch 成功得到的原始响应字节。
2. Reader 模板只作用于 Trafilatura 的清洗后派生视图 `index.html`。
3. `index.html` 单独保存/打开时也必须有完整样式，不依赖 CDN。
4. 清洗失败时仍生成同一 Reader 外壳，明确提示 `source.html` 已保存；不能因为模板渲染而掩盖 extraction failure。
5. 原网页中的链接和图片保持 Trafilatura 清洗后的真实 URL，不发明本地资产或伪造离线完整性。
6. 不引入脚本；生成页 CSP 只允许必要的内联样式和已有 http/https/data 图片。
7. Vendored Simple.css 保留 MIT 版权/许可证声明。

## Acceptance Criteria

- AC-01：成功清洗时 `index.html` 是完整 HTML 文档，并含统一 Reader header/main/footer。
- AC-02：Reader 使用 vendored Simple.css + 小量项目覆盖样式，CSS 内联进 `index.html`，无外部 stylesheet/CDN。
- AC-03：标题、段落、图片、表格、blockquote、pre/code 等清洗后语义元素能由主题直接排版。
- AC-04：移动端布局可读，正文宽度受控；打印时去除不必要 UI 并保留正文。
- AC-05：原始 `source.html` 字节完全不变；`content.md` 继续由 Trafilatura 产生。
- AC-06：extraction failure 仍返回 partial，且 styled `index.html` 明确指向 `source.html`。
- AC-07：`metadata.json` 记录 Reader theme/template 事实。
- AC-08：聚焦测试验证模板、内联 CSS、无 CDN、source snapshot 不变、失败路径和 zip 内容。

## Implemented

- vendored `Simple.css 2.3.7` 与原 MIT LICENSE，并通过 package-data 随 MCP 安装；
- `WebMaterializer` 保持原始 `source.html` 和 Trafilatura `content.md` 行为不变；
- Trafilatura 的 cleaned HTML 会剥掉其 document wrapper，只取清洗后的 body 内容，再放入统一 `clean-reader-v1` Reader shell；
- Reader 包含来源栏、正文区域、原网页链接和来源说明 footer；CSS 全部内联，不依赖 CDN/npm/JS；
- 在 Simple.css 上只增加正文宽度、移动端、图片、表格、长链接和打印所需的薄覆盖样式；
- Reader CSP 禁止脚本/对象/frame，只开放内联样式以及现有 http/https/data 图片；
- extraction failure 不降级成裸 HTML，而是在同一 Reader 中显示 `source.html` 提示，Job 仍保持 partial；
- `metadata.json` / AcquisitionResult 增加 `reader_template`、`reader_theme` 和 embedded CSS 事实；
- 架构文档已更新；聚焦测试已补充 standalone Reader、wrapper 去重、语义元素、失败路径、zip 与 metadata 契约。

## Steps

- [x] completed：核对现有 WebMaterializer，确认当前已完成 fetch + Trafilatura 清洗，但 `index.html` 基本直接使用清洗输出
- [x] completed：调查成熟 classless CSS / 文档主题并选择 Simple.css
- [x] completed：vendor Simple.css 与许可证，并实现 Reader HTML 外壳
- [x] completed：更新 metadata / package data / 架构说明
- [x] completed：补聚焦测试
- [ ] in_progress：在可运行仓库环境执行聚焦测试，并用真实网页做一次最终 Reader 视觉/内容复测

## Validation

目标测试：

```text
pytest tests/test_web_materializer.py tests/test_rendering_download.py tests/test_zhihu_materialize_routing.py
```

已完成静态回读：

- 当前分支中的 `web_materializer.py` 已完整回读，Reader shell / CSS 内联 / source 写入 / extraction 状态与 metadata 路径一致；
- `test_web_materializer.py` 已回读，覆盖 source snapshot 精确保留、单一 html/body wrapper、Simple.css 内联、MIT notice、语义元素、失败 partial 与 zip；
- `pyproject.toml` 已包含两个 vendor 文件的 package-data；
- `CURRENT_ARCHITECTURE.md` 已描述新的 fetch → Trafilatura → Reader 链路。

未实际执行：

- 当前执行容器没有该仓库副本，并且尝试从 GitHub clone 时 DNS 无法解析 `github.com`，因此上述 pytest **尚未运行**；
- 真实网页经 OpenClaw/MCP 下载后打开 `index.html` 的视觉复测也尚未执行。

不得把新增测试或静态回读写成“测试通过”。

## Result

实现和公共产物契约已经落盘；计划保持 `in_progress`，直到聚焦测试与至少一个真实网页 Reader 复测有实际运行证据。
