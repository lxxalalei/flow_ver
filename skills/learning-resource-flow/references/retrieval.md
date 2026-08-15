# Retrieval Guidance

多轮检索围绕用户目标自然推进，不维护 ResultSet/Presentation 状态机。

## 1. 每轮只回答四件事

```text
用户真正需要什么
  -> 这一轮最值得搜什么
  -> 真实结果是否有用
  -> 还缺什么，是否存在明显不同的补搜路线
```

继续搜索前必须能具体回答“缺什么”和“下一条路线为什么能补上”。如果只能说“可能还有更好”或“还有平台没搜”，就停止机械扩散。

## 2. 搜索角度不是关键词变体

`火山科普 / 火山知识 / 儿童火山知识` 仍是同一搜索空间。

“喷发原理理解”“真实喷发过程观察”“可打印实验单”才是不同价值方向。

窄任务一个方向即可；较宽任务优先 1–3 个互补方向。

## 3. 调用 Search

```text
resource_search(search_tasks=[...], limit=...)
```

每次 Search 都是一次独立真实搜索。补搜时重新组织有意义的 `search_tasks` 即可，没有 `mode=extend`、`base_result_set_id`、`task_version` 或 lineage 需要维护。

MCP 返回的 `resource_id` 是当前进程里的资源句柄。候选排序、比较、是否展示由 Agent 根据用户目标决定。

## 4. 结果判断

重点看：

- relevance：是否真的围绕当前主题；
- usefulness：能不能帮助完成目标；
- target fit：深度、语言、媒介是否合适；
- constraint fit：是否满足 must/exclude；
- substantive：是否有真实内容；
- credibility：当前任务所需证据是否足够；
- complementarity：是否与其他候选提供不同价值。

允许 unknown。没有证据不要靠平台名、标题、播放量补齐。

## 5. 什么时候 Inspect

只有某个未知事实会改变推荐或下载决策时才 Inspect 高潜项。可访问性、真实格式、版本、资源本体/landing page 是典型例子。

不要为了流程完整 Inspect 全部候选。

## 6. 什么时候停止

通常在这些情况下停止继续搜：

- 已有足够高质量且互补的候选；
- 剩余问题应由 Inspect 或用户选择解决；
- 下一轮只能重复同一搜索空间；
- 用户只是先看看，当前结果已经够用；
- 连续补搜没有带来新的有用内容。

停止表示当前证据已经足够做下一步，不等于声称“全网没有更好资源”。

## 7. 用户选择不需要后端状态

候选展示在正常对话里即可。用户说“第 2 个”“这两个”时，Agent 根据自己刚展示的列表找到相应 `resource_id`。

不调用 Presentation/Selection 保存工具，不维护位置版本，也不把正常对话行为复制成数据库事务。

## 8. 创作者枚举

已知 `creator_id` 且用户要查看该账号作品时：

```text
resource_browse_creator(platform=..., creator_id=..., limit=...)
```

这是内容枚举能力，不需要建立新的 Flow。
