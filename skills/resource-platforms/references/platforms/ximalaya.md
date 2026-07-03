# 喜马拉雅搜索

## 执行入口

- Adapter：`scripts/ximalaya/adapter.py`
- 搜索脚本：`scripts/ximalaya/ximalaya_search.py`
- 认证：公开搜索通常不需要；可选 `XIMALAYA_COOKIE`
- 计划参数：`core=album|track`、`free_only`、`sort=relevance|popularity|newest`

`core=album`返回专辑，`core=track`返回单条声音。`free_only`请求免费过滤；排序参数会转换为接口支持的相关度、播放量或时间条件。

## 搜索路径

1. 优先调用官方 `https://www.ximalaya.com/revision/search`。
2. 主接口异常或无结果时，降级到 `https://apis.netstart.cn/ximalaya/search` 镜像。

单页最多20条，必要时分页；页间等待0.5秒。直接脚本默认20条，正常流水线使用 Stage 2 的 `max_results`。

## 输出和错误

结果提供专辑或声音ID、标题、详情页、简介、主播、封面、时长、发布时间、付费状态，以及播放量、评分、声音数量和主播认证等平台信号。

主脚本的旧字段可能包含自身质量估计，Adapter不会把它转换成 Selector 的最终评分。主接口和镜像均失败或返回空内容时应记录平台执行或解析错误，不把接口失败解释为真实零结果。

## 当前验证状态

2026-06-30真实搜索成功，并在“小学古诗”测试计划中返回专辑和音频结果。镜像属于降级来源，失效时不能影响主接口结果。
