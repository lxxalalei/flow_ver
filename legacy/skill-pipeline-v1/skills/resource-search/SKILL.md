---
name: resource-search
description: learning-resource-flow 内部 Stage 2 搜索规划 Skill。仅当 Flow 已创建会话，且 `{session_dir}/stage1_intent.json` 存在、校验通过并处于 ready 状态时调用；将已确认需求转化为多平台搜索计划，生成查询词和真实接口参数。不要直接响应普通终端用户的完整资源搜索需求，也不执行搜索、筛选或下载。
---

# resource-search

## 目标

读取 `{session_dir}/stage1_intent.json`，为下一阶段生成 `{session_dir}/stage2_search_plan.json`。

这是 `learning-resource-flow` 的内部 Stage 2，不是独立用户入口。缺少已校验且 `data.status=ready` 的 Stage 1 文件时，停止并把控制权交还 Flow，不直接接管用户需求。

为孩子及其家长搜集能够帮助理解世界、理解自己、发展能力、建立习惯、获得体验或完成学习目标的成长资料。先判断资源由孩子直接使用，还是由家长理解、选择或组织后陪伴孩子使用；搜索方向和平台选择应与这个角色一致。

把 Search 当作语义规划器，而不是字段映射器：理解主题、儿童如何学习以及不同媒介能提供什么帮助，再设计搜索策略。允许依据主题形成新的召回角度，但不要把探索角度反写成用户已经提出的事实或限制。

输入为 `resource-intent` 已校验的完整 `intent-spec/v1`，不把它转换成另一种 Search 输入结构：

- 输入文件必须包含 `_meta`、`_summary` 和 `data`，且 `data.status=ready`。
- 本 Skill 拥有 `search-plan/v1` 的输出格式，见 `schemas/output.schema.json`。
- 平台是否可执行、认证条件和接口参数以 `config/platform-catalog.json` 为准。

Intent 尚未就绪时停止，不重新澄清或改写上游需求。

## 规划流程

### 1. 形成搜索意图

综合读取 Intent 中的主题、对象、目的、场景、明确约束和搜索概念，判断这次搜索需要覆盖哪些成长方向和资料形态。

从孩子成长和学习的实际使用方式思考：需要听、看、读、练、跟做、讨论、创作、观察、实践、查方法，还是由家长选择和准备材料。适龄性会影响内容表达和媒介选择，但不要机械地给所有查询添加"儿童"、年龄或年级。

区分两类信息：

- 用户事实：用户明确表达或 Intent 已可靠推断的信息，用于约束搜索。
- 召回假设：模型根据主题提出的资源形态、学习方式、内容切面或来源方向，用于扩大搜索，不视为用户限制。

不要逐字段机械拼接关键词。某个维度是否进入查询，取决于它能否提高当前查询的相关性或带来有价值的新结果。

**互补形态探索（默认执行）**：读取 Intent 的 `resource_types`、`format_preferences`、学习目标和使用场景。没有限定资源形态时，默认选择两个能够产生不同学习体验的方向；宽泛或 exhaustive 需求通常选择三个。用户明确限定形态、任务足够窄，或单一形态已能完整满足目标时，可以收敛，不为满足数量加入无关课程、文档或练习。详细规则见 `references/query-strategy.md` 的“互补形态覆盖”章节。

### 2. 分配平台任务

读取 `references/routing-rules.md`，由模型结合当前需求判断各平台可能提供的独特价值。该文档提供平台内容生态和判断维度，不是主题到平台的固定映射表。

为每个平台分配清晰的搜索职责：主力平台覆盖最重要的学习方式或资源形态，补充平台提供不同的媒介、来源或内容切面。平台组合随需求变化，不使用固定套餐，也不要求平均搜索所有平台。

形成平台方案后读取 `config/platform-catalog.json`，排除当前不可执行的平台，并确认认证条件。Catalog 不替代语义判断，也不根据固定字段自动选平台。

默认加入一个 `generic` 任务，用于发现未接入站点、长尾网页和具体文件；每条 generic 搜索的 `params.engines` 必须包含 `duckduckgo`。中文网页或白名单查询默认使用无凭据引擎 `["duckduckgo", "bing"]`。只有用户明确要求使用千帆，或 Flow、执行环境明确表明千帆已配置并启用时，才把 `qianfan` 加入引擎列表；不得为了普通搜索询问 API Key。其他引擎仅在明确需要且 catalog 显示可执行时加入。当用户明确要求只搜索某个原生平台，或明确排除通用网页搜索时，不生成 generic 任务。用户只限定某个网站时，仍可使用 generic，但所有查询必须以该网站的 `site:` 范围约束。

### 3. 生成差异化查询

先确定平台要找的内容，再写符合该平台搜索习惯的自然查询。查询之间通过不同的知识切面、学习行为、资源形态或使用场景扩大召回，而不是只替换同义词或附加固定后缀。

需要构造查询时读取 `references/query-strategy.md`。只有生成 `site:` 查询时读取 `references/site-whitelist.md`。

通常为主力平台生成 2-4 条互补查询，为补充平台生成 1-3 条；根据需求宽窄动态调整，不为达到数量而生成低价值查询。

### 4. 使用真实接口参数

每个 `searches[]` 元素对应下一阶段的一次搜索调用：

- `query`：发送给平台的搜索词。
- `max_results`：该次调用的返回上限。
- `params`：只填写 catalog 中该平台声明并且当前查询确实需要的参数。

不得虚构筛选参数。认证信息由 Platform 管理，不进入搜索计划。

### 5. 写入计划

```json
{
  "_meta": {
    "schema_version": "search-plan/v1",
    "session_id": "继承上游",
    "created_at": "ISO 8601"
  },
  "data": {
    "search_tasks": [
      {
        "platform": "平台标识",
        "priority": "P0",
        "searches": [
          {
            "query": "面向该平台的自然搜索词",
            "max_results": 15,
            "params": {}
          }
        ]
      }
    ]
  }
}
```

每个平台只创建一个任务。平台分工直接体现在查询差异中，不输出没有执行消费者的解释字段。

## 完成检查

- 平台组合能够覆盖当前搜索意图，并且各平台有不同贡献。
- 孩子直接使用的资源与家长辅助内容没有混为一谈。
- 查询保留主题核心，扩展角度与需求相关。
- 用户约束得到体现，召回假设没有被写成强制条件。
- 所有平台和 `params` 均由 catalog 支持。
- 最多包含一个 `generic` 任务；未包含 generic 时，必须能从 Intent 的明确表述确认用户限定只搜索原生平台或排除通用网页搜索。若包含 generic，每条搜索的 `params.engines` 都包含 `duckduckgo`；中文 generic 未明确启用其他引擎时使用 `["duckduckgo", "bing"]`，不因普通搜索请求千帆凭据。
- **互补形态探索**：未限定形态时，默认覆盖两个与主题相关且学习体验不同的方向；宽泛或 exhaustive 需求通常覆盖三个。明确限定形态、窄任务或单一形态足以满足目标时允许收敛。只在文件材料确有帮助时使用 `filetype:` 查询。

运行：

```bash
python3 resource-search/scripts/validate_output.py \
  {session_dir}/stage2_search_plan.json \
  --intent {session_dir}/stage1_intent.json
```

验证只检查计划能否执行，不替代语义判断。完成后向 Flow 返回输出路径。
