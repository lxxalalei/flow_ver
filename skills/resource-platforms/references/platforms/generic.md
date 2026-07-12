# Generic 通用搜索

## 执行入口

- Adapter：`scripts/generic/adapter.py`
- 搜索脚本：`scripts/generic/generic_search.py`
- 第三方依赖：无，仅使用 Python 标准库
- 认证：DuckDuckGo、Bing、页面版百度通常不需要；`qianfan` 需要 `QIANFAN_API_KEY`，由 Flow 在计划实际选中该引擎时预检并注入。
- 计划参数：`engines`，必须包含 `duckduckgo`；中文网页默认使用无凭据的 `duckduckgo` 与 `bing`，可按需额外包含 `qianfan` 或 `baidu`

Adapter 按计划把一条查询传给千帆、DuckDuckGo、Bing 或百度。多个引擎并行执行，任一引擎失败不取消其他引擎；最终按规范化 URL 去重，并在引擎合并后截取 `max_results`，不是每个引擎各返回 `max_results`。只有计划明确选中 `qianfan` 时 Flow 才预检 Key 并在缺失时询问配置或跳过；普通搜索不会因千帆凭据暂停。

## 搜索路径

- DuckDuckGo：请求 HTML 搜索页并解析自然结果。
- Bing：先解析中文搜索 HTML；无结果或受阻时尝试 RSS 搜索。
- 百度：请求 `https://www.baidu.com/s` 并解析结果页。
- 千帆：调用百度千帆 `web_search` API，返回标题、链接、摘要和日期；`site:` 查询会转为原生站点过滤。
- 过滤搜索引擎自身跳转页，只保留可定位的外部 HTTP(S) 地址。

每条结果提供网页标题、链接、摘要，以及 `platform_signals.engine` 和该引擎中的排名。通用搜索只负责网页发现，费用、适龄性、可信度和内容完整性由 Selector 判断。

## 数量和错误

- 直接脚本默认20条，正常流水线使用 Stage 2 的 `max_results`。
- CLI把数量限制在1–100。
- 安全验证页返回 `SEARCH_BLOCKED`；单引擎失败允许结果和错误同时存在。
- 页面结构变化导致无可解析结果时，不应伪造结果。

## 当前验证状态

2026-07-10 中文网页搜索默认使用 DuckDuckGo 与 Bing，不要求凭据；千帆只在用户明确要求或环境已明确启用时加入。页面版百度可能触发安全验证，通用结果仍可能跑题；Platform 应保留部分成功和错误，Selector 负责过滤跑题网页。
