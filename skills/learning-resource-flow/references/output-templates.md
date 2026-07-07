# Flow 输出模板

## Stage 4：候选展示

原样展示 Selector 返回的候选文本。不要在 Flow 中维护第二套候选格式、分组顺序或编号规则；平台错误、候选摘要和选择说明均以 Selector 展示文本为准。

## Stage 5：下载进度

```text
下载进度：{completed}/{total}
成功 {success_count} · 降级 {degraded_count} · 失败 {failed_count}
当前：{title} — {status}
```

降级时补充 `degraded_level` 和缺失内容；失败时给出可理解的原因，不暴露 Cookie、token 或内部堆栈。

## Stage 6：最终汇总

```text
处理完成。

成功获取：{success_count}
降级保存：{degraded_count}
下载失败：{failed_count}
已归档：{archived_count}
重复跳过：{skipped_count}
资料库位置：{library_root}
```

按“成功、降级、失败、归档跳过”分组列出资源。每条至少包含标题、来源、最终状态和本地路径或来源链接。

## 无候选

```text
本次从 {platform_count} 个平台取得 {raw_count} 条原始结果，但筛选后没有符合当前条件的候选。
主要原因：{top_filter_reasons}

可以调整关键词、增加平台，或明确放宽费用/语言/质量条件。
```
