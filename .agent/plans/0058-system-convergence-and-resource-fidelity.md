# 0058 — 系统收敛、能力接通与资源保真

- 状态：in_progress
- 创建日期：2026-08-18
- 更新日期：2026-08-19
- 完成日期：未完成
- 范围：`mcp/education-resources/`、Host Web URL Import、Generic Web 保存、active 文档、真实 OpenClaw 验收

## Objective

在不恢复旧 Flow / ResultSet / Selection / Plan / Asset / authority / digest 架构的前提下，把已经正确的 **Agent / Skill 语义层 + MCP 能力层** 真正接通并收敛：

1. Session 保持独立代码职责，但不再维持独立 MCP 进程；
2. Host Web 找到已接入平台 URL 后回到对应 Inspector / Downloader；
3. Generic Web 先保留原始 HTML，再用成熟库生成可读表示；
4. active 文档只描述当前真实架构；
5. 最终用真实 OpenClaw 用户链证明这些改动解决实际产品问题。

## Non-goals

- 不重写 `learning-resource-flow`；当前 Skill 先冻结。
- 不新增 Session Service / Auth Gateway / Credential Authority / Login Transaction。
- 不新增 URL Resolver Framework / Provider Discovery Framework / 第二套 Capability Registry。
- 不恢复 `prepare -> confirm -> start`、AssetBundle、eligibility、authority/binding/digest 链。
- 不为旧独立 session-manager 建长期 compatibility layer。
- 不自己重造 WebFetch、浏览器或网页克隆器。
- 当前不接 Monolith / SingleFile / ArchiveBox。
- 不建立多 extractor fallback。
- 不在本计划新增平台 Adapter。

## Business invariants

1. Agent / Skill 负责需求、搜索任务、来源职责、候选判断、Gap、停止、用户选择和归档分类。
2. MCP 只负责真实平台能力、IO、副作用和必要运行状态。
3. `resource_id` 是进程内临时句柄；稳定身份仍是 URL / 平台原生 ID。
4. `job_id` 只用于真实 Download / Batch 长任务。
5. 用户已明确选中对象并要求下载时直接执行，不制造二次确认。
6. Session Tool 不是 Search / Download 的固定前置步骤；只有真实 `AUTH_REQUIRED` 或用户主动管理登录态时使用。
7. SmartEdu 公共 Search / Catalog 始终匿名。
8. `annas-archive` 当前继续走匿名 Libgen 镜像，不引入 Anna 会员登录。
9. exact Provider 失败后返回真实失败，不切换不等价 Provider。
10. Batch 默认枚举到来源真实结束；分页不变成采集上限。
11. 网页正文抽取不能改变已经取得的 source snapshot。

## 已实施架构

```text
Main Agent / learning-resource-flow
        │
        ├── Host Web Search
        │       ↓ selected URL
        │   resource_import_url
        │
        ↓
education-resources MCP
  ├── 10 Resource Tools
  └── 4 Session Tools
          ↓
      one SessionStore
```

Standalone `mcp/session-manager/` 和 `session_bridge.py` 已删除。

## Decisions

### Decision 001 — Session 模块独立，MCP 进程合并

把 SessionStore 与四个 Session Tool 合入 `education-resources`。当前只有一个消费者，独立进程没有兑现跨 MCP 复用/独立部署价值，却引入 shared data dir、bridge 和双 Store 一致性问题。

保留：平台筛选、原子写入、Windows DPAPI、过期状态、必要 probe。

删除：operation ledger、idempotency fingerprint/revision、standalone/local 双路径。

迁移：不维持双读兼容；旧 standalone 登录态可能需要重新捕获一次。

### Decision 002 — Host Web Import 使用薄 URL 识别

`resource_import_url()` 仅根据明确 host/path 恢复已有专门平台身份：

```text
Bilibili /video/... -> bilibili
Zhihu               -> zhihu
basic.smartedu.cn   -> smartedu
unknown             -> generic
```

不建立 Resolver Framework 或第二 Registry。

### Decision 003 — Web 不做 benchmark-first，直接采用 Trafilatura

原计划准备先建设完整 extractor benchmark。当前改为：

```text
BoundedWebFetcher
  -> source.html
  -> Trafilatura
       -> index.html
       -> content.md
       -> metadata.json
```

目标是停止继续扩展自研正文抽取器，并把 source snapshot 与可读抽取分开。当前不接 Monolith；只有未来真实用户明确要求“离线打开仍尽量完整还原 CSS/图片”时再单独评估。

## Acceptance criteria

### AC-01 — Session 部署边界

