# Task Spec 0064：微信公众号搜索 HTML 实体清洗

- 状态：completed
- 创建日期：2026-08-20
- 完成日期：2026-08-20
- 范围：微信公众号搜索适配器及定向测试

## Goal（必填）

用户/系统能够：从微信公众号搜索获得已反解 HTML 实体的标题、摘要、公众号名和有效 Sogou 跳转 URL。

## Non-goals（必填）

- 不修改搜狗搜索策略、Cookie/Login 语义或反爬处理。
- 不解析跳转后的微信文章正文，不新增 Inspect 或 Download 能力。
- 不修改其他平台适配器。

## Acceptance Criteria（必填）

### AC-01

```text
Given: 搜狗结果包含 &ldquo;、&amp; 等 HTML 实体
When: WechatSearchAdapter 解析候选
Then: 文本字段是正常 Unicode 文本，URL 查询分隔符为 & 而不是字面量 &amp;
```

### AC-02

```text
Given: 当前公开搜狗微信搜索页
When: 执行真实联网搜索
Then: 返回候选，且标题和 URL 不残留 HTML 实体
```

## Business Invariants

- 搜索仍只发现候选，不宣称具备 Inspect/Download。
- 反爬页仍返回显式 AUTH_REQUIRED。
- limit 语义保持不变。

## Expected Change Surface

- Likely to change: `adapters/wechat.py`、直接相关测试。
- Should not change: 其他 Adapter、公共 Tool Schema、能力文档。

## Validation Plan

- 定向单元测试覆盖文本和 URL 实体反解、limit、AUTH_REQUIRED 不变。
- 搜索相关测试。
- 一次真实联网 `ResourceService.search(platform=wechat)`。
- Python 编译和 `git diff --check`。

## 步骤

- [x] completed：实现文本与 URL 的最小实体清洗。
- [x] completed：补充定向测试并运行搜索回归。
- [x] completed：执行真实联网验证、复核边界并归档计划。

## Milestone checkpoint

```text
Original goal still unchanged?: 是
Non-goals still respected?: 是
Business invariants still true?: 是
New abstraction introduced?: 否
New source of truth introduced?: 否
Fallback added?: 否
Data truncation added?: 否
Unrelated files changed?: 否；先前工作区修改均未被本任务改写
Actual user flow affected?: WeChat 搜索候选展示和跳转 URL
Actual user flow validated?: 后端真实联网 ResourceService 已验证；未执行真实 OpenClaw Agent
Scope drift detected?: 否
```

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted unit | 20 tests passed | 文本/URL 实体反解、limit、AUTH_REQUIRED 及搜索回归 | 上游长期稳定性 |
| live search | 3 candidates、0 failures、0 entity residue | 当前真实搜狗微信结果已正确清洗 | 长期上游稳定性、跳转后的文章可访问性 |
| real Agent/user flow | 未执行 | | |

## 结果

- `html.unescape` 在标签剥离前处理标题、摘要和公众号名；Sogou href 在 URL 拼接前单独反解。
- 没有修改请求、Cookie、反爬、limit 或公共 Tool 契约。
- Level 1 验证完成；未执行真实 OpenClaw Agent 或登录态流程。
