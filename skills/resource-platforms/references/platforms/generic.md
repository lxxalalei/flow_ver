# Generic 通用搜索

## 执行入口

- Adapter：`scripts/generic/adapter.py`
- 搜索脚本：`scripts/generic/generic_search.py`
- 第三方依赖：无，仅使用 Python 标准库
- 认证：通常不需要；可选 `BAIDU_COOKIE`、`BING_COOKIE`
- 计划参数：`engines`，必须同时包含 `baidu`、`bing`

Adapter 把一条查询传给百度和 Bing。两个引擎并行执行，任一引擎失败不取消另一个；最终按规范化 URL 去重，并在两个引擎合并后截取 `max_results`，不是每个引擎各返回 `max_results`。

## 搜索路径

- 百度：请求 `https://www.baidu.com/s` 并解析结果页。
- Bing：先解析中文搜索 HTML；无结果或受阻时尝试 RSS 搜索。
- 过滤百度、Bing 和 Microsoft 自身跳转页，只保留可定位的外部 HTTP(S) 地址。

每条结果提供网页标题、链接、摘要，以及 `platform_signals.engine` 和该引擎中的排名。通用搜索只负责网页发现，费用、适龄性、可信度和内容完整性由 Selector 判断。

## 数量和错误

- 直接脚本默认20条，正常流水线使用 Stage 2 的 `max_results`。
- CLI把数量限制在1–100。
- 安全验证页返回 `SEARCH_BLOCKED`；单引擎失败允许结果和错误同时存在。
- 页面结构变化导致无可解析结果时，不应伪造结果。

## 当前验证状态

2026-06-30真实搜索能够返回 Bing/百度合并结果；百度可能触发安全验证，且通用结果相关性不稳定。Platform 应保留部分成功和错误，Selector 负责过滤跑题网页。