- [x] 只有一个 active `education-resources` MCP。
- [x] 同一个 server 暴露 10 Resource Tool + 4 Session Tool。
- [x] 资源 Adapter 和 Session Tool 使用同一 SessionStore。
- [x] 删除 `mcp/session-manager/` 和 `session_bridge.py`。
- [x] 不保留 standalone/local 双路径。

### AC-02 — SessionStore 简化

- [x] 删除 operation ledger / idempotency fingerprint/revision。
- [x] 浏览器宽捕获先按平台规则筛选，再保存 canonical session。
- [x] 保留原子写入和 Windows DPAPI。
- [x] 不再对完整 capture 做先于平台筛选的总字节门禁。
- [ ] 真实 Windows 捕获/保存仍需 OpenClaw 复测。

### AC-03 — Host Web URL → 专门平台

- [x] Import 不再无条件 `platform="generic"`。
- [x] 已加入 Bilibili / Zhihu / SmartEdu 明确 URL 路由。
- [x] 未知 URL 保持 `generic`。
- [x] 没有新增 Registry/Resolver framework。
- [ ] 真实 Host Web → Import → Download 仍需 OpenClaw 复测。

### AC-04 — Web Resource

- [x] `source.html` 保存 fetch 成功取得的原始 HTML。
- [x] Trafilatura 生成 readable HTML / Markdown。
- [x] 抽取失败时 source snapshot 保留并报告 partial/source_only。
- [x] 删除生产路径自研 `web_blocks.py`。
- [x] 不接 Monolith / SingleFile / ArchiveBox。
- [x] 网络响应超出真实 fetch 上限时显式失败，不静默裁剪。
- [ ] 真实网页人工检查仍需本机复测。

### AC-05 — active 文档

- [x] `CURRENT_ARCHITECTURE.md` 改为一个 MCP。
- [x] `TOOLS.md` 改为 14 Tool 和嵌入 Session。
- [x] 根 `README.md` / MCP README / `DEVELOPMENT_PLAN.md` 已同步。
- [x] `AGENTS.md` 不再把 standalone session-manager 当 active 组件。
- [x] 0029 / 0041 已从 active plans 移入 archive。

### AC-06 — 真实 OpenClaw 闭环

仍需用户本机实际完成：

1. Host Web 找到已接入平台 URL → Import → 专门 Inspector/Downloader → 文件；
2. SmartEdu 已保存 session 环境下公共 Search 仍匿名；
3. Anna/Libgen 不触发登录；
4. 一个真实 `AUTH_REQUIRED` 平台 → 用户浏览器登录/捕获 → `resource_session_save` → 重试；
5. 一个 Generic Web 页面得到 `source.html + index.html + content.md` 并人工检查；
6. 一个此前易 compaction 的 Douyin 长任务完整完成或暴露具体剩余失败。

后端测试不能替代以上六项。

## Milestones

- [x] M0 — 冻结目标与边界
- [x] M1 — Session Tool 合入 education-resources
- [x] M2 — SessionStore 净迁移与瘦身
- [x] M3 — Host Web Import 平台身份恢复
- [x] M4 — Trafilatura 直接接入，取消 benchmark-first
- [x] M5 — `source.html` 与可读表示分离
- [x] M6 — active 文档/计划收敛
- [ ] in_progress：M7 — 静态/子系统验证 + 真实 OpenClaw 用户验收

## Validation

### 已完成的事实核对

- 已复核 Trafilatura 官方 `extract()` API，确认支持 HTML/Markdown 输出和 `include_tables/include_images/include_links` 参数。
- 已按当前树删除 standalone session-manager、bridge 和旧生产 `web_blocks.py`。
- 已增加针对 Session 先筛选、Import 平台路由、Web source snapshot 的 focused regression tests。

### 尚未完成

当前执行环境无法直接安装/运行该仓库的 Python 依赖，也无法连接用户 Windows OpenClaw，因此：

- focused pytest 尚未实际执行；
- MCP stdio probe 尚未实际执行；
- 真实 Windows DPAPI/login capture 尚未实际执行；
- 真实平台/OpenClaw E2E 尚未实际执行。

在这些验证实际完成前，不把本计划标记为 completed。

## Remaining risks

1. Trafilatura 不同输出格式对链接/图片结构的可见程度可能不同；硬保证是原始 `source.html` 保留，而不是宣称每个衍生格式必然保留所有 DOM 语义。
2. 旧 standalone session 加密记录不做双读，升级后可能需要一次重新登录/捕获。
3. 当前 URL 平台识别故意只覆盖有明确证据的代表性 URL；后续只能根据真实遗漏逐个补，不扩成猜测型通用识别器。
4. Python focused tests 尚未实际运行，必须在可安装依赖的环境补上。
