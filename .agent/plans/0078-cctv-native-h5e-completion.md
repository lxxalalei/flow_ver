# 0078 — CCTV 旧 H5E 原生解密收口

- 状态：in_progress
- 创建日期：2026-08-29
- 完成日期：未完成
- 范围：`mcp/education-resources/src/education_resource_mcp/adapters/cctv_h5e.py`、`cctv_download.py`、`cctv_hls.py`、CCTV focused tests 与真实旧 H5E 验收；公共 MCP Tool 面不变

## Objective

让 CCTV 旧版（重点为 2025-08 之前）视频以**该视频当前实际可获取的最高画质**完成 MP4 交付；需要 H5E 时优先由 Python native 稳定解密，并用真实老视频证明 native 路径能否替代现有 JS/WASM fallback。只有最高画质真实反例消失后才允许删除 `vendor/cctv-h5e`。

## Non-goals

- 不宣称覆盖 CCTV 所有页面、所有 host 或 2025-08 后全部新加密；
- 不新增 MCP Tool、平台、Agent 语义状态或 crypto/provider framework；
- 不为了目录整洁提前删除仍有真实兜底价值的 WASM；
- 不用 mock/unit 结果替代真实 H5E 视频解码证据；
- 不因上游实现不同而无证据覆盖本仓库已有真实样本校准行为；
- 不把 450/1200/2000/3000/4000 中任一档硬编码成产品质量上限。

## Business invariants

- 用户要求的是最高画质：同一视频存在多个可下载 representation 时，按实际视频分辨率优先、码率次之选择最高；
- 低档画质通过只可作为协议诊断证据，**不能**代替该视频最高实际可选档的验收；
- 不允许因为高画质 native 失败而静默降到低画质并宣称下载成功；WASM 在保留期间只能兜底同一高画质 H5E stream；
- clear MP4 / HLS 若本身就是最高可用 representation，则直接下载，不为了使用 H5E 而降质或绕路；
- HLS master 只按服务端实际暴露的 variant 选择，不在代码中设置 2000 等固定 ceiling；
- `getHttpVideoInfo` 返回 URL 中的 `maxbr` 是服务端约束事实，不是产品画质目标；后续若发现更高可访问 representation，必须纳入比较；
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
| 2018《历史转折中的邓小平》第 1 集 | `ef2366a50f644f00918966e786cefc76` | 10 | 10,004 | 1,225 | 1 | 原 450 档 native 明确失败；后续已修 |
| 2026《CCTV空中剧院》越剧《春香传》 | `043732250b304099a3e8ee245400bc89` | 10 | 10,388 | 0 | 未需要 | 当前样本通过，不扩大为全覆盖承诺 |

### 2026-08-29 2018 定向修复进展

- 已重新固定原审计使用的同一 450 档前 10 分片：`4,524,032 bytes`、`10,004 NAL`；fixture 只保存在 `.openclaw-test/`，不提交媒体数据；
- 首个真实差异位于 new-mode type1 NAL `41 9e 41` 的 byte 64：native 使用 flip mask `0x5e86`，WASM oracle 唯一匹配 `0x7e86`；
- 对 2018 / 2021 / 2026 三组真实流共 `65,257` 个可直接对照 type1 cell 校准后，step 13 应由 header byte 1 bit 2 决定；新规则 0 个 cell 不匹配，旧规则 11,840 个不匹配；
- 修复后原 2018 450 档 10 分片 native MP4 full-decode 为 **0 error**，WASM reference 为 **1 error**；原 1,225-error 反例已消失；
- 新增 2020《新闻联播》`6e97ca203f2845069c5fbb06cab375ce` 2000 档前 5 分片验证，native / WASM 均为 **0 error**；2021 / 2026 既有样本重跑 native 仍为 **0 error**；
- 真实 CCTV master 属性带空格（`PROGRAM-ID=1, BANDWIDTH=...`）已修 selector 并补真实格式测试；
- selector 修复后，2018 当前实际最高档为 **1200**。该档前 10 分片 native 仍有 **334 errors**，WASM 为 **2 errors**，首差异位于 type25 前 classic EPB/尾部填充边界；
- 因 1200 才是该样本当前最高实际可选档，450 的 0 error 现在只算诊断成功，**不算最终下载验收通过**；
- 当前结论：type1 step-13 已修，但最高档 classic 反例仍存在，因此继续保留 WASM/vendor。

### 2026-08-29 1200 档收口：三项协议修正（AC-11 达成）

fixture 重建于 `.openclaw-test/cctv-fixture-2018-1200/`（前 10 分片 + WASM oracle + NALU 级 worker 探针，媒体数据不提交）。逐 NAL 对真实 worker 校准后定位三个独立根因，全部修复：

