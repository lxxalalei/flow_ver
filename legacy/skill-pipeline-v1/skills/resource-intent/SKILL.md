---
name: resource-intent
description: learning-resource-flow Stage 1 的持续需求理解与澄清能力。用于结合用户初始请求和后续回答，分析儿童成长或学习资料需求，识别会显著影响搜索的歧义，自然追问，并在需求足够明确后生成可供下游使用的 intent-spec/v1。
---

# resource-intent

## 职责

理解用户真正想为孩子寻找什么资料，并对搜索结果负责：需求不清时主动分析和追问，需求清楚后形成稳定、可验证的 Intent。

在当前 Stage 1 对话中持续维护同一份需求理解。初始请求建立语义，后续回答补充、确认或修正已有信息；短回答必须结合刚才的问题理解。澄清轮数不设上限，也不以填满字段为目标。

本 Skill 只负责需求语义：不选择平台、不生成完整查询、不执行搜索、不筛选候选。

## 事实与推理

按以下优先级使用证据：

1. 用户当前明确表达和确认。
2. 当前需求中较新的用户回答；明确修正可以覆盖较早表达。
3. 有充分语义依据的推断。
4. 不会明显改变需求的透明低风险默认。

保留未受新证据影响的既有结论，只更新相关主题、目标、场景、学习者信息或约束。将事实、推断和默认分别标记为 `explicit`、`inferred`、`defaulted`；未知信息直接省略，不编造值补齐结构。

## 需求模型

围绕会实际影响搜索、筛选或使用的内容理解需求：

- 孩子想理解、探索、练习、实践、表达或改善的核心主题。
- 学习目标、能力水平、年龄或年级等适用条件。
- 自主学习、家长辅导、课堂使用、打印练习、路上听等场景。
- 资料大类、具体内容形态和真实文件格式。
- 语言、版本、费用、来源、质量和排除项等约束。

保持约束强度：`must` 是不可妥协条件，`prefer` 影响排序但可以妥协，`exclude` 是明确排除。不要把偏好升级为硬条件，也不要弱化用户明确底线。

具体槽位、证据和推断边界见 `references/semantic-rules.md`。涉及资料形态时再读取 `references/resource-form-rules.md`；主题归一化确实不确定时读取 `references/domain-vocabulary.md`。

## 澄清责任

先判断：如果现在不问，Search 是否仍能形成方向明确、可筛选且不会明显偏离用户诉求的计划？

- 能：保留未知值或使用有依据的低风险推断，继续完成 Intent。
- 不能：找出影响最大的歧义，只提出一个自然、容易回答的问题。

重点澄清核心主题、彼此独立的目标、明显分叉的学习路线、事实冲突、硬约束冲突，以及会改变适用性或安全性的学习者条件。不要为了平台、数量、普通格式偏好或可由 Search 覆盖的差异追问。

组织问题或面对宽泛、冲突需求时读取 `references/clarification-rules.md`。用户回答后继续分析同一需求；如果仍存在关键歧义，可以继续追问。澄清期间只形成对话问题，不生成正式 Intent 文件。

## Ready 判断

满足以下条件时结束澄清：

- 核心需求和不可妥协约束已经明确。
- 剩余未知信息不会让 Search 走向明显不同的路线。
- 下游能够制定有效搜索计划，并判断候选是否符合用户目标。
- 所有 explicit 和 inferred 结论都有用户原话证据；默认值透明且低风险。

不要因为“已经能勉强搜索”而忽略关键路线歧义，也不要在需求已经足够明确后继续收集可选信息。

## 正式输出

Ready 后一次性生成 `{session_dir}/stage1_intent.json`，遵循 `schemas/output.schema.json` 的 `intent-spec/v1`，并使用 `scripts/validate_output.py` 校验。新生产流程的正式文件状态为 `ready`；Schema 对旧 `needs_clarification` 文件的兼容不代表澄清期间需要生成该文件。

正式输出必须：

- 忠实保留 `raw_request` 和整个 Stage 1 中有效的用户证据。
- 只写有值且会影响下游的槽位。
- 保持 `explicit`、`inferred`、`defaulted` 的区别。
- 提供 `canonical_terms`、`synonyms`、`related_terms` 等概念材料，但不包含平台、`site:`、完整查询句或查询预算。
- 对使用的默认值在 `assumptions` 中作简短说明。

取消或无法继续获得真正必要的信息时，将控制权交回 Flow，不伪造 `ready` 输出。

## 按需资源

- `references/clarification-rules.md`：需求宽泛、路线分叉、信息冲突或准备提问时读取。
- `references/semantic-rules.md`：生成正式 Intent、处理复杂推断或检查槽位语义时读取。
- `references/resource-form-rules.md`：用户涉及视频、音频、试卷、课件、PDF 等资料形态或格式时读取。
- `references/domain-vocabulary.md`：主题归一化、同义词或领域边界确实不确定时读取。
- `examples/golden-cases.json`、`examples/clarification-matrix-cases.json`：修改 Skill 或回归验收时读取，不用于正常对话。
