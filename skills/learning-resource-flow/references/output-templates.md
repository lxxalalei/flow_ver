# Flow 输出模板

## Stage 3：搜索凭据提醒

只列出当前搜索计划中缺少必需凭据或认证已失效的平台，不显示 Cookie、Token、请求头内容或私有文件正文：

```text
开始搜索前，还需要配置以下平台的登录信息：

- {platform_name}：{credential_requirement}
  用途：仅用于本次平台搜索，不会写入搜索计划或结果。

你可以选择：
1. 由我协助在本地配置后继续搜索
2. 暂时跳过这些平台，继续搜索其他来源
3. 取消本次任务
```

认证在执行期间失效时，将首句改为“以下平台的登录信息缺失或已失效”。用户选择协助后，可以直接提供所需凭据，也可以使用可用的浏览器登录方式；由模型负责创建本地私有文件、更新凭据约定并完成注入，不把建文件或编辑配置的工作交给用户。凭据写入后不得在回复或日志中回显完整内容。

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
