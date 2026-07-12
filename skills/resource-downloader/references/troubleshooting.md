# Downloader 故障排查

先查看 `stage5_download.json` 中对应资源的 `error.error_code`。不要绕过统一执行器手工重做下载，否则临时目录、格式校验和 Stage 5 结果可能不一致。

## 网络错误

- `NETWORK_TIMEOUT`、`NETWORK_CONNECTION_FAILED`：确认来源页面仍可访问；执行器会有限重试一次。
- `NETWORK_RATE_LIMITED`：停止高频请求，稍后重新执行，不增加并发。
- `NETWORK_SSL_ERROR`：Windows 会在系统 `curl.exe` 可用时使用证书存储回退；不要关闭证书校验。
- `DOWNLOAD_TOO_LARGE`：调整计划中的 `max_bytes`，确认用户确实需要该文件后再运行。

## 认证与访问限制

- `AUTH_REQUIRED`：只有平台明确支持且用户已授权时，才通过环境变量提供 Cookie/CDP。
- `ANTI_CRAWL_CAPTCHA`：停止自动下载，保存公开网页或来源链接。
- `CONTENT_PREMIUM_OR_DRM`：不重试、不绕过，按公开内容降级。
- 地区、IP 或站点策略限制：不使用代理轮换或规避手段。

凭据不得写入 `download_plan.json`、Stage 5、日志或资料库。

## 文件问题

- `DOWNLOAD_FILE_CORRUPTED`：来源可能返回错误页、空文件、截断文件或损坏容器；确认 URL 后重试一次。
- `DOWNLOAD_UNEXPECTED_FORMAT`：检查 `expected_formats` 是否正确，或平台是否只返回了 sidecar。
- `DOWNLOAD_NOT_DIRECT_FILE`：该 URL 是网页，应交给 `auto` 或 `webpage`。
- 平台脚本返回成功但没有文件：属于平台入口缺陷，修复脚本，不伪造结果。

可单独检查文件：

```bash
python -c "from content_validation import validate_download_file; print(validate_download_file(r'<path>'))"
```

## 网页归档问题

- Level 2 正常包含 `source.html`、`content.md`、`metadata.json`。
- 正文为空、只有登录提示、验证码或“启用 JavaScript”外壳时，不应标记为 Level 2。
- 动态页面当前不启用浏览器渲染，按 Level 3 保存来源信息。
- 当前不下载页面内图片；不要把缺图误报为完整原文件。

## 平台入口问题

- 确认入口位于 `scripts/platforms/`，并支持 `download <url> -o <dir>`。
- 运行环境缺少可选工具时，应返回 `SYSTEM_TOOL_NOT_FOUND` 或非零退出码，由执行器降级。
- Bilibili、Douyin 的 Downloader 本地入口负责调用现有引擎；不要让模型直接运行搜索层脚本。
- NLC 只支持 `nlc:yuewen:*` 公开 EPUB；馆藏目录和站内页面走网页归档。

## 复核命令

```bash
python resource-downloader/scripts/run_download_plan.py <session_dir>
python resource-downloader/scripts/validate_output.py <session_dir>
python -B -m unittest discover -s resource-downloader/tests -p "test_*.py" -v
```

独立校验失败时修复一次；仍失败则停止进入归档阶段。