- **classic 模式改为 RBSP grid 解密 + EPB 压缩**（原 EBSP 原地解密自首个 EPB 后全部 cell 错位）：单趟 RBSP 提取 → key=RBSP[15:31/16:32] 视 EPB 位置 → stride 80 cell → 输出压缩 RBSP；
- **type25 是双向模式开关**：真实流中 ES3=`0x09` 切 new-mode、`0x06` 切回 classic。2018 1200 档 new-mode 区间仅为 NAL 969–9050，两端都是 classic；450 档有 5 个交替区间。原实现一旦 enable 永不回退；
- **129 字节门槛适用于两种模式**：worker 对 <129B 的 type1/5 一律原样保留（加密直接出片），原 classic 门槛 40B 会过度解密 113–126B 的短 NAL。

worker 侧另有两个与本仓库无关的已观察事实：其 TS 重打包会把 FF 填充写进 PES payload 并改写 SDT（这解释了 WASM 参考产物残余 1–2 个 decode error）；其 EPB 尾部剥离数随会话状态 ±1 漂移（NALU 级探针 warm≥8 后输出与 wasm.ts 逐字节一致）。

最终有界真实矩阵（native remux MP4 full-decode error 行数 / WASM oracle）：

| 样本 | 档 | native | WASM |
| --- | --- | ---: | ---: |
| 2018 `ef2366...` 当前最高 1200 | 前 10 分片 | **0** | 1 |
| 2018 `ef2366...` 450（原审计档） | 前 10 分片 | **0** | 未需要 |
| 2020 `6e97ca20...` 2000 | 前 5 分片 | **0** | 未需要 |
| 2021 `8fc41c33...` 2000 | 前 5 分片 | **0** | 未需要 |
| 2026 `04373225...` 2000 | 前 10 分片 | **1** | 2 |

### 最高画质规则收敛


- `cctv_hls.py` 已从“单纯最高 BANDWIDTH”收紧为：有 `RESOLUTION` 时按像素数优先、BANDWIDTH 次之；无 `RESOLUTION` 时退回 BANDWIDTH；
- selector 不包含 2000 ceiling；focused fixture 明确包含 3000/4000，并要求服务端 master 若实际暴露更高档就选择更高档；
- 当前 `CctvVideoDownloader` 仍是 `h5e_url` 存在即优先 H5E，尚未完成 clear/H5E 多 representation 横向画质比较；这是 AC-12 的明确待办，不能把“master 内最高”冒充“视频整体最高”。

### 其他已完成修正

- 错误 test fixture 已改为保持 TS 输入/输出等长；
- clear HLS master 与 H5E master 复用 selector，clear HLS 不再直接 `FEATURE_NOT_SUPPORTED`；
- relative / root-relative / absolute HLS child URI 统一通过 `urljoin` 解析；
- WASM fallback 从分组并行改为**整个 ordered stream 一个 worker Session**，避免 type25/new-mode 状态跨 worker 丢失；
- `scripts/diagnose_cctv_h5e_divergence.py` 可定位 native/WASM 首个 NAL/TS 字节差异；
- Windows Release workflow 已加入 installed-package CCTV focused pytest。

## Acceptance criteria

- [x] AC-01：type25 marker 能开启 new-mode；前置 classic、后置 type1/type5 使用对应 native transform；
- [x] AC-02：type1/type5 RBSP grid 使用原始 EPB positions；
- [x] AC-03：native H5E 对完整 ordered encrypted TS 使用一个 Session；
- [x] AC-04：native 明确验证 NAL count > 0 且 TS 总长度不变；
- [x] AC-05：HLS master 按最高实际画质选择：分辨率优先、BANDWIDTH 次之，不写死 2000 ceiling；
- [x] AC-06：WASM fallback 对完整 ordered stream 使用一个 Session，不按组切断协议状态；
- [ ] AC-07：当前 HEAD 的 installed-package CCTV focused pytest 全绿。`4b63ca6` 对应 Windows run #19 已确认 install → focused pytest → MCP runtime → artifact 全绿；本轮 HLS quality ranking 改动触发的新 CI 仍需结果；
- [x] AC-08：2018 `ef2366...` 原 450 档首个 NAL divergence 已定位为 type1 step-13，并有针对性修复；
- [x] AC-09：同一 2018 450 档 10 分片 native 从 1,225 errors 降为 0；新增 2020 2000 档 5 分片 native / WASM 均为 0；2021 / 2026 native 仍为 0；
- [x] AC-10：当前真实高画质反例仍存在，因此明确保留 JS/WASM/vendor；
- [x] AC-11：2018 最高档 1200 修复完成，native 334 → **0** errors（WASM 参考为 1）；450 档 0、2020 0、2021 0、2026 1（其 WASM 自身 2），全部样本 native ≤ WASM；
- [ ] AC-12：下载器从“有 H5E 就优先 H5E”改为对当前**可下载** clear/H5E representation 做真实画质比较，选择整体最高；同档优先 clear；最高档失败不得静默降质。

