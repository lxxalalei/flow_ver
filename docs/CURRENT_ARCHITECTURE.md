# 当前架构

> 快照日期：2026-08-16  
> 只描述当前 active 运行事实。旧 Flow/ResultSet/Presentation/Selection/Plan/authority 设计可从 Git 历史和 `.agent/plans/archive/` 查阅。

## 1. 当前定位

`education-resources` 不再是资源工作流后端，而是一个**搜索与下载能力 MCP**。

```text
用户自然语言
  ↓
learning-resource-flow Skill / Main Agent
  │  理解目标、规划搜索、判断相关性、决定补搜/Inspect、展示候选、理解用户选择
  ↓
education-resources MCP
  │  Search / Browse Creator / Inspect / Download / Job Status / Cancel
  ↓
平台 Search Adapter / Inspector / Downloader
```

核心原则：

> MCP 只释放脚本能力，不复制对话状态，不把正常用户行为建模成数据库事务。

## 2. Active Tool

当前共 6 个：

1. `resource_search`
2. `resource_browse_creator`
3. `resource_inspect`
4. `resource_download`
5. `resource_job_status`
6. `resource_job_cancel`

已经移除的公共工作流 Tool：

- Flow start/list/status
- Presentation save
- Selection save
- Download prepare/start
- Archive
- Library search

## 3. 最小主链

```text
需求理解
  ↓
resource_search
  ↓
Agent 判断候选
  ├─ 关键事实不足 → resource_inspect
  ├─ 仍有明确缺口 → 再次 resource_search
  └─ 已足够 → 在对话中展示
                    ↓
                  用户选择
                    ↓
            用户明确要求下载
                    ↓
             resource_download
                    ↓
        fresh Inspect + Provider route
                    ↓
                 Downloader
                    ↓
                  Job
                    ↓
          resource_job_status
                    ↓
                  files
```

没有 ResultSet lineage、Presentation version、Selection version、selection digest、Plan、confirmation token 或 Outcome 状态链。

## 4. 内部状态

MCP 只保留两个进程内映射：

```text
resource_id -> 搜索返回的原始候选
job_id      -> status / progress / files / failures
```

这些状态只为跨 Tool 调用服务。

不使用 SQLite，不提供进程重启恢复。MCP 重启后资源句柄失效时重新搜索即可；下载 Job 被进程终止时按失败处理，不为了极端恢复场景重新引入 durable workflow。

## 5. Search

`search.py` 负责：

- Generic Web 搜索；
- 平台 Adapter 调度；
- 不同平台并发、单个平台 query 顺序执行；
- 返回实际候选和来源失败。

Adapter 的真实能力由“代码是否注册并实现 `search()`”决定。

已删除原先的 Retrieval authority 层：

- platform registry loader；
- Adapter descriptor/version/digest 权威校验；
- identity profile；
- private retrieval models；
- 多层候选身份证明。

当前 Service 只做简单业务去重：同一轮中 `(platform, canonical_url)` 相同的结果保留一次。

## 6. Inspect

Inspect 保留，因为部分平台的搜索结果只是线索，下载前确实需要解析真实资源表示，例如：

- Bilibili DASH 视频；
- Douyin 实际 MP4；
- Ximalaya track 音频；
- SmartEdu 具体 PDF/音视频；
- Shuge 文件；
- Generic Web 正文/landing page。

但 Inspect 不再持久化 Resolution、fingerprint、evidence snapshot 或 cache binding。调用一次得到当前事实即可；下载时会 fresh Inspect。

## 7. Download

用户明确要求下载后直接：

```text
resource_download(resource_ids=[...])
```

Service 对每个资源：

```text
fresh Inspect
  ↓
AcquisitionPlanner.route()
  ↓
exact registered Provider
  ↓
Downloader
```

`AcquisitionPlanner` 现在只是一次性路由器，不创建持久 Plan。

保留 exact Provider 的原因是业务需要：不同平台下载实现不同，且失败后不能偷偷换成不等价路径。它不是 authority chain。

## 8. Job

Job 是唯一保留的流程状态，因为真实下载可能耗时，用户需要：

- 查看进度；
- 得到最终文件；
- 查看失败；
- 取消任务。

当前使用小型 `ThreadPoolExecutor` 进程内 JobRunner。

Job 返回：

```text
job_id
status
progress
files[]
failures[]
```

不再有 JobItem / Outcome / AssetBundle 数据库投影。

## 9. 文件

下载文件直接保存到：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/
```

JobStatus 返回真实路径。当前没有 Archive/Library 状态层；后续如果需要“整理资料库”，应以独立、明确的文件整理能力实现，而不是恢复整个下载状态机。

## 10. 登录

SessionStore 继续保留，因为 Bilibili、Douyin、Ximalaya 等平台真实搜索/下载会需要合法登录态。

登录要求属于平台事实，不属于资源工作流状态。`AUTH_REQUIRED` 必须真实返回。

## 11. 当前目录

```text
mcp/education-resources/src/education_resource_mcp/
├── server.py
├── service.py
├── config.py
├── search.py
├── inspection.py
├── inspection_registry.py
├── jobs.py
├── sessions.py
├── session_bridge.py
├── adapters/
└── acquisition/
```

已经删除：

```text
storage.py
models.py（旧 Flow/Contract 输入模型）
retrieval/
contracts/
taxonomy.py
```

## 12. 当前验证重点

不再以“旧状态契约是否全部兼容”为目标。

验证优先级：

1. Search 脚本是否返回真实、可用候选；
2. Inspect 是否能得到下载需要的实际 Representation；
3. Download 是否真的产生正确文件；
4. OpenClaw 长任务是否不再因为 MCP 状态和 Tool Result 膨胀而频繁 compaction/中断；
5. 各平台真实失败是否诚实暴露。

测试只围绕这些业务行为保留。旧 Flow、SQLite migration、Presentation、Selection、Plan/digest 的专项测试已删除，不允许它们反过来要求恢复旧架构。
