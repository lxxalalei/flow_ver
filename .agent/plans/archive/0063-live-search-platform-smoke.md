# Task Spec 0063：全平台真实搜索 Smoke 审计

- 状态：completed
- 创建日期：2026-08-20
- 完成日期：2026-08-20
- 范围：当前注册的 Search Adapter 与 Generic 搜索入口，只读真实联网验证

## Goal（必填）

用户/系统能够：获得当前各搜索平台“正常、需登录、失效或结果可疑”的真实运行清单，并保留足够错误证据供后续定向修复。

## Non-goals（必填）

- 本轮不修复新发现的平台问题，不修改 Adapter、Schema 或业务能力。
- 不测试下载、归档、Batch 完整枚举或需要用户账户的登录捕获。
- 不把 `AUTH_REQUIRED`、平台明确不支持关键词或无凭据误报为站点故障。

## Acceptance Criteria（必填）

### AC-01

```text
Given: 当前运行时注册的所有搜索平台
When: 使用适合各平台的公开关键词、URL 或原生 ID 执行真实查询
Then: 每个平台都有状态、候选数、耗时和失败证据
```

### AC-02

```text
Given: 搜索返回候选的平台
When: 检查标题、URL 域名和基本相关性
Then: 不仅以 HTTP 200 或空 failure 判断成功
```

### AC-03

```text
Given: 登录限制、缺少 API Key、上游拦截、解析漂移和真实无结果
When: 汇总审计
Then: 各状态被明确区分，并给出修复优先级
```

## Business Invariants

- 测试数据只写临时目录，不保存凭据、Cookie、下载资产或正式运行状态。
- 不使用后端 probe 冒充真实 OpenClaw Agent 用户流程。
- 本轮只读审计生产代码；计划与结果文档除外。

## Expected Change Surface

- Likely to change: 本 Task Spec 的状态和结果记录。
- Should not change: `skills/`、`mcp/education-resources/src/`、测试和业务文档。

## Validation Plan

- 枚举实际注册 Adapter。
- 对每个平台运行一个真实搜索 smoke；必要时以第二条查询确认可重复故障。
- 抽样校验成功候选的标题、URL 与查询相关性。
- 运行 `git diff --check` 确认只新增审计记录。

## 步骤

- [x] completed：枚举平台并准备与能力匹配的查询。
- [x] completed：执行真实联网搜索和候选质量抽查。
- [x] completed：复测失败项并区分登录、配置、网络与解析问题。
- [x] completed：形成分级清单、完成边界检查并归档计划。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| runtime enumeration | 17 dedicated + Generic | 当前实际注册面 | 动态上游可用性 |
| live platform smoke | 17 路（排除已单独验证的 baiduwenku） | 12 个专用平台公开搜索正常；4 个为登录/授权限制；Generic 失效 | 长期稳定性、登录后路径 |
| candidate quality sample | 检查首轮全部 32 个候选的标题和 URL | 返回内容与查询基本相关；发现 WeChat HTML 实体未清洗 | 完整召回质量、详情页长期有效性 |
| real Agent/user flow | 未执行 | | |

## 结果

- 正常：bilibili、smartedu、ximalaya、cctv、yixi、kepu、runoob、nlc、open163、annas-archive、wechat、shuge。首轮共返回 32 个候选，标题与查询基本相关。
- 受登录/授权限制，不判站点故障：douyin、zhihu、weibo、zjer。当前受控临时环境没有保存任何平台 Session；本地正式 Session 目录也没有已存记录。
- P1：Generic Web 当前失效。三条不同查询均为 0 候选；DuckDuckGo 和 Baidu 返回安全验证，Bing RSS 地址返回搜索首页 HTML。`resource_search(platform=generic)` 同时把底层 engine errors 表现成 0 failure，形成静默空结果。
- P2：Wechat 可搜索，但标题和 Sogou redirect URL 中保留 `&ldquo;`、`&amp;` 等 HTML 实体，属于结果清洗缺陷。
- 环境未配置 QIANFAN_API_KEY 或 SearXNG，无法验证这两个替代 Generic 路径。
- 本轮未修改产品代码；修复应另开定向任务，优先处理 Generic 的有效搜索源和错误透传，再处理 WeChat 实体清洗。
