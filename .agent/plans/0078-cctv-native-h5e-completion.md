# 0078 — CCTV 旧 H5E 原生解密收口

- 状态：in_progress
- 创建日期：2026-08-29
- 完成日期：未完成
- 范围：`mcp/education-resources/src/education_resource_mcp/adapters/cctv_h5e.py`、`cctv_download.py`、CCTV focused tests 与真实旧 H5E 验收；公共 MCP Tool 面不变

## Objective

让 CCTV 旧版（重点为 2025-08 之前）`hls_h5e` 视频优先由 Python native 路径稳定完成解密和 MP4 交付，并用真实老视频证明 native 路径能否替代现有 JS/WASM fallback。只有真实反例消失后才允许删除 `vendor/cctv-h5e`。

## Non-goals

- 不宣称覆盖 CCTV 所有页面、所有 host 或 2025-08 后全部新加密；
- 不新增 MCP Tool、平台、Agent 语义状态或 crypto/provider framework；
- 不为了目录整洁提前删除仍有真实兜底价值的 WASM；
- 不用 mock/unit 结果替代真实 H5E 视频解码证据；
- 不因上游实现不同而无证据覆盖本仓库已有真实样本校准行为。

## Business invariants

- clear MP4 / HLS 直接下载，不进入 H5E 解密；
- H5E 优先使用 `getHttpVideoInfo` 的 per-video `hls_h5e_url`；
- type25 才开启 new-mode，不猜模式、不双路盲解；
- HLS 分片可并发下载，但 native/WASM 解密 Session 都属于完整有序 stream；
- native decrypt 前后 TS 总字节长度保持一致；
- native 失败必须真实失败，当前仍允许既有 WASM fallback；
- classic `o+80` guard 保留：0069 已有 2021 样本与官方 worker 的真实对照证据。

## Current evidence

### 已完成的 native 修正

- `795fca1`：恢复 type25 → new-mode Session dispatch；
- `b37b78e`：type1/type5 使用变换前原始 EPB positions；
- `81dea5c`：H5E 改为并发下载 → 按序拼 encrypted TS → 单 native Session 解密 → remux；
- 对应 mode switching / EPB / stream-session focused tests 已落盘。

### 2026-08-29 真实样本矩阵

| 年代 / 样本 | GUID | 实测分片 | Native NAL | Native ffmpeg error | WASM | 判定 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 2021《新闻直播间》红色游 | `8fc41c33005f48318a920e9d15243ba0` | 5 | 4,480 | 0 | 未需要 | native 通过；观察到 `01a8` family |
| 2018《历史转折中的邓小平》第 1 集 | `ef2366a50f644f00918966e786cefc76` | 10 | 10,004 | 1,225 | 1 | native 明确失败；fallback 必要 |
| 2026《CCTV空中剧院》越剧《春香传》 | `043732250b304099a3e8ee245400bc89` | 10 | 10,388 | 0 | 未需要 | 当前样本通过，不扩大为全覆盖承诺 |

2018 同一批分片 native 1,225 条错误、WASM 仅 1 条，差距足以确认是 native 解密差异，不是一般截断噪声。因此当前**禁止删除 WASM/vendor**。

### 本轮针对审计缺口的修正

- 修正错误 test fixture：mock decrypt 现在保持 TS 输入/输出等长，不再与生产不变量冲突；
- 新增 `adapters/cctv_hls.py`：统一解析 HLS master 的 `BANDWIDTH`，在 `getHttpVideoInfo` 已带 `maxbr=2048` 的 bounded master 内选择最高档，不再误拿首个 450 档；
- clear HLS master 与 H5E master 复用同一 selector，clear HLS 不再直接 `FEATURE_NOT_SUPPORTED`；
- relative / root-relative / absolute HLS child URI 统一通过 `urljoin` 解析；
- WASM fallback 从分组并行改为**整个 ordered stream 一个 worker Session**，避免 type25/new-mode 状态跨 worker 丢失；
- 新增 `scripts/diagnose_cctv_h5e_divergence.py`：输入同一 encrypted TS 与 WASM TS，现场跑 Python native，并定位第一个 native/WASM NAL 字节差异，输出 NAL type/header、new-mode、stride、flip mask、EPB、首个差异位置和 hash；
- Windows Release workflow 新增 CCTV focused pytest，并使用最终安装进产品 venv 的包执行。

## Acceptance criteria

