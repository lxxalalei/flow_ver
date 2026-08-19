# Task Spec 0054：抖音 creator_sec_uid 暴露与 browse_creator 自描述

- 状态：in_progress
- 创建日期：2026-08-15
- 完成日期：未完成
- 分支：`codex/growth-resource-taxonomy-rework`
- 来源：0028 用户真实测试反馈（2026-08-15 19:21–19:34 会话 126ebec3）

## 事故记录

用户在 OpenClaw 中要求"把停云小阁所有视频详情拉成 JSON 清单"。`resource_browse_creator`
需要抖音 `sec_user_id`（`MS4wLjAB...`），但搜索候选与 inspect 元数据都不携带该字段，
工具自描述也未说明来源。Agent 为找到答案读取了 8 个大文件（contracts schema 与
adapter/service 源码，约 20 万字符 ≈ 5 万 tokens），把会话上下文推到 73.7K input，
触发 compaction——用户侧表现为"回答中途断开"。

同会话另两个事实（非本计划范围）：抖音对连续多关键词搜索限流（返回空但不报错）；
模型上下文声明缺失导致压缩阈值偏保守（已在 openclaw.json 为 ds 模型声明
`contextWindow: 1000000` 缓解）。

## Goal（必填）

用户/系统能够：从 `resource_search`（douyin）候选 metadata 与 `resource_inspect`
（douyin）resolved metadata 直接读到 `creator_sec_uid`，随即以它调用
`resource_browse_creator`；Agent 无需读取仓库源码或契约文件来发现 creator_id 的
来源与格式。

## Non-goals（必填）

- 不实现昵称→sec_uid 的服务端解析（抖音无稳定公开接口，不猜）。
- 不改 `browse_creator` 的输入契约字段名或鉴权/幂等语义。
- 不为其他平台顺带新增 creator 字段；其他平台 adapter 有原生句柄时再按同一模式补。
- 不处理抖音搜索限流（服务端空结果），那是平台风控行为，另行记录。

## Acceptance Criteria（必填）

### AC-01 搜索候选携带 creator_sec_uid

```text
Given: douyin 搜索响应的 aweme_info.author 含 sec_uid
When: resource_search
Then: 候选 metadata.creator_sec_uid == 原值；metadata.author（昵称）不变。
```

### AC-02 inspect 元数据携带 creator_sec_uid

```text
Given: 详情接口 aweme_detail.author 含 sec_uid
When: resource_inspect
Then: resolved.metadata.creator_sec_uid == 原值。
      author 缺失 sec_uid 时字段缺省，inspect 不失败。
```

### AC-03 工具自描述写明来源

```text
Given: resource_browse_creator 的 docstring / input schema / tool-catalog
Then: 明确 creator_id 是平台原生句柄（douyin sec_uid 或 /user/ 完整 URL），
      来源是搜索/inspect 候选 metadata 的 creator_sec_uid，不得按昵称猜。
```

### AC-04 存量行为不回退

```text
When: 运行 douyin 相关聚焦测试（platform_adapters / douyin_inspect）
Then: 既有断言不因新增字段失败；缺省路径（无 sec_uid）无 creator_sec_uid 键。
```

## 设计要点

1. `adapters/base.py make_resource` 增加 `creator_sec_uid: str | None` 参数，
   真值时写入 `metadata.creator_sec_uid`（元数据为自由字段，不破坏既有 schema）。
2. `adapters/douyin.py _normalize_item` 从 `aweme_info.author.sec_uid` 提取并传入。
3. `adapters/inspect_douyin.py` 从 `aweme_detail.author.sec_uid` 提取写入
   resolved metadata；缺失时省略。
4. `server.py resource_browse_creator` docstring、
   `contracts/schemas/tools/resource_browse_creator.schema.json` 的 creator_id
   description、`contracts/tool-catalog.json` 描述三处同步写明来源。

## Validation checkpoint

已完成（2026-08-15，Windows 本机）：

- 聚焦测试：`test_platform_adapters.py` + `test_douyin_inspect.py` 37 passed
  （含新增 creator_sec_uid 断言与缺省容错）；`test_browse_creator_contract.py`
  + `test_contract_outputs.py` + `test_platform_inspectors_catalog.py`
  24 passed + 558 subtests。
- 契约 JSON（schema description、tool-catalog）改写后解析有效，契约测试不回退。

待完成：

- ~~同步部署 + doctor~~ 已完成（2026-08-15）：sync 全绿、gateway 重启、
  `education-resources --probe` ok。
- ~~真实链路验证~~ 已完成（2026-08-15）：真实视频 inspect 返回
  `metadata.creator_sec_uid = MS4wLjABAAAA0JOY…`（creator=停云小阁）；以该值调用
  `search_creator`（browse_creator 底层）返回该账号 5 条真实视频。
  期间观察到一次详情接口瞬时降级（无 sec_uid），缺省容错路径按设计工作。
  注：同关键词 `resource_search` 仍被抖音限流（返回空），AC-01 的 live 证据
  由单元测试（真实响应形状 fixture）覆盖。
- 用户复测后归档。

## Completion criteria

- AC-01~AC-04 有实现与测试证据；
- 同步部署后 `openclaw mcp doctor education-resources --probe` ok；
- 用户在 OpenClaw 中以新链路完成一次"搜索 → 拿 creator_sec_uid → browse_creator"
  或等价验证后，本计划方可归档。
