# Platform Registry

`platform-registry.json` 是 education-resources MCP 的平台身份、检索和历史能力声明机器
Registry，`registry_version=1.0.0`。它属于服务内部 Retrieval 契约，不是当前 acquisition
执行权威，也不是新的 MCP Tool；模型不能提交 Registry/descriptor、凭据、命令或本地路径。

对应 JSON Schema 位于
[`../schemas/platform-registry.schema.json`](../schemas/platform-registry.schema.json)。运行时由
`retrieval.registry` 严格校验，再通过 `adapters.base.AdapterDescriptor` 转换为冻结、递归
不可变且可哈希的平台检索/身份/历史声明 descriptor；它不是 Capability Descriptor。内置 Adapter 注册时
必须与 Registry 精确一致；外部或历史测试 stub 仍可只声明 `platform_id`。

## 当前范围

Registry 固定包含 `generic` 与 15 个内置平台，共 16 项：

```text
generic, bilibili, douyin, zhihu, smartedu, ximalaya, cctv, yixi,
kepu, baiduwenku, runoob, nlc, open163, annas-archive, weibo, wechat
```

- 所有平台都声明 `search=true`，并保留 0018/0021 时期的 `acquire=true` 历史字段；
  `acquire` 和 `acquisition.strategies` 不能证明当前存在可执行 Provider route。
- Registry 中 `inspect=true` 精确覆盖七个平台：`generic`、`bilibili`、`nlc`、
  `annas-archive`、`ximalaya`、`zhihu`、`smartedu`。其余九个平台保持 `inspect=false`，
  不会被静默回退到 generic Inspector。
- creator browse 仅限 `bilibili`、`douyin`、`zhihu`、`weibo`。
- Bilibili/Douyin 视频、SmartEdu 资源、Ximalaya 音频、Anna's Archive 图书以及各平台
  `webpage` strategy 都是 Registry 保留的历史能力声明，不是当前 acquisition route 清单。
- Anna's Archive 的历史搜索/Inspection 来源为 Libgen-backed 路线；Wechat 搜索当前由
  Sogou Weixin 提供。平台显示名不能掩盖实际实现来源，也不构成权利、质量或执行能力证明。

## Acquisition 运行时路由（Tool catalog 1.6）

Platform Registry 只描述平台身份、Search/Inspect 与历史能力声明。当前 acquisition 不再维护独立 Capability Descriptor catalog。
执行路线由 `acquisition/planner.py` 中的小型 `ProviderSpec` 与当前部署的 exact Provider registration 共同决定，并且必须以当前 Resolution/Representation 为输入。

当前简化路线至少包括：

| representation | strategy / scope | exact Provider |
|---|---|---|
| generic document primary | `direct_file` / `primary_resource` | `generic-direct@1.0.0` |
| generic webpage primary | `web_materialize` / `primary_resource` | `generic-web-materializer@1.0.0` |
| generic webpage landing | `web_materialize` / `landing_page` | `generic-web-materializer@1.0.0` |
| SmartEdu document primary | `direct_file` / `primary_resource` | `smartedu-resource@1.0.0`（仅实际注册时） |

Prepare 根据 fresh Representation 生成 PlanItem；Start 重新读取当前 Resolution，核对 representation 未漂移，并确认 Plan 中的 exact Provider 仍注册且支持相同 scope/strategy。该检查不生成 Readiness Snapshot、Eligibility ID 或 binding digest。

Provider 失败后不切换 Generic/其他 Provider、scope 或 strategy。Bilibili、Douyin、Ximalaya、Anna/Libgen 等路线如果没有当前 `ProviderSpec + Representation + exact Provider`，就保持结构化 blocked/unsupported，不能从 Registry 的历史 `acquire=true` 推导执行能力。

未来新增 acquisition route 时，应最小化地新增/调整 ProviderSpec、Inspector 产生的 Representation、Provider registration 和业务回归测试；不得重新建立 Descriptor → Readiness → Eligibility → digest 状态链。

## Identity profile

逻辑资源身份按以下顺序解析：

```text
platform native ID -> ISBN -> DOI -> platform-aware canonical URL
                   -> title + creator + edition weak fingerprint
```

默认 URL 规则只规范 scheme/host 并移除 fragment。query 参数只有在当前平台的
`identity_profile.canonical_url.removable_query_parameters` 明确列出时才能移除；SmartEdu
的 `contentId`、`courseId`、`catalogType` 等查询参数保持身份意义。Registry 与代码内置
fallback 由测试锁定一致，错误平台不能复用其他平台的可清理参数。

内部 Identity 只是去重证据，不是公共 `resource_id`。`resource_search` 与
`resource_browse_creator` 在 URL 安全校验和空标题过滤后执行保守去重，保持首见顺序并只
补充缺失事实；最终公共候选才由服务端生成随机 `resource_id`。强身份冲突不得自动合并，
而不同平台的 native ID 在同一 ISBN/DOI 下属于不可直接比较的 locator，不构成跨平台冲突。

## 修改纪律

修改 Registry 时必须同步：

1. 更新 `platform-registry.schema.json` 和严格 loader 语义校验。
2. 更新 Adapter descriptor 一致性测试和 Identity Golden Cases。
3. 平台身份、检索与历史声明仍以本 JSON 为机器权威；acquisition 执行路线以当前 ProviderSpec、Representation 和 exact Provider registration 为准。
4. 保持凭据、Cookie、Token、命令、下载 URL 和本地路径不进入 Registry。
5. 新增或修改 inspect 能力时，必须同步实际 Inspector Router、平台固定夹具和能力一致性测试；
   Registry 不得提前声明未实现的平台支持。未启用平台由服务层返回结构化
   `FEATURE_NOT_SUPPORTED`。
6. 新增 acquisition route 必须同步 ProviderSpec、Inspector Representation、exact Provider registration 与业务测试；不得通过改 `acquire=true` 或 `acquisition.strategies` 扩大当前执行能力。

## Inspection 边界（0019）

首批 Inspector 只做有界、服务端控制的资源核验：

- Generic 使用受限 GET、逐跳 SSRF/重定向校验、1 MiB 流式上限和 MIME/魔数交叉验证。
- Bilibili、NLC、Anna/Libgen、Ximalaya、Zhihu、SmartEdu 使用各自平台域名和元数据策略；
  Anna/Libgen 的当前实现事实不等于已完成 Anna's Archive 官方来源或生产授权验收。
- 输出只允许服务端生成的 Representation 元数据和可用性/失败状态，不返回 locator、文件字节、
  本地路径、Cookie 或 Token；Inspect 不下载、不归档。
- Registry 的 inspect 开关表示对应 Inspection Router 代码能力已接入，不表示真实平台网络、
  授权、条款或反爬验收通过，更不授予 acquisition 执行能力。