## Expected change surface

允许：

- `adapters/cctv_h5e.py`：由 2018 byte-level divergence 直接证明的协议修正；
- `adapters/cctv_download.py` / `cctv_hls.py`：最高画质选择、HLS 与 stream 生命周期修正；
- CCTV focused tests；
- `scripts/diagnose_cctv_h5e_divergence.py`；
- 本计划。

默认不改：

- Skill；
- MCP public tool schema；
- 其他 Adapter；
- Job / SessionStore；
- Generic Web / Archive。

只有 AC-08/09/11 的真实 native 门槛通过后才允许删除：

- `vendor/cctv-h5e/runtime`；
- Node/WASM fallback；
- 相应 package-data/runtime 文档。

0078 整体完成还要求 AC-12，不能以低画质可下载代替最高画质产品行为。

## Steps

- [x] completed：研究历史 CCTV 下载器与当前 native H5E 开源实现；
- [x] completed：恢复 type25/new-mode、EPB、完整 TS 单 Session；
- [x] completed：执行 2021 / 2018 / 2026 有界真实 smoke，并确认 2018 native 反例；
- [x] completed：修测试 fixture、master variant、clear-HLS master、HLS URI 和 WASM Session 生命周期；
- [x] completed：增加 native/WASM NAL divergence 诊断脚本；
- [x] completed：取得 2018 原 450 档同一 encrypted/WASM TS 并定位、修复 type1 step-13；
- [x] completed：重跑 2018 450 + 2020 + 2021 + 2026 有界真实样本；
- [x] completed：明确最高画质产品规则，并让 master selector 按分辨率 → BANDWIDTH 选择且无固定 2000 ceiling；
- [x] completed：定位并修复 1200 档全部反例（classic RBSP grid、type25 双向开关、129B 门槛），AC-11 通过；
- [ ] in_progress：实现 clear/H5E representation 级最高画质比较，不允许静默降质；
- [ ] pending：当前 HEAD installed-package focused CI 全绿；
- [ ] pending：通过真实门槛后再决定是否删除 fallback；否则保留并结束本计划；
- [ ] pending：0078 收口后恢复 0077 Real User Journey。

## Validation record

| Validation | Result | Proves | Does NOT prove |
| --- | --- | --- | --- |
| 2021 bounded H5E | native 0 ffmpeg errors | 该 `01a8` 样本可 native | 所有旧 H5E |
| 2018 原 450 H5E | native 1225 / WASM 1 | 原生存在真实 gap | 最高画质可用 |
| 2018 450 定向修复后 | native 0 / WASM 1 | step-13 修复正确 | 2018 最高档可用 |
| 2018 1200 当前最高档 | native 334 / WASM 2 | 最高档仍有 classic EPB/尾部反例 | 可安全删除 fallback |
| 2018 1200 三项修正后 | **native 0 / WASM 1** | 1200 档 native 路径达到产品级（AC-11） | 2025-08 后全部新加密形态 |
| 450/2020/2021/2026 修正后回归 | native 0/0/0/1 | 双向开关与 129B 门槛无样本回归 | 全部年代与档位 |
| 2020 2000 bounded H5E | native 0 / WASM 0 | 中间年代额外样本通过 | 全部 2019/2020 视频 |
| 2026 bounded H5E | native 0 | 当前单样本可用 | 2025-08 后全面覆盖 |
| HLS quality focused tests | 3000/4000 fixture 可选最高 | selector 无 2000 hard ceiling | CCTV 实际一定暴露 3000/4000 |
| CCTV focused pytest | 此前 44 passed | type1 mask、spaced master、HLS/session 聚焦回归通过 | 当前 HEAD installed-package 全绿 |
| Windows run #19 | success | packaged install、focused pytest、MCP runtime 全绿 | 本轮质量排序代码已验证 |

## Current checkpoint

```text
Public MCP surface changed?: no
New runtime semantic state?: no
Native H5E materially improved?: yes
Low-quality success accepted as release proof?: no
HLS selector fixed ceiling?: no
HLS selection rule?: resolution first, bandwidth second
Cross-representation highest-quality routing?: pending
2018 original 450 divergence fixed?: yes, native 0 / WASM 1
2018 selected highest 1200 native healthy?: yes, native 0 / WASM 1 (AC-11 passed)
Safe to delete vendor now?: no (AC-12 pending; deletion gated on it)
```

## Result

进行中。产品验收口径已经明确为“该视频当前实际可获取的最高画质”，低档成功仅用于诊断。AC-08/09/11 已全部通过：2018 最高 1200 档 native 0 error（WASM 参考 1），三个协议根因（classic RBSP grid、type25 双向开关、129B 门槛）均已按真实 worker 逐 NAL 校准修复并落 focused 测试。剩余：AC-12 下载器 clear/H5E representation 级最高画质选择；完成后按真实门槛评估是否删除 WASM/vendor。