- [x] AC-01：type25 marker 能开启 new-mode；前置 classic、后置 type1/type5 使用对应 native transform；
- [x] AC-02：type1/type5 RBSP grid 使用原始 EPB positions；
- [x] AC-03：native H5E 对完整 ordered encrypted TS 使用一个 Session；
- [x] AC-04：native 明确验证 NAL count > 0 且 TS 总长度不变；
- [x] AC-05：HLS master 能选择 bounded master 的最高 BANDWIDTH，clear HLS 与 H5E 共用选择逻辑；
- [x] AC-06：WASM fallback 对完整 ordered stream 使用一个 Session，不按组切断协议状态；
- [ ] AC-07：最新 installed-package CCTV focused pytest 全绿。前一轮实际结果为 41 passed / 1 failed，唯一失败来自新 step 未刷新 winget 安装后的 ffmpeg PATH；`4b63ca6` 已修 CI 环境，重跑中；
- [ ] AC-08：2018 `ef2366...` native/WASM 首个 NAL divergence 已定位并有针对性修复；
- [ ] AC-09：修复后重跑同一 2018 10 分片，native full-decode error 降到与 WASM 同量级，并补一个 2019/2020 左右旧样本防止单样本过拟合；
- [x] AC-10：当前真实反例存在，因此明确保留 JS/WASM/vendor；只有 AC-08/09 真正通过后才能重新讨论删除。

## Expected change surface

允许：

- `adapters/cctv_h5e.py`：由 2018 byte-level divergence 直接证明的协议修正；
- `adapters/cctv_download.py` / `cctv_hls.py`：HLS 与 stream 生命周期修正；
- CCTV focused tests；
- `scripts/diagnose_cctv_h5e_divergence.py`；
- 本计划。

默认不改：

- Skill；
- MCP public tool schema；
- 其他 Adapter；
- Job / SessionStore；
- Generic Web / Archive。

只有 AC-08/09 真实通过后才允许：

- 删除 `vendor/cctv-h5e/runtime`；
- 删除 Node/WASM fallback；
- 删除相应 package-data/runtime 文档。

## Steps

- [x] completed：研究历史 CCTV 下载器与当前 native H5E 开源实现；
- [x] completed：恢复 type25/new-mode、EPB、完整 TS 单 Session；
- [x] completed：执行 2021 / 2018 / 2026 有界真实 smoke，并确认 2018 native 反例；
- [x] completed：修测试 fixture、450/2000 variant、clear-HLS master、HLS URI 和 WASM Session 生命周期；
- [x] completed：增加 native/WASM NAL divergence 诊断脚本；
- [ ] in_progress：等待最新 installed-package focused CI 结果；取得 2018 同一 encrypted/WASM TS 后运行 divergence 诊断；
- [ ] pending：只按首个真实 divergence 修 native；
- [ ] pending：重跑 2018 + 一个额外旧年代样本；
- [ ] pending：通过真实门槛后再决定是否删除 fallback；否则保留并结束本计划；
- [ ] pending：0078 收口后恢复 0077 Real User Journey。

## Validation record

| Validation | Result | Proves | Does NOT prove |
| --- | --- | --- | --- |
| 2021 bounded H5E | native 0 ffmpeg errors | 该 `01a8` 样本可 native | 所有旧 H5E |
| 2018 bounded H5E | native 1225 / WASM 1 | 存在真实 native gap | gap 的具体算法原因 |
| 2026 bounded H5E | native 0 | 当前单样本可用 | 2025-08 后全面覆盖 |
| installed-package focused CI（旧轮次） | 41 passed / 1 env failure | fixture/HLS tests 未暴露逻辑失败 | 最新 runtime 全绿 |
| Windows packaged install（此前） | success | clean package 能安装并启动 MCP | H5E 算法正确 |

## Current checkpoint

```text
Public MCP surface changed?: no
New runtime semantic state?: no
Native H5E materially improved?: yes
Known old-H5E native counterexample?: yes, 2018 ef2366...
HLS 450/2000 bug fixed in code?: yes
Clear-HLS master supported in code?: yes
WASM stream state preserved?: yes, one Session
Latest installed-package focused pytest green?: pending CI
2018 byte-level divergence located?: pending raw encrypted/WASM TS pair
Safe to delete vendor now?: no
```

## Result

进行中。当前工作重点已经从“继续泛化 H5E 算法”缩小为一个明确问题：用 2018 `ef2366...` 的同一份 encrypted/WASM TS 找到第一个 native/WASM NAL divergence，并只修该真实差异。目录清理不是当前验收目标。
