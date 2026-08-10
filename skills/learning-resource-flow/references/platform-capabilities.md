# 平台与执行能力参考

## 权威来源与使用边界

本参考是 Skill 规划搜索、创作者浏览、Inspection 和获取说明时的能力地图。当前存在三个不能
互相替代的事实层：

1. [`mcp/education-resources/contracts/platforms/platform-registry.json`](../../../mcp/education-resources/contracts/platforms/platform-registry.json)
   的 `registry_version=1.0.0` 保存平台身份、检索、历史 inspect/acquire 声明和 identity profile；
   当前共有 16 项，即 `generic` 加 15 个具体平台。
2. [`mcp/education-resources/contracts/capabilities/capability-descriptors.json`](../../../mcp/education-resources/contracts/capabilities/capability-descriptors.json)
   保存静态 Capability Descriptor；其独立 `catalog_version=1.1.0`、`registry_version=1.1.0`。
3. 当前部署 readiness、候选 Resolution/Representation、Eligibility、Plan/Execution binding、
   Provider Outcome、Asset 和 Job projection 都是运行时服务端事实，不能从前两个静态文件推断。

实际获取权威链固定为：

```text
Capability Descriptor
-> Runtime Readiness
-> persisted Resolution / Representation
-> Eligibility
-> Plan capability binding + authority_digest
-> fresh Execution binding
-> exact Provider
-> persisted Acquisition Outcome
-> Asset / AssetBundle
-> sanitized Job status projection
```

平台 Registry 的 `acquire=true`、平台名称、搜索结果 URL、扩展名或旧 options 都不能选择
Provider、strategy 或 scope。Provider 必须来自同一条已声明并在 start 时重新校验的 exact route；
没有隐式或静默 generic Provider fallback。`allow_safe_fallback` 也只允许 descriptor/readiness
明确声明的同 Provider、同 strategy、同 scope 边；当前 descriptor 均声明 fallback disabled。

读取本参考只能回答“某平台声明了什么搜索、浏览、认证、Inspection 或静态 capability”，不能
回答“当前部署是否 ready、某条内容是否相关、适合儿童、可信、完整、可下载或有权使用”。实际
选择平台仍由 `goal`、`resource_target` 和用户明示的 `constraints` 决定；不要因为表中列出平台
就无差别搜索全部平台。

## 当前静态 Capability Descriptor

当前静态 catalog 只有以下三条 exact acquisition route；每条仍须通过运行时 readiness、持久化
Resolution/Representation 与 Eligibility 才能进入 Plan：

| descriptor_id | platform | scope / representation | strategy | exact Provider | inspector | fallback |
|---|---|---|---|---|---|---|
| `cap_generic_document_primary_direct_v1` | `generic` | `primary_resource` / primary document | `direct_file` | `generic-direct@1.0.0` | `generic@1.0.0` | disabled |
| `cap_generic_webpage_landing_materialize_v1` | `generic` | `landing_page` / landing webpage | `web_materialize` | `generic-web-materializer@1.0.0` | `generic@1.0.0` | disabled |
| `cap_smartedu_document_primary_direct_v1` | `smartedu` | `primary_resource` / primary document | `direct_file` | `smartedu-resource@1.0.0` | `smartedu@1.0.0` | disabled |

当前 descriptor catalog 没有声明 `web_capture` route，也没有为 Bilibili、Ximalaya、Anna/Libgen
等历史平台下载路线声明可执行 capability。平台 Registry 或代码中存在旧 Downloader 并不足以
授权执行；缺少 exact descriptor/readiness/eligibility binding 时必须返回结构化不支持或能力
绑定失败，而不是由 generic Provider 接管。

## 平台搜索与 Inspection 规划地图

Registry 当前所有平台都声明 `search=true`、历史 `acquire=true`；后者只保留平台级历史能力
信息，不是当前可执行证明。`inspect=true` 仅限 `generic`、`bilibili`、`nlc`、
`annas-archive`（Libgen-backed）、`ximalaya`、`zhihu`、`smartedu` 这 7 个平台，其余 9 个平台
由服务端返回 `FEATURE_NOT_SUPPORTED`。creator browse 只有 `bilibili`、`douyin`、`zhihu`、
`weibo` 为 true。

| platform_id | 名称 | resource types | search | creator browse | auth mode / kind | 历史非网页 acquisition 声明 | 历史 webpage 声明 | inspect |
|---|---|---|---|---|---|---|---|---|
| generic | 通用 Web 搜索 | article, book, document, video, audio, course, dataset, other | 是 | 否 | none / none | 无 | 是 | 是（通用公开网页） |
| bilibili | 哔哩哔哩 | video | 是 | 是 | optional / cookie | platform_video | 是 | 是 |
| douyin | 抖音 | video | 是 | 是 | required / cookie | platform_video | 是 | 否（FEATURE_NOT_SUPPORTED） |
| zhihu | 知乎 | article | 是 | 是 | optional / cookie | 无 | 是 | 是 |
| smartedu | 国家中小学智慧教育平台 | document, video, audio, course, other | 是 | 否 | optional / token | platform_resource | 是 | 是 |
| ximalaya | 喜马拉雅 | audio | 是 | 否 | optional / cookie | platform_audio | 是 | 是 |
| cctv | 央视网 | video | 是 | 否 | none / none | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |
| yixi | 一席 | video | 是 | 否 | none / none | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |
| kepu | 科普中国 | article | 是 | 否 | none / none | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |
| baiduwenku | 百度文库 | document | 是 | 否 | none / none | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |
| runoob | 菜鸟教程 | article | 是 | 否 | none / none | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |
| nlc | 国家图书馆 | book | 是 | 否 | none / none | 无 | 是 | 是 |
| open163 | 网易公开课 | course | 是 | 否 | none / none | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |
| annas-archive | Anna's Archive | book | 是 | 否 | none / none | platform_book | 是 | 是（Libgen-backed） |
| weibo | 微博 | article | 是 | 是 | required / cookie | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |
| wechat | 微信公众号 | article | 是 | 否 | optional / cookie | 无 | 是 | 否（FEATURE_NOT_SUPPORTED） |

resource types 是平台 Adapter 声明的结果形态范围，不是对某条结果实际内容的保证。auth
mode/kind 是会话路由元数据，不代表平台质量或结果可信度。历史 `acquire=true` 与 webpage
声明也不表示当前部署存在 exact Provider route；下载仍须遵守用户确认、访问权限、版权和服务端
Capability Authority。

## 当前适配来源说明

- Anna's Archive 当前搜索与 Inspection 说明使用 Libgen-backed 路线。该事实只用于解释结果
  来源和历史能力边界，不把平台名或该路线自动当作权利、可靠性、内容质量或可执行下载证明。
- 微信公众号当前 Adapter 使用 Sogou Weixin-backed 搜索路线。返回结果应理解为搜狗索引的
  微信内容，不等同于直接访问微信公众号后台，也不自动证明账号身份、文章完整性或内容质量。
- Registry 的 webpage 声明只是历史平台能力元数据，不是“网页回退”。对 `inspect=false`、
  readiness 不足或 exact capability 缺失的平台，不得静默改走 generic webpage route，也不得把
  `FEATURE_NOT_SUPPORTED` 解释成资源不存在。

Inspector 的“可用”只表示服务端有对应的受控检查实现，不构成相关性、可信度、儿童适用性、
版权、Eligibility 或可下载保证。
