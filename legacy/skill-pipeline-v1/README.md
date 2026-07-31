# 六阶段 Skill 流程快照

这里完整保留迁移前的七个 Skill 目录及其当前未提交修改：

```text
learning-resource-flow
resource-intent
resource-search
resource-platforms
resource-selector
resource-downloader
library-manager
```

它们原本通过 Stage JSON、manifest 和脚本串联。当前 active 实现已经切换为
`skills/learning-resource-flow -> mcp/education-resources`，不要把这里的 Skill
复制回顶层 `skills/`，除非正在执行有记录的回滚或对等测试。

该快照保留原目录的兄弟关系，因此旧代码内部基于 `skills/` 相对位置的引用大多仍
可用于审计。文档中的旧执行命令需要增加 `legacy/skill-pipeline-v1/` 前缀。
