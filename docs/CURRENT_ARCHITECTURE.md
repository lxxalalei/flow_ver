# 当前架构

> 快照日期：2026-08-16  
> 只描述当前 active 运行事实。旧 Flow/ResultSet/Presentation/Selection/Plan/authority 设计只保留在 Git 历史和归档计划中。

## 1. 当前定位

`education-resources` 是一个**搜索、下载、归档能力 MCP**，不是资源工作流后端。

```text
用户自然语言
  ↓
learning-resource-flow Skill / Main Agent
  │  理解目标、规划搜索、判断候选、理解用户选择、决定归档分类
  ↓
education-resources MCP
  │  Search / Browse Creator / Inspect / Download / Job / Archive
  ↓
平台 Search Adapter / Inspector / Downloader + 本地资料库
```

核心原则：

> MCP 只释放真实脚本与文件能力，不复制对话状态，不把正常用户行为建模成数据库事务。

## 2. Active Tool

当前共 7 个：

1. `resource_search`
2. `resource_browse_creator`
3. `resource_inspect`
4. `resource_download`
5. `resource_job_status`
6. `resource_job_cancel`
7. `resource_archive`

已经移除的工作流 Tool/状态：

- Flow start/list/status
- ResultSet lineage
- Presentation save
- Selection save
- Download prepare/start
- Plan / confirmation token
- ArchiveRecord / AssetBundle / Library state

## 3. 最小主链

```text
需求理解
  ↓
resource_search
  ↓
Agent 判断候选
  ├─ 关键事实不足 → resource_inspect
  ├─ 仍有明确缺口 → 再次 resource_search
  └─ 已足够 → 展示给用户
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
            Agent 判断分类
                    ↓
             resource_archive
                    ↓
                资料库文件
```

## 4. 内部状态

MCP 只保留两个进程内映射：

```text
resource_id -> 搜索返回的原始候选
job_id      -> status / progress / files / failures
```

这些状态只为跨 Tool 调用服务。

不使用 SQLite，不提供 Flow 恢复。MCP 重启后资源句柄失效时重新搜索即可；不为低频恢复场景重新引入 durable workflow。

## 5. Search

`search.py` 负责 Generic Web 和平台 Adapter 调度。Adapter 的真实能力由“代码是否注册并实现 `search()`”决定。

已删除原 Retrieval authority 层：platform registry、descriptor/version/digest、identity profile 等。Service 只做同一轮 `(platform, canonical_url)` 的简单业务去重。

## 6. Inspect

Inspect 用于把搜索线索解析成当前真实可用的资源表示，例如 Bilibili DASH、Douyin MP4、Ximalaya 音频、SmartEdu 文件、Generic Web 页面等。

不再持久化 Resolution、fingerprint、evidence snapshot 或 freshness binding。需要下载时重新 Inspect 一次。

## 7. Download

用户明确要求下载后直接：

```text
resource_download(resource_ids=[...])
```

每个资源执行：

```text
fresh Inspect
  ↓
AcquisitionPlanner.route()
  ↓
exact registered Provider
  ↓
Downloader
```

`AcquisitionPlanner` 只是一次性路由器，不创建持久 Plan。保留 exact Provider 是因为不同平台确实对应不同下载脚本，而不是为了 authority chain。

## 8. Job

Job 保留，因为真实下载可能耗时，用户需要查看进度、结果、失败和取消。

返回只保留：

```text
job_id
status
progress
files[]
failures[]
```

不再有 JobItem / Outcome / AssetBundle 数据库投影。

## 9. Archive

归档恢复为一个**薄文件能力**：

```text
resource_archive(
  job_id=...,
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

Main Agent 负责根据资源语义决定领域和主题；MCP 只把该 Job 已成功下载的真实文件移动到资料库。

默认资料库根目录使用当前系统用户的“文档/Documents”目录：

```text
~/Documents/学习资料库/
```

Windows 通常对应：

```text
C:\Users\<用户名>\Documents\学习资料库\
```

可通过：

```text
EDUCATION_RESOURCE_MCP_LIBRARY_DIR
```

单独配置。

目录结构：

```text
学习资料库/
  04-自然科学/
    天文与宇宙/
      视频|音频|图文|其他/
        文件
```

顶层分类来自包内 `library-taxonomy.json`。它只是目录配置，不参与搜索判断、状态流转或版本校验。

没有：

```text
archive_id
ArchiveRecord
AssetBundle
archive version/digest
ready state
```

归档完成后，Job 中对应文件路径会更新为资料库最终路径，避免返回已经失效的下载临时路径。

## 10. 登录

SessionStore 继续保留，因为部分平台真实搜索/下载需要合法登录态。`AUTH_REQUIRED` 属于平台事实，不属于资源工作流状态。

## 11. 当前核心目录

```text
mcp/education-resources/src/education_resource_mcp/
├── server.py
├── service.py
├── config.py
├── search.py
├── inspection.py
├── inspection_registry.py
├── archive.py
├── library-taxonomy.json
├── jobs.py
├── sessions.py
├── session_bridge.py
├── adapters/
└── acquisition/
```

已删除且不应恢复为主链：

```text
storage.py
models.py（旧 Flow/Contract 输入模型）
retrieval/
contracts/
taxonomy.py（旧运行时 taxonomy/校验体系）
```

## 12. 当前验证重点

1. Search 是否返回真实可用候选；
2. Inspect 是否得到下载需要的实际 Representation；
3. Download 是否产生正确文件；
4. Archive 是否把成功文件移动到正确资料库目录并返回最终路径；
5. OpenClaw 长任务是否不再因 MCP 状态和 Tool Result 膨胀而频繁 compaction/中断；
6. 平台真实失败是否诚实暴露。

不以旧状态契约兼容为目标，也不让旧 Flow/SQLite/Plan/digest 测试迫使实现重新复杂化。
