---
name: resource-platforms
description: 成长资料平台搜索执行层。读取 resource-search 生成的多平台搜索计划，并行调用可用平台及通用搜索引擎，归一化原始结果并写入 Stage 3。用于执行搜索，不负责理解需求、生成关键词、筛选评分或下载资源。
---

# resource-platforms

## 执行要求

输出搜索结果前，先自检结果是否完整、结构是否合规；明显半成品时继续修正。

## 任务

把 `{session_dir}/stage2_search_plan.json` 交给统一执行器，生成 `{session_dir}/stage3_search_results.json`。

本 Skill 只负责：

- 根据私有搜索注册表加载平台 adapter。
- 并行执行不同平台的任务。
- 在同一平台内按顺序执行多条查询，避免并发触发限流。
- 让 generic adapter 按计划中的 `engines` 搜索千帆、DuckDuckGo、Bing 或百度；默认计划至少包含 `duckduckgo`。
- 处理平台超时、失败和部分成功。
- 归一化平台原始字段。
- 合并同平台、同 `resource_id` 的完全重复响应。

不要重新读取 Intent 生成关键词，不做跨平台相似去重、业务过滤、最终质量评分、候选展示或下载。

## 执行

运行：

```bash
python3 resource-platforms/scripts/run_search_plan.py \
  {session_dir}/stage2_search_plan.json \
  {session_dir}/stage3_search_results.json
```

执行器读取 `config/search-registry.json`。只有 `status=available` 且 adapter 可加载的平台才能执行；planned 或不可用平台写入结构化错误，不得伪造成零结果。

执行所需凭据由 Flow 在调用前注入环境变量。本 Skill 不读取或写入 `credentials.json`，不向用户索取凭据，也不处理凭据配置；只执行计划并把认证结果返回 Flow。

### 并行规则

1. 不同平台使用独立 worker 并行执行，并由注册表的 `max_concurrency` 限制总并发。
2. 同一平台的 `searches[]` 默认串行。
3. generic 内部按计划请求千帆、DuckDuckGo、Bing 或百度，再按规范化 URL 合并；千帆凭据由 Flow 对实际选中的 `qianfan` 引擎预检，本 Skill 不自行提醒用户。
4. 单个平台失败不得取消其他 worker。
5. 所有 worker 完成或超时后一次性原子写入 Stage 3。

### Adapter 规则

每个 available 平台必须由注册表指向一个 `adapter.py`，模块导出 `ADAPTER`，并实现：

```python
search(query: str, max_results: int, params: dict) -> {
    "results": [...],
    "error": None
}
```

adapter 负责把统一参数转换为平台真实调用，并把平台响应转换为公共搜索资源。认证只能从运行环境、配置或浏览器会话读取，不能写入搜索计划、结果或日志。

Cookie、Token、浏览器状态路径和 CDP 地址只使用注册表及平台文档声明的环境变量。不得把认证信息放进 `searches[].params` 或命令行中的明文参数。缺少依赖或必需认证时，必须在联网前返回结构化错误。

缺少必需认证或登录态失效时，返回 `AUTH_REQUIRED` 或对应认证错误给 Flow，不在本 Skill 中提醒用户、写入凭据或发起配置交互。认证信息不得写入搜索计划、结果或日志。

## 结果边界

每条有效资源至少提供：

- `resource_id`
- `platform`
- `title`
- `source_url`

类型、简介、作者、时长、费用、语言、封面、下载可行性和平台原生信号只在平台能够确定时输出。未知字段省略，不编造。

平台热度、认证和原生评分只能放入 `platform_signals`，不得输出 Selector 的最终 `quality_score`。

失败调用写入 `data.errors`，包括平台、查询、错误码、说明和是否可重试。只要其他平台有有效结果，Stage 3 仍然可以完成。

## 完成检查

- `_summary.resource_count` 等于 `data.resources` 数量。
- `_summary.failed_platforms` 只包含完全没有成功结果且存在错误的平台。
- `_summary.empty_platforms` 包含正常完成但没有返回资源、且没有错误的平台。
- 执行器尝试每个计划任务；Stage 3 只持久化有效资源和真实错误，零结果且无错误的查询不增加占位记录。
- 输出不包含搜索计划改写、跨平台筛选或下载结果。
- 只向 Flow 返回 `_summary` 和输出路径。

## 按需读取

- `config/search-registry.json`：平台状态、adapter、认证方式和超时。
- `references/search-interface.md`：adapter 与 Stage 3 的搜索数据说明。
- `references/search-errors.md`：搜索错误及重试边界。
- `references/platforms/{platform}.md`：正常批量搜索不预加载。某个平台认证失败、连续空结果、接口或解析异常时，读取对应文件后诊断；测试、修改或新增该平台搜索实现前也必须读取。不要为一个平台的问题加载其他平台文档。
