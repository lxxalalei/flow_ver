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

### 2026-08-29 2018 定向修复进展

- 已重新固定原审计使用的同一 450 档前 10 分片：`4,524,032 bytes`、`10,004 NAL`；fixture 只保存在 `.openclaw-test/`，不提交媒体数据；
- 首个真实差异位于 new-mode type1 NAL `41 9e 41` 的 byte 64：native 使用 flip mask `0x5e86`，WASM oracle 唯一匹配 `0x7e86`；
- 对 2018 / 2021 / 2026 三组真实流共 `65,257` 个可直接对照 type1 cell 校准后，step 13 应由 header byte 1 bit 2 决定；新规则 0 个 cell 不匹配，旧规则 11,840 个不匹配；
- 修复后原 2018 450 档 10 分片 native MP4 full-decode 为 **0 error**，WASM reference 为 **1 error**；原 1,225-error 反例已消失；
- 新增 2020《新闻联播》`6e97ca203f2845069c5fbb06cab375ce` 2000 档前 5 分片验证，native / WASM 均为 **0 error**；2021 / 2026 既有样本重跑 native 仍为 **0 error**；
- 同时发现真实 CCTV master 属性带空格（`PROGRAM-ID=1, BANDWIDTH=...`），已修 selector 并补真实格式测试；否则当前代码无法进入 2018 最高档变体；
- 选择器修复后，2018 当前实际最高档为 1200。该档前 10 分片 native 仍有 **334 errors**，WASM 为 **2 errors**，首差异位于 type25 前 classic EPB/尾部填充边界；尝试过的 direct/RBSP/全量或有界 EPB 猜测均未达到门槛，未写入生产代码；
- 当前结论：450 档原反例和 type1 step-13 已修，但最高档 classic 反例仍存在，因此继续保留 WASM/vendor。

### 本轮针对审计缺口的修正

- 修正错误 test fixture：mock decrypt 现在保持 TS 输入/输出等长，不再与生产不变量冲突；
- 新增 `adapters/cctv_hls.py`：统一解析 HLS master 的 `BANDWIDTH`，在 `getHttpVideoInfo` 已带 `maxbr` 上限的 bounded master 内选择最高档，不再误拿首个 450 档；
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
- [x] AC-08：2018 `ef2366...` 原 450 档首个 NAL divergence 已定位为 type1 step-13，并有针对性修复；
- [x] AC-09：同一 2018 450 档 10 分片 native 从 1,225 errors 降为 0；新增 2020 2000 档 5 分片 native / WASM 均为 0；2021 / 2026 native 仍为 0；
- [x] AC-10：当前真实反例存在，因此明确保留 JS/WASM/vendor；只有 AC-08/09/11 全部通过后才能重新讨论删除。
- [ ] AC-11：当前实际选择的 2018 1200 档 classic EPB/尾部填充差异修复，native 334 errors 降至与 WASM 2 同量级；通过前不得删除 fallback。

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

只有 AC-08/09/11 真实通过后才允许：

- 删除 `vendor/cctv-h5e/runtime`；
- 删除 Node/WASM fallback；
- 删除相应 package-data/runtime 文档。

## Steps

- [x] completed：研究历史 CCTV 下载器与当前 native H5E 开源实现；
- [x] completed：恢复 type25/new-mode、EPB、完整 TS 单 Session；
- [x] completed：执行 2021 / 2018 / 2026 有界真实 smoke，并确认 2018 native 反例；
- [x] completed：修测试 fixture、450/2000 variant、clear-HLS master、HLS URI 和 WASM Session 生命周期；
- [x] completed：增加 native/WASM NAL divergence 诊断脚本；
- [x] completed：取得 2018 原 450 档同一 encrypted/WASM TS 并定位、修复 type1 step-13；
- [x] completed：重跑 2018 450 + 2020 + 2021 + 2026 有界真实样本；
- [ ] in_progress：定位 2018 当前最高 1200 档 classic EPB/尾部填充边界；
- [ ] pending：通过真实门槛后再决定是否删除 fallback；否则保留并结束本计划；
- [ ] pending：0078 收口后恢复 0077 Real User Journey。

## Validation record

| Validation | Result | Proves | Does NOT prove |
| --- | --- | --- | --- |
| 2021 bounded H5E | native 0 ffmpeg errors | 该 `01a8` 样本可 native | 所有旧 H5E |
| 2018 bounded H5E | native 1225 / WASM 1 | 存在真实 native gap | gap 的具体算法原因 |
| 2018 450 定向修复后 | native 0 / WASM 1 | 原反例已由 step-13 修复 | 2018 所有码率 |
| 2018 1200 当前最高档 | native 334 / WASM 2 | 仍有 classic EPB/尾部填充反例 | 可安全删除 fallback |
| 2020 2000 bounded H5E | native 0 / WASM 0 | 中间年代额外样本通过 | 全部 2019/2020 视频 |
| 2026 bounded H5E | native 0 | 当前单样本可用 | 2025-08 后全面覆盖 |
| CCTV focused pytest | 44 passed | type1 mask、spaced master、HLS/session 聚焦回归通过 | installed-package / Windows CI |
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
2018 original 450 divergence fixed?: yes, native 0 / WASM 1
2018 selected 1200 native healthy?: no, native 334 / WASM 2
Safe to delete vendor now?: no
```

## Result

进行中。2018 原 450 档 type1 step-13 反例已经修复并跨 2020/2021/2026 样本复核；新的唯一阻塞是 selector 修正后实际会选择的 1200 档仍存在 classic EPB/尾部填充差异。未达到该真实门槛前不删除 WASM/vendor，目录清理不是当前验收目标。
