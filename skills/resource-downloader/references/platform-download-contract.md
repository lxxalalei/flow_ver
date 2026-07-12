# 平台单资源下载接口

平台脚本只负责把一个已选资源写入指定临时目录。重试、校验、降级、Stage 5 结果和正式目录提交全部由 Downloader 统一执行器负责。

## 命令接口

每个平台入口至少支持：

```bash
python scripts/platforms/{platform}_download.py download <source_url> -o <output_dir>
```

- `source_url`：Stage 3 的公开来源地址。
- `output_dir`：Downloader 创建的绝对 `.partial/` 临时目录。
- 成功返回码为 `0`，并至少产生一个普通文件。
- 失败返回非 `0`，向 stderr 输出简洁、可分类的原因。
- 不向 stdout 输出凭据、Cookie、token 或大段页面内容。
- 入口只能取得预览、替代版本或公开文稿时，可在 stdout 输出 `Level 1`—`Level 3` 产物提示；最终状态仍由 Downloader 根据文件和提示统一生成。

入口可以按平台支持以下可选参数：

- `--cookie <path>`：安全运行环境提供的 Cookie 文件。
- `--cdp <url>`：用户已经授权的浏览器会话。
- `--timeout <seconds>`、`--max-bytes <bytes>`：执行限制。
- 平台明确需要的格式筛选参数。

## 文件规则

- 只写入 `output_dir`，不得引用或移动电脑中其他既有文件。
- 不创建符号链接、快捷方式或指向外部路径的清单。
- 临时分片在脚本返回前完成合并或清理；未完成文件不能伪装为成功。
- 文件名应稳定、安全，并保留可识别扩展名。
- 可以产生字幕、封面和 JSON 等 sidecar；至少一个主文件必须与资源能力相符。

Downloader 会在脚本返回后统一检查：

- 进程退出码和超时。
- 文件是否存在、是否位于临时目录、是否为符号链接。
- 文件魔数、容器结构、错误 HTML 页面和期望格式。
- 全部通过后才原子提交到 `{session_dir}/downloads/`。

## 职责边界

平台入口不负责：

- 搜索、推荐、评分或替换资源。
- 生成 `stage5_download.json`。
- 单独写入最终 Level 0—3、决定是否重试或是否元数据降级。
- 决定正式资料库目录。
- 绕过登录、付费墙、DRM、验证码、地区限制或其他访问控制。

新增平台后，在 `run_download_plan.py` 注册入口，并通过 `platform_is_applicable()` 限制适用资源类型。
