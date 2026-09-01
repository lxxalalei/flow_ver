# Real Platform Smoke Matrix

> 目的：用少量真实网络样本验证平台能力仍然能完成真实用户路径。它不是新的 E2E 框架，也不替代单元测试、MCP contract test 或真实 OpenClaw User Journey。

## 原则

- 只验证真实平台行为，不用 mock 结果冒充平台健康。
- 一级 release gate 固定保持小规模；不因为接入平台数量增加就机械扩成全平台扫描。
- 每条 smoke 使用稳定、公开、低风险的样本或查询；样本失效时替换样本，不把样本本身变成业务规则。
- 平台失败只记录当前能力失败，不推导“资源不存在”。
- Search 只证明发现；Expand 只证明结构枚举；Download 只以真实文件和健康检查证明成功。
- 不为 smoke 增加 fallback、硬编码结果、固定页数或任意截断。
- 登录能力不做统一 preflight；只有真实操作返回 `AUTH_REQUIRED` 时才验证 Session 路径。

## Tier 1 — Release Gate

| 平台/能力 | 真实 smoke | 通过条件 | 主要捕获的回归 |
| --- | --- | --- | --- |
| Bilibili | `resource_search` 找到公开学习视频；对一个公开 creator/collection 做 `resource_expand`；下载一个明确选中的公开视频 | Search 返回真实 URL；Expand 到来源真实结束并可分页读取；Download Job 产生可用媒体文件 | WBI/接口变化、creator/collection 结构变化、下载解析失效 |
| Douyin | `resource_search` 找到公开视频；对一个已知 creator/collection 做 `resource_expand`；下载一个明确选中的公开视频 | Search/Expand 返回真实资源身份；Download 产生可用媒体文件；失败时错误事实明确 | 签名、页面结构、风控和媒体地址变化 |
| CCTV | 搜一个公开视频并下载；额外使用一个已确认的旧 H5E 样本验证当前最高可用画质 | clear/H5E 先按真实画质统一选择最高档；clear 直接下载，H5E 由 Python native 解密；最终 MP4 通过 ffmpeg 全解码检查；失败不静默降质 | CCTV 页面/API变化、最高画质选择、旧 H5E native 解密、ffmpeg 集成 |
| SmartEdu | 搜一个明确教材/同步主题；展开一个已知教材或课程容器；Inspect 一个具体资源 | Search 匹配真实版本/课程；Expand 完整结束；Inspect 返回真实组成/可获取事实；匿名能力不被错误转成 Session preflight | 教材结构、分片结束条件、资源 detail、匿名/认证边界 |
| Ximalaya | 搜一个公开音频主题；完整展开一个公开专辑；下载一个明确选中的 track | Search 返回真实 track/album URL；Expand 完整结束；下载产生可播放音频 | 搜索接口、专辑分页、音频获取路径变化 |
| Generic Web | `resource_import_url` 一个稳定公开文章；Download；检查 `source.html/content.md/index.html`；对另一轮明确视觉请求执行 HTML Design | 原始响应保留；正文抽取/Reader 事实明确；离线 Reader 不依赖在线资源；HTML Design 不改写完整清洗正文 | 网页获取、Trafilatura、图片内嵌、Reader、HTML Design 边界 |

## Tier 2 — Targeted Only

以下平台不进入每次 release 的固定全跑矩阵。只有相关 Adapter/能力发生修改，或真实用户 Journey 暴露问题时做对应真实 smoke：

- Zjer
- Baidu Wenku
- LibGen
- Zhihu
- Shuge
- Yixi / Open163 / Kepu
- Weibo / WeChat
- Runoob

这样可以避免“接入一个平台就永久增加一条发版阻塞测试”的线性膨胀。

## 建议样本保存方式

真实 URL、creator URL、album URL、课程 URL 等易变化 fixture 不写进业务代码，也不要固化成平台规则。测试机器使用本地、非运行时配置，例如：

```json
{
  "BILIBILI_CREATOR_URL": "https://...",
  "BILIBILI_VIDEO_URL": "https://...",
  "DOUYIN_CREATOR_URL": "https://...",
  "CCTV_OLD_H5E_URL": "https://...",
  "SMARTEDU_CONTAINER_URL": "https://...",
  "XIMALAYA_ALBUM_URL": "https://...",
  "GENERIC_WEB_URL": "https://..."
}
```

fixture 只为测试定位真实样本，不进入 MCP runtime contract。

## 每次 smoke 记录的事实

只记录可验证事实：

```text
commit SHA
执行时间
平台/能力
输入 query 或 fixture identity
实际 Tool/调用路径
成功/失败
返回的真实 URL / job_id（必要时）
文件数量与类型
媒体/HTML 健康检查结果
真实错误码/错误信息
耗时
```

不要记录或维护：

```text
PlatformHealthState
CapabilityScore
AuthorityDigest
长期成功率状态机
自动 fallback 决策
```

需要趋势分析时，从历史 smoke 结果计算，不把统计结果反过来变成运行时权威状态。

## Release 判定

Tier 1 中与本次改动直接相关的 smoke 必须通过。

如果某个未修改平台因为真实外部平台临时故障失败：

1. 先确认是当前代码回归还是外部平台事实；
2. 不静默切换到不等价路径以让测试变绿；
3. 记录失败证据；
4. 如果核心用户路径仍有等价真实能力可用，由人工决定是否阻塞发布。

“所有平台永远 100% 在线”不是 release gate；“系统能准确暴露真实平台状态并完成核心用户路径”才是。
