# 开发路线

当前机器事实见 [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)，执行记录见 `.agent/plans/`。

## 产品目标

用户通过自然语言完成完整教育资源闭环：

```text
表达需求 -> 澄清 -> 搜索 -> 候选审查 -> Inspect -> 展示 -> 选择 -> 获取计划 -> 确认 -> 下载 -> 归档
```

成功 = 结果符合目标、关键事实可解释、用户控制副作用、资源能正确获取并恢复。

## 架构约束

### 1. 语义判断与事实状态分开

MCP 保存事实（ResultSet、Resolution、Plan、Job、Asset）。Skill 私有完成 SemanticReview / Gap / StopDecision。

### 2. 获取链保持简单

```text
Resolution -> Plan -> 用户确认 -> Job -> exact Provider -> Outcome -> Asset -> Archive
```

Provider 能力用轻量配置和运行时检查表达，不引入多层自证状态。

### 3. 精确 Provider，不 silent fallback

Plan 指定哪个 Provider，Start 就执行哪个。失败返回真实失败，需要改变路线时重新 Prepare。

### 4. Representation 是核心业务事实

区分 `primary_resource` / `representation` / `landing_page` / `metadata`。

### 5. 保留必要安全边界

prepare → 确认 → start、SSRF / 重定向保护、受控任务目录、取消 / 超时、MIME 检查、登录 / 付费墙边界。

## 路线

```text
0028 真实平台 E2E
  -> 0029 benchmark 与 release gate
  -> 平台扩展 / Library & Viewer
  -> 部署
```

### 0028 Real Platform E2E

逐平台验证完整用户闭环：Search → Inspect → Select → Confirm → Acquire → Archive → Recover。

覆盖：文章网页、文件型文档、视频、音频、课程、混合来源、失败恢复。

不能用 fixture / 单元测试替代真实闭环。

### 0029 Benchmark & Release Gate

度量业务行为：relevance、是否过早 Present、Gap 准确性、Provider route 是否真实、结果一致性。

P0 门禁：未确认产生副作用、错资源被获取、silent fallback、伪造成功、归档非 ready Asset、绕过认证。

### 平台扩展

按用户价值恢复 / 新增平台。核心是把 Search 命中解析成真实 Representation 并通过明确 Provider 获取。

### Library & Viewer

资料库浏览、分类筛选、预览、Bundle 展示、去重、再搜索入口。

### 部署

远程 Streamable HTTP、多租户、Secret 管理、配额、可观测性。
