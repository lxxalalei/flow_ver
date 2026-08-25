# SmartEdu 平台 Playbook

平台结构事实的唯一权威记录。适配器代码只负责稳定操作（索引拉取、分片迭代、类型透传）；端点、标签分类学、条目拓扑、坑都记在这里。模型遇到平台行为与本文不符时：以实测为准，修完后**回写本文**；验证走当前架构的聚焦测试（`mcp/education-resources/tests/test_smartedu_textbook_expand.py` 等），旧 smoke 脚本未随 `catalog_expand` 迁移。

最后实测：2026-08-20（实测记录见文末）。

## 匿名访问边界

- 公共搜索、教材索引、CDN 静态 JSON 全部匿名可访问，**不要**附带浏览器 token（跨网络重放会被拒）。
- 只有 Inspect / Download 真实返回 `AUTH_REQUIRED` 才走 Session Tool。

## 教材索引（resource_expand 数据源）

```text
https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/national_lesson/teachingmaterials/version/data_version.json
  -> {"urls": [索引分片 part_1..N]}     # 2026-08-20: 3 片, 共 2970 本教材
教材条目: 每片一个数组, 每项 {id, title, tag_list}
资源分片: .../teachingmaterials/{mid}/resources/part_100.json, part_101... 以 404 结尾
```

### tag_list 维度（分类学）

| 维度 | 含义 | 示例值 |
| --- | --- | --- |
| `zxxxk` | 学科 | 语文、数学 |
| `zxxnj` | 年级 | 一年级 |
| `zxxcc` | 册次 | 上册、下册 |
| `zxxbb` | 版本（出版社体系） | 统编版、人教版、北师大版 |
| `zxxxd` | 学段（**含学制信息**） | `小学`、`小学（五•四学制）` |
| `zxxxjjc` | 教材体系 | `新教材`、`旧教材` |

**学制判断**：stage 值含 `五四学制`（去掉空格/圆点后匹配）即五四制，否则六三制。

### 条目拓扑（关键）

同一 `学科/年级/册次/版本` 下通常有 **4 个教材条目**：

```text
新教材 × 六三制   ← 2022 课标修订版教材本体，用户说"新课标/2022课标修订版"指这个
新教材 × 五四制
旧教材 × 六三制
旧教材 × 五四制   （部分条目为空壳，0 绑定）
```

spec 第 5 段起可选：`新教材`/`旧教材`（体系）、`六三制`/`五四学制`（学制）。**默认不筛**——枚举所有条目，按条目元数据让用户/上层选择。

### 版本别名（用户语言 → 平台标签）

| 用户说 | 平台值 |
| --- | --- |
| 2022课标修订版 / 2022课标 / 新课标 | `zxxxjjc=新教材`（体系维度，不是 zxxbb 版本！） |
| 旧课标 / 2011课标 / 老教材 | `zxxxjjc=旧教材` |

用户把别名放到第 4 段（`语文/一年级/上册/2022课标修订版`）也能解析：识别为体系过滤，版本留空。

### 资源绑定类型

| resource_type_code | 含义 | 独立页面 | catalog_expand 处理 |
| --- | --- | --- | --- |
| `national_lesson` | 同步课堂课 | `syncClassroom/classActivity?activityId=` | 枚举为条目 |
| `elite_lesson` | 精品课 | `qualityCourse?courseId=` | 枚举为条目 |
| `singing` | 吟唱/朗读（assets_video） | **无** | 只计数进 expand job summary，不伪造 URL |

**已知盲区**：教材详情页挂的教学资源（教学设计、课件、任务单、练习题）**不在这个索引里**，当前能力面覆盖不到。用户要"所有资源"时必须明说这个缺口，不要把课程式绑定装作全量。

## 课程是复合资源

课程/教材详情是逻辑复合资源：主视频（HLS，下载时取分片、AES 解密、ffmpeg 封 MP4）+ PDF 资料 + 伴随音频，一个资源自然交付多文件。不要从 URL 猜扩展名。

## 排障经验

- 教材索引拉取失败 → 看网络出口/IP 风控，不补 token 重试（匿名端点）。
- `RESOURCE_NOT_FOUND` 的错误消息带同维度下实测可用版本值列表——直接用它，不要自己猜规格。
- 索引分片循环里单片失败会跳过（partial 容忍）；资源分片 404 是正常终止信号。
- Windows 控制台打印中文/特殊字符（`五•四` 的圆点）需 `PYTHONIOENCODING=utf-8`。

## 实测记录

- 2026-08-20：`语文/一年级/上册` 4 条目实测绑定——新教材六三 `b7062df1` 62 条（45 同步课 + 17 singing）；新教材五四 `52df02ab` 26 条（全 elite_lesson）；旧教材六三 `5ce96672` 81 条（64 同步课 + 16 elite + 1 singing）；旧教材五四 `b8f11d0d` 0 条。全套索引拉取约 2 秒。
