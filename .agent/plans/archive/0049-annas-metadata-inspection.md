# Task Spec 0049：Anna's Archive 检查改为 md5 元数据通道

- 状态：completed
- 创建日期：2026-08-14
- 完成日期：2026-08-14
- 分支：`codex/growth-resource-taxonomy-rework`
- 来源：0028 用户真实测试反馈（2026-08-14，Anna's Archive 电子书 13 个候选检查全部失败）

## Goal（必填）

用户/系统能够：对携带合法 32 位 md5 的 `annas-archive` 资源执行 `resource_inspect`
时，服务端基于搜索元数据直接产出 Resolution（materializable primary document），
不发起对合成详情页 `annas-archive.gl/md5/<md5>` 的网络请求；该站点风控（403）
或不可达不再阻塞后续 `resource_download_prepare`。

## Non-goals（必填）

- 不改 `AnnasArchiveSearchAdapter` / `AnnasArchiveDownloader`：搜索仍走 Libgen
  镜像，下载仍按 md5 匿名直连 Libgen 镜像并在下载后做真实格式校验。
- 不为检查增加 Libgen 镜像可达性探测；下载失败继续按 Job 项结构化失败（DOWNLOAD_FAILED 可重试）。
- 不改 `source_url` 的合成规范（`annas-archive.gl/md5/<md5>` 是给用户看的身份页）。
- 不动其他平台 inspector 的 `platform_bounded_get` 行为与 `_enrichment_allowed` 语义。
- 不新增抽象层、新错误码或新契约字段；`inspection.method` 用既有自由字符串段表达 `platform_metadata`。

## Acceptance Criteria（必填）

### AC-01 合法 md5 不触发网络请求

```text
Given: 资源 platform=annas-archive，platform_signals.md5 为合法 32 位十六进制
When: AnnasArchiveInspector.inspect(resource)
Then: 不发起任何 HTTP 请求（transport.requests 为空）；
      resolution_status=resolved，resource_type=book，
      primary representation kind=document、role=primary、scope=primary_resource、
      materializable=true，metadata.md5 保留，inspection.method=platform_metadata。
```

### AC-02 事故回归：详情站点风控不再阻塞

```text
Given: source_url 指向 annas-archive.gl（403/不可达），资源带合法 md5
When: inspect
Then: 与 AC-01 相同的成功结果；availability=available，无 AUTH_REQUIRED failure。
```

### AC-03 非法 md5 仍被拦截

```text
Given: 资源无合法 md5
When: inspect
Then: PLATFORM_VALIDATION_BLOCKED / policy_blocked，无网络请求（既有行为不变）。
```

### AC-04 其他平台不受影响

```text
When: 运行 inspector 目录测试（nlc/ximalaya 等）
Then: platform_bounded_get、AUTH_REQUIRED 401、404 unavailable 语义保持不变。
```

## 验证计划

Level 2：`tests/test_platform_inspectors_catalog.py`、`tests/test_inspect_contract.py`、
`tests/test_platform_adapters.py`（annas 部分）；`python -m compileall`；`git diff --check`。
部署后由用户在 OpenClaw 中重测真实链路（记回 0028）。
