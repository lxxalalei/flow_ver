# Platform Registry

`platform-registry.json` 是 education-resources MCP 当前平台能力与 Identity profile 的机器
权威来源，`registry_version=1.0.0`。它属于服务内部 Retrieval 契约，不是新的 MCP Tool，
也不允许模型提交 descriptor、凭据、命令或本地路径。

对应 JSON Schema 位于
[`../schemas/platform-registry.schema.json`](../schemas/platform-registry.schema.json)。运行时由
`retrieval.registry` 严格校验，再通过 `adapters.base.AdapterDescriptor` 转换为冻结、递归
不可变且可哈希的 descriptor。内置 Adapter 注册时必须与 Registry 精确一致；外部或历史
测试 stub 仍可只声明 `platform_id`。

## 当前范围

Registry 固定包含 `generic` 与 15 个内置平台，共 16 项：

```text
generic, bilibili, douyin, zhihu, smartedu, ximalaya, cctv, yixi,
kepu, baiduwenku, runoob, nlc, open163, annas-archive, weibo, wechat
```

- 所有平台当前都声明 `search=true`、`acquire=true`；`inspect` 精确启用七个平台：
  `generic`、`bilibili`、`nlc`、`annas-archive`、`ximalaya`、`zhihu`、`smartedu`。
  其余九个平台保持 `inspect=false`，不会被静默回退到 generic Inspector。
- creator browse 仅限 `bilibili`、`douyin`、`zhihu`、`weibo`。
- 专用 acquisition 只覆盖 Bilibili/Douyin 视频、SmartEdu 资源、Ximalaya 音频和
  Anna's Archive 图书；`webpage` 表示受控通用网页回退，不等于平台专用下载器。
- Anna's Archive 搜索与下载实现当前由 Libgen 镜像提供；Wechat 搜索当前由 Sogou
  Weixin 提供。平台显示名不能掩盖实际实现来源，也不构成权利或质量证明。

认证字段只描述当前 Adapter 的会话需求。它与 `sessions.py` 的登录态捕获、探测和存储
Registry 分离；不得从某个平台存在 Session 配置反推其搜索或下载一定需要认证。

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
3. 更新 Skill 的 `references/platform-capabilities.md`，但仍以本 JSON 为机器权威。
4. 保持凭据、Cookie、Token、命令、下载 URL 和本地路径不进入 Registry。
5. 新增或修改 inspect 能力时，必须同步实际 Inspector Router、平台固定夹具和能力一致性测试；
   Registry 不得提前声明未实现的平台支持。未启用平台由服务层返回结构化
   `FEATURE_NOT_SUPPORTED`。

## Inspection 边界（0019）

首批 Inspector 只做有界、服务端控制的资源核验：

- Generic 使用受限 GET、逐跳 SSRF/重定向校验、1 MiB 流式上限和 MIME/魔数交叉验证。
- Bilibili、NLC、Anna/Libgen、Ximalaya、Zhihu、SmartEdu 使用各自平台域名和元数据策略；
  Anna/Libgen 的当前实现事实不等于已完成 Anna's Archive 官方来源或生产授权验收。
- 输出只允许服务端生成的 Representation 元数据和可用性/失败状态，不返回 locator、文件字节、
  本地路径、Cookie 或 Token；Inspect 不下载、不归档。
- Registry 的 inspect 开关表示代码能力已接入，不表示真实平台网络、授权、条款或反爬验收通过。
