---
name: resource-platforms
description: 学习资源平台搜索执行层。读取 resource-search 生成的多平台搜索计划，并行调用可用平台及百度、Bing 通用搜索接口，归一化原始结果并写入 Stage 3。用于执行搜索，不负责理解需求、生成关键词、筛选评分或下载资源。
---

# resource-platforms

## 铁律（不可违反）

**Iterate until the output is complete and well-formed. Before declaring done, run a self-check — if any part feels half-baked, keep going.**

输出搜索结果前，自检这份搜索结果真的达标了吗。

## 任务

把 `{session_dir}/stage2_search_plan.json` 交给统一执行器，生成 `{session_dir}/stage3_search_results.json`。

本 Skill 只负责：

- 根据私有搜索注册表加载平台 adapter。
- 并行执行不同平台的任务。
- 在同一平台内按顺序执行多条查询，避免并发触发限流。
- 让 generic adapter 同时搜索百度和 Bing。
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

执行前由模型检查当前计划涉及的平台，并按需读取对应平台文档。凭据约定保存在当前 Agent Skills 根目录的 `.learning-resource-flow/credentials.json` 及其相邻私有文件中；该文件不是阶段契约，也不要求脚本自动管理。

凭据文件不存在时，由模型按 `config/credentials.example.json` 创建；缺少必需凭据时，询问用户并在授权后帮助写入本地文件。运行统一执行器时，由模型把当前任务需要的凭据注入环境变量。不要为未计划的平台加载凭据。

### 并行规则

1. 不同平台使用独立 worker 并行执行，并由注册表的 `max_concurrency` 限制总并发。
2. 同一平台的 `searches[]` 默认串行。
3. generic 内部并行请求百度和 Bing，再按规范化 URL 合并。
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

缺少必需认证或登录态失效时，返回 `AUTH_REQUIRED` 或对应认证错误。模型读取对应平台文档，说明具体缺少什么，并询问是否需要协助配置；配置完成后重新调用统一执行器。只报告配置状态，不把凭据写入搜索计划、结果或日志。

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
- 执行器尝试每个计划任务；Stage 3 只持久化有效资源和真实错误，零结果且无错误的查询不增加占位记录。
- 输出不包含搜索计划改写、跨平台筛选或下载结果。
- 只向 Flow 返回 `_summary` 和输出路径。

## 按需读取

- `config/search-registry.json`：平台状态、adapter、认证方式和超时。
- `config/credentials.example.json`：模型创建本地凭据约定时使用的轻量示例，不是需要脚本校验的数据契约。
- `references/search-interface.md`：adapter 与 Stage 3 的搜索数据说明。
- `references/search-errors.md`：搜索错误及重试边界。
- `references/platforms/{platform}.md`：正常批量搜索不预加载。某个平台认证失败、连续空结果、接口或解析异常时，读取对应文件后诊断；测试、修改或新增该平台搜索实现前也必须读取。不要为一个平台的问题加载其他平台文档。
