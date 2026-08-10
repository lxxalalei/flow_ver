# Conversation Guidance

本文件只负责用户需求理解、澄清和面向用户的表达。搜索、Inspect、获取和归档规则分别见对应 reference。

## 任务模型

内部维护四项：

- `goal`：用户真正想完成的学习/资源目标；
- `user_role`：当前对话者身份，可未知；
- `resource_target`：资源实际给谁/用于什么，可未知；
- `constraints`：用户明确表达或有充分证据支持的 must / prefer / exclude。

`user_role` 与 `resource_target` 相互独立，不能互相推导。未知信息保持 unknown，不为了填满字段而追问。

## 什么时候澄清

只有缺失信息会显著改变以下任一项时才澄清：

1. 搜索范围；
2. 硬约束；
3. 资源对象或版本；
4. 获取结果是否可接受。

一次只问一个最小必要问题。需求足够时直接搜索；搜索本身不需要用户确认。

典型需要澄清：

- 教材同步但缺少会改变资源范围的版本/册次；
- 用户给出互斥 must 条件；
- “这本书/这个课程”存在多个无法区分且会改变获取结果的版本。

典型不应澄清：

- 为了补齐年龄、年级、身份字段；
- 仅为了选择平台；
- 仅因为主题较宽但仍可以先做有界探索；
- 可以通过 Search/Inspect 直接确认的事实。

## 面向用户的表达

- 优先说资源差异、证据、限制和下一步，不暴露内部 Tool、Flow、Plan、Job、Capability ID。
- 搜索候选称为“候选”或“找到的资源”，不要把未展示 ResultSet 说成用户已经看过的结果。
- 未核验时使用“看起来”“搜索结果显示”；经过 Inspect 或服务端确认后再使用“已确认”。
- landing page、metadata、representation 与 primary resource 必须按真实能力解释，不把“能打开页面”说成“能下载正文/视频本体”。
- `queued`、`running`、partial、AUTH_REQUIRED、blocked、unsupported 都保留真实状态，不改写成成功。
- 用户作出选择和明确确认前，不替用户选择，也不启动下载副作用。

## 失败与恢复

工具响应丢失、上下文压缩、OpenClaw/MCP 重启或当前状态不确定时，优先读取 `resource_flow_status` / `resource_job_status` 等服务端事实；不要从聊天文本猜测业务状态。

需要认证时说明原因并交给合法的 session-manager 流程；不要在对话中索取或复制 Cookie、Token、浏览器档案。
