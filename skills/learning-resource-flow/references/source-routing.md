# Source Routing Guidance

本文件负责“去哪里搜、为什么搜这些来源”，不负责候选语义评分，也不证明平台当前可获取资源本体。

## 基本原则

来源选择由 `goal + resource_target + explicit constraints + 当前 Gap` 驱动，而不是由用户身份、平台热度或 Registry 列表驱动。

优先选择能直接提供所需内容或证据的少量来源；不同来源应有互补价值，而不是为了“平台数量”机械扩散。

## 三层事实不要混淆

1. **Platform Registry**：平台身份、搜索/Inspect 等静态声明；
2. **Capability Descriptor**：设计上支持的 resource/scope/strategy/provider 组合；
3. **Deployment Readiness / Resolution / Eligibility**：当前部署、当前候选、当前权限与表示的实际事实。

Registry/Descriptor 存在都不能单独证明“现在能下载这个资源”。平台能力机器事实见 [`mcp/education-resources/contracts/`](../../../mcp/education-resources/contracts/README.md)。

## 来源路线

按任务优先考虑来源族，而不是固定平台名单：

- 官方/公共教育机构：教材、课程、政策、权威公开材料；
- 专业内容平台：结构化课程、视频、音频、文章；
- 创作者/社区：实践经验、解释、案例、补充视角；
- 图书/文献目录：版本、作者、ISBN、馆藏或可获取表示线索；
- Generic Web：用于补足未被专门 Adapter 覆盖的公开网页资源。

同一个 SearchDirection 通常选 2–3 个最相关来源即可。只有存在来源覆盖 Gap 时再扩展。

## 资源类型不是平台路由器

`video`、`book`、`document`、`course` 等只是资源语义类型，不能据此直接决定 Provider 或 Acquisition strategy。

例如：

- book 搜索命中图书馆目录，可能只有 metadata/landing page；
- video 平台可能当前只有搜索/Inspect，没有 primary acquisition；
- 普通网页可能通过 web materialization 得到可离线阅读的 representation。

是否能获取必须进入 Inspect/Capability/Eligibility 权威链确认。

## 搜索词

查询应围绕主题、目标、必要限定和用户真正需要的内容形式，不使用“优质、权威、高赞、适合孩子”等评价词替代后续审查。

需要横向比较时，优先改变 SearchDirection 或来源族，而不是无限堆近义词。

## 认证与策略

需要登录、版权/许可判断或平台策略限制时，不通过其他 Provider 静默绕过。把结构化限制保留给后续 Inspect/Acquisition 和用户解释。
