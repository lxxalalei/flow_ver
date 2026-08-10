# Source Routing Guidance

本文件负责“去哪里搜、为什么搜这些来源”，不负责候选语义评分，也不证明平台当前可获取资源本体。

## 基本原则

来源选择由 `goal + resource_target + explicit constraints + 当前 Gap` 驱动，而不是由用户身份、平台热度或 Registry 列表驱动。

优先选择能直接提供所需内容或证据的少量来源；不同来源应有互补价值，而不是为了“平台数量”机械扩散。

## 三层事实不要混淆

1. **Platform Registry**：平台身份、resource types、search / creator browse / Inspect 等静态声明，以及 `auth_mode` / `auth_kind` 等认证属性；
2. **Capability Descriptor**：设计上支持的 resource/scope/strategy/provider 组合；
3. **Deployment Readiness / Session State / Resolution / Eligibility**：当前部署、当前合法登录态、当前候选、当前权限与表示的实际事实。

Registry/Descriptor 存在都不能单独证明“现在能下载这个资源”。当前是否登录由 session-manager/实际服务状态判断；当前是否可获取必须继续进入 Readiness → Resolution/Representation → Eligibility → Plan/Execution 权威链。平台能力机器事实见 [`mcp/education-resources/contracts/`](../../../mcp/education-resources/contracts/README.md)。

不要在本文件维护完整平台能力表、固定登录状态表或 acquisition route 快照；需要这些事实时读取机器 Registry/Descriptor 和当前服务状态。

## 来源路线

按任务优先考虑来源族，而不是固定平台名单：

- 官方/公共教育机构：教材、课程、政策、权威公开材料；
- 专业内容平台：结构化课程、视频、音频、文章；
- 创作者/社区：实践经验、解释、案例、补充视角；
- 图书/文献目录：版本、作者、ISBN、馆藏或可获取表示线索；
- Generic Web：用于补足未被专门 Adapter 覆盖的公开网页资源。

同一个 SearchDirection 通常选 2–3 个最相关来源即可。只有存在来源覆盖 Gap 时再扩展。

## Search 与 Creator Browse

用户是在“按主题找内容”时使用普通 `resource_search`。只有用户的目标明确是浏览某个创作者/账号已有内容，且当前平台 Registry/Tool 能力实际支持 creator browse 时，才使用 `resource_browse_creator`。

典型 creator browse 意图包括：用户提供创作者主页/账号并询问“这个人发了什么”“把这个作者的相关内容找出来”等。普通内容链接、单条资源 URL 或仅仅提到创作者名字，都不能自动转换成 creator browse 身份。

`resource_browse_creator` 返回的仍然是 ResultSet，后续必须经过相同的 Evaluate → Presentation → Selection 流程；它不是批量下载入口。平台不支持、需要认证或返回其他结构化失败时保留真实状态，不偷偷改成另一种浏览/下载路线。

## 可信来源定向搜索

有些来源知识属于 Skill 的 discovery guidance，而不是平台 Capability。它们用于在“明确需要高可信来源且宽泛搜索质量不足”时缩小搜索空间。

可以在 Generic Web 查询中使用 `site:域名` 做定向发现，但遵守：

- 不是每轮搜索都加 `site:`；先由目标、显式来源要求或当前 Gap 判断是否需要；
- 一条 query 最多绑定一个站点，避免把搜索范围收得不可解释；
- 用户明确指定来源时优先尊重用户来源；
- 站点只表示“优先发现来源”，不证明内容正确、适合当前用途、当前可访问或可获取；
- 某站点搜索失败只表示这条 discovery route 没拿到结果，不等于资源不存在，也不能触发 acquisition fallback。

当前可优先参考的稳定来源线索：

| 场景 | 来源线索 |
| --- | --- |
| 公共教育/教材 | `eduyun.cn`、`pep.com.cn` |
| 汉字/古诗文 | `zdic.net`、`gushiwen.cn`、`edu.cnr.cn` |
| 教案/练习/编程学习 | `21cnjy.com`、`runoob.com` |
| 科学与自然 | `cdstm.cn`、`school.kepu.net.cn`、`xiaoxiaotong.org`、`ppbc.iplant.cn` |
| 艺术 | `namoc.cn` |
| 消防/防灾/健康 | `119.gov.cn`、`data.earthquake.cn`、`chinacdc.cn` |

这些域名是“curated preferred discovery sources”，不是 security allowlist、network allowlist、Capability Descriptor 或内容审批清单。实际搜索与页面可用性仍以当前工具结果为准。

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

涉及健康、安全、灾害、人体、公共规则或其他事实错误代价较高的主题时，优先官方、专业机构和可核验原始来源；学科同步优先公共教育平台、出版社和明确教材配套来源；科学、人文、艺术探索优先博物馆、科技馆、图书馆、公共文化和专业科普来源。聚合页、转载和平台热度可以帮助发现，但不自动提高 SemanticReview。

## 登录与搜索质量

认证属性和当前登录状态分开处理：

- Registry 的 `auth_mode` / `auth_kind` 只说明平台静态认证要求；
- 当前用户是否已有有效会话只看 session-manager 或真实工具返回，不能靠 Markdown 表或聊天记忆；
- 不默认在首次搜索前逐个平台做登录检查，避免把认证变成无必要的前置阻塞；
- 如果 Registry 明确要求认证且用户当前任务就指定该平台，或真实搜索/Inspect 返回 AUTH_REQUIRED，再进入 session-manager 流程；
- 对 optional auth，当前公开结果已经足够完成任务时不主动打断用户登录；只有结果明显不足、且合法登录很可能改变当前 Gap 时，才把登录作为一个可选下一步；
- 登录完成后重新读取 Flow/当前服务状态，不把“已登录”直接推导成搜索、Inspect 或获取成功。

## 认证与策略

需要登录、版权/许可判断或平台策略限制时，不通过其他 Provider 静默绕过。把结构化限制保留给后续 Inspect/Acquisition 和用户解释。

如果某个平台当前没有 native search/browse 能力，不把 Generic Web 结果伪装成该平台原生搜索。只有用户目标允许“查找该平台公开网页”这一不同 discovery route 时，才可明确标注为 Generic Web 发现；它仍不改变后续 Capability/Eligibility 权威链。
