# 平台能力参考

## 权威来源与使用边界

本参考是 Skill 规划平台路线时的能力地图。机器权威是
mcp/education-resources/contracts/platforms/platform-registry.json（registry_version 1.0.0）；
下表只复述该注册表当前的 16 项记录：generic 加 15 个具体平台。

读取本参考只能回答“某平台当前声明支持什么检索、浏览、认证和获取路线”，不能回答
“内容是否相关、适合儿童、可信、完整、可下载或有权使用”。平台名、平台能力、
登录方式、来源标签和专用获取策略都不是内容质量证据。实际选择哪些平台，仍由目标、
resource_target 和用户明示的 constraints 决定；不要因为注册表列出平台就无差别搜索全部
平台。

注册表当前所有平台都声明 search=true、acquire=true；inspect=true 仅限 generic、bilibili、
nlc、annas-archive（Libgen-backed）、ximalaya、zhihu、smartedu 这 7 个平台，其余 9 个
平台为 inspect=false，并由服务端返回 `FEATURE_NOT_SUPPORTED`。creator browse
只有 bilibili、douyin、zhihu、weibo 为 true。下表的“专用 acquisition”只列出除
webpage 以外的 registry 策略；每一行的“网页回退”均表示 registry 同时声明 webpage。

## 当前平台能力

| platform_id | 名称 | resource types | search | creator browse | auth mode / kind | 专用 acquisition | 网页回退 | inspect |
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

resource types 是平台适配器声明的结果形态范围，不是对某一条结果实际内容的保证。
auth mode/kind 是会话路由元数据，不代表平台质量或结果可信度。acquire=true 只表示
服务端存在受控获取路线；仍需遵守用户确认、访问权限、版权和下载安全流程。

## 当前适配来源说明

- Anna's Archive 当前适配器使用 Libgen-backed 路线。该事实用于解释结果来源和能力边界，
  不把 Anna's Archive 这个平台名或该路线自动当作权利、可靠性或内容质量证明。
- 微信公众号当前适配器使用 Sogou Weixin-backed 路线。返回结果应理解为搜狗索引的
  微信内容，不等同于直接访问微信公众号后台，也不自动证明账号身份、文章完整性或内容质量。
- generic 与各平台的 webpage 回退都只是受控公开网页路线；不能据此推断网页已经被检查、
  下载可用或允许再分发。对 inspect=false 的平台，不得静默把网页回退当作该平台已经
  核验，也不得把 `FEATURE_NOT_SUPPORTED` 解释成资源不存在。

本批次只记录注册表已经声明的检索、创作者浏览、获取、认证和 Inspection 能力；Anna's
Archive 的 Inspection 明确是 Libgen-backed 路线，不承诺 Anna API。Inspector 的“可用”只
表示服务端有对应的受控检查实现，不构成相关性、可信度、儿童适用性、版权或可下载保证。
