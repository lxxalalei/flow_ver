# 0070 — 内容感知的离线 HTML 设计

- 状态：completed
- 创建日期：2026-08-25
- 范围：Generic Web 清洗结果的 Agent DesignSpec 与 MCP 本地完整渲染

## Goal

用户要求精美、内容感知的网页交付物时，Agent 读取一个有界且显式标记截断的设计上下文，依据 HTML Design Skill 产生结构化 DesignSpec；MCP 将 Job 中已经完整清洗并嵌入图片的正文原样注入自包含 Reader，更新真实文件与 Job 记录。

## Non-goals

- 不让模型重写、摘要或搬运完整正文；
- 不修改或删除 `source.html`、`content.md`；
- 不允许任意 CSS、JavaScript、远程字体或远程资源；
- 不把 HTML 设计变成所有下载的固定前置流程；
- 不引入 Design Job、模板数据库、主题 Registry 或第二份内容事实源；
- 不处理一个 Download Job 内多个网页产物的歧义。

## Acceptance Criteria

- `resource_html_design(context)` 只接受已完成的单网页 Download Job，返回主题判断所需的标题、来源、显式有界摘录、结构统计和提纲；
- `resource_html_design(render)` 只接受 schema 允许的 DesignSpec，完整保留现有 Reader 正文片段；
- 最终 HTML 自包含、无脚本、无外链样式，支持移动端、打印与键盘焦点；
- `metadata.json`、`job.json` 与实际 `index.html` 大小同步；
- active Skill 只在用户明确要求视觉优化时进入 HTML Design 路线；
- MCP stdio schema、聚焦测试和全量测试通过。

## 复杂度举证

```text
Problem:
当前固定 clean-reader-v2 无法让 Agent 在清洗完成后依据实际内容设计页面，也没有受控的读摘要/写回 Artifact 边界。

Why current structure cannot solve it:
Skill 不能直接安全改写终态 Job；resource_job_status 不提供设计上下文，直接覆盖 index.html 会让 Job 文件记录失真。

Simplest alternative considered:
让模型直接生成完整 HTML，或在 resource_download 前仅凭 URL/标题选择固定主题。

Why that alternative is insufficient:
完整 HTML 会占用大量上下文并可能截断正文；下载前没有清洗后的结构与内容证据，无法做内容感知设计。

New source of truth introduced:
无。source.html 与 content.md 保持事实源；DesignSpec 只是 metadata.json 中的衍生呈现事实。

New invariant introduced:
render 前后的 Reader main 正文片段必须逐字节相同；只允许单网页终态 Job。

Failure modes introduced:
设计规格无效、Job 类型不支持、产物已归档/缺失、单 Job 多网页歧义；全部显式失败。
```

## Steps

- [x] completed：核对当前固定 Reader、Job 文件登记和公共 Tool 边界。
- [x] completed：调研 Claude Code 官方 Artifacts 文档及其内置 `artifact-design` 设计原则。
- [x] completed：实现 Design Context、DesignSpec、本地 Renderer 与公共 Tool。
- [x] completed：更新 active Skill 和架构文档。
- [x] completed：运行聚焦测试、stdio Tool probe、全量回归与桌面/窄屏视觉验收。
