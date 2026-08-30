# Download Guidance

下载阶段处理一个语义问题：**用户是否已经明确要把哪个资源获取下来。**

## 1. 下载触发条件

当用户已经明确表达下载、保存、获取等意图，并且目标资源可以确定时执行获取能力。

例如：

- “第 1、3 个帮我下下来” → 下载用户实际看到的第 1、3 个候选；
- “这本书能下的话帮我保存” → 对当前已选书籍直接尝试获取；
- “这批结果全部下载” → 当“这批”指向一个完整成功的 Expand Job 时，直接以完整集合进入批量下载；
- “先看看”“先别下载” → 保持发现、判断和选择阶段。

目标对象仍有歧义时，只澄清对象；目标对象已经明确时直接执行用户已经表达的获取意图。

## 2. 用户选择由稳定资源身份承接

Agent 根据当前对话中的 URL、平台稳定 ID、标题、作者和来源理解用户选中了哪个资源。

`resource_id` 作为当前 MCP 进程内的操作句柄使用。句柄失效时，通过已知稳定身份恢复同一个资源。

Expand 只负责把容器展开为真实子资源集合。Expand Job 的完整结果在用户明确选择全部或具体部分后进入 Download：

- 用户选择部分子资源 → 读取足以确定这些资源的页，再下载对应当前 `resource_id`；
- 用户明确选择完整集合，且 Expand Job 为 `succeeded` → 直接把 `expand_job_id` 交给 `resource_download`；
- Expand Job 为 `partial` / `failed` / `cancelled` → 当前已展示部分继续按明确候选处理，完整集合语义等待真实完整结果。

## 3. Resource 与 File 是不同层级

Resource 是用户选择的逻辑资源；File 是真实交付物。一个 Resource 可以产生 0、1 或多个文件。

例如：

```text
SmartEdu 课程
  -> 课堂视频
  -> 教学设计 / 讲义
  -> 配套音频

Generic Web 页面
  -> index.html
  -> source.html
  -> content.md
  -> metadata.json
```

`resource_inspect` 返回的 landing page、附件和媒体事实共同描述同一个逻辑资源的可获取内容。具体平台依据真实内容决定其自然交付文件集合。

Generic Web 的 `index.html` 是清洗正文的主要离线阅读交付物；`source.html` 保留原始 HTML 响应，`content.md` 和 `metadata.json` 提供清洗正文与元数据。正文图片获取失败等情况由 Job 的 `files` / `failures` 和终态真实表达。

用户明确要求精美或内容感知 HTML 时，先等待单网页 Download Job 到达终态，再按 [`html-design.md`](html-design.md) 取得设计上下文并渲染。

默认 `preferred_container="original"` 表示按资源本身的自然交付方式获取。自然交付可以是单文件，也可以是一组文件。

## 4. 直接下载与细粒度选择

用户说“把这个下载下来”且对象明确时，直接进入 `resource_download`；执行能力会 fresh Inspect 当前资源事实。

当未知内容会改变用户真正需要哪些文件时，先 Inspect，例如：

- “只要视频和课件”；
- “PDF 都要，视频只要最高画质”；
- “除了封面其他都保存”。

SmartEdu 等复合课程在用户需要查看内部文件时，可以 Expand 后按真实文件级资源选择；用户直接要求“下载整课”时按课程自然交付获取。

当前 Tool 能力只能表达部分细粒度选择时，向用户说明实际可选范围。

## 5. 格式约束保持用户原有强度

默认使用 `preferred_container="original"` 获取资源自然表示。

用户明确要求特定格式，且格式会影响实际使用时，把该格式作为真实获取条件。例如“我要能打印的 PDF”与“电子版都行”对应不同约束强度。

格式选择只在平台真实提供的表示中进行。当前表示无法满足用户格式要求时，依据真实结果说明限制并让用户决定下一步。

## 6. 批量下载承接用户已经明确的集合选择

`resource_download` 可以形成包含多个 Resource 的后台 Job，用于把重复的机械获取收进 MCP 后台执行。

```text
Expand
  -> 完整候选集合
  -> 用户明确选择全部或部分
  -> resource_download
  -> 后台逐 Resource fresh Inspect / exact Provider / 0..N Files
```

用户选择完整 Expand Job 时直接传 `expand_job_id`；用户选择部分结果时，只读取足以确定这些资源的页。

## 7. 成功由真实 Job 终态和文件结果决定

`resource_download` 和 `resource_expand` 返回持久 `job_id` 后，持续通过 `resource_job_status` 获取进度，直到进入：

```text
succeeded / partial / failed / cancelled / interrupted
```

到达终态后，根据真实 `files` / `failures` 说明结果。只有完整 `succeeded` 的 Expand Job 承担“全部结果”语义。

一个 Resource 产生多个文件、或一个 Job 包含多个 Resource 时，整体状态依据完整 `files` / `failures` 汇总，而不是根据某个单独成功文件推断。

## 8. 失败后回到当前资源和用户目标

失败后先根据真实错误确定：

- 当前资源是否暂时不可获取；
- 当前来源是否需要认证；
- 资源本体是否失效；
- 是否存在等价且满足用户要求的真实表示；
- 用户目标是否更适合转向替代资源。

替代资源、重试或停止由 Agent 根据用户目标和当前 Evidence 决定。

真实资源操作返回 `AUTH_REQUIRED` 时，进入 Session 登录引导。用户在浏览器中完成登录后，将捕获对象作为 opaque `capture` 交给 Session 保存能力，再重试原资源操作。

认证流程由用户在浏览器中完成；Agent 只承接 Session 捕获对象和登录后的原任务恢复。用户选择不登录或登录后仍无法获取时，说明当前限制并基于原目标判断替代来源。

## 9. 取消

用户明确要求停止正在进行的下载时，执行 Job cancel，并以真实取消终态说明结果。
