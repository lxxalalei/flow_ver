# 0078 — CCTV 旧 H5E 原生解密收口

- 状态：in_progress
- 创建日期：2026-08-29
- 完成日期：未完成
- 范围：`mcp/education-resources/src/education_resource_mcp/adapters/cctv_h5e.py`、`cctv_download.py`、对应 CCTV focused tests；公共 MCP Tool 面不变

## Objective

让 CCTV 旧版（重点为 2025-08 之前）`hls_h5e` 视频优先由 Python native 路径稳定完成解密和 MP4 交付，并用真实老视频证明 native 路径足以覆盖当前已知 H5E 形态；只有达到真实证据门槛后才删除现有 JS/WASM fallback 与 `vendor/cctv-h5e`。

## Non-goals

- 不宣称解决 2025-08 之后 CCTV 新加密方案；
- 不新增 MCP Tool、平台或 Agent 语义状态；
- 不为了去掉 `vendor` 而提前删除仍有真实兜底价值的 WASM；
- 不重写整个 CCTV Search/Expand/Inspect；
- 不引入新的下载框架、crypto framework 或 provider abstraction；
- 不用 mock/unit 结果替代真实 H5E 视频解码证据。

## Business invariants

- 普通 clear HLS / MP4 继续直接下载，不经过 H5E 解密；
- H5E 使用 `getHttpVideoInfo` 返回的 per-video `hls_h5e_url` 优先；
- H5E protocol mode 由真实 NAL marker 驱动：type25 开启 new-mode，不靠猜测或双路盲解；
- HLS 分片可以并发下载，但解密语义属于按顺序重建后的完整 TS stream；
- TS 总字节长度在 native decrypt 前后保持一致，PES 缩短通过 adaptation-field stuffing 吸收；
- native 失败必须真实失败；当前阶段仍允许已存在的 WASM fallback；
- `cctv_h5e.py` 当前已有 2021 样本/官方 worker 对照证据的行为（特别是 classic `o+80` guard）不因上游当前实现不同而无证据覆盖。

## Current architecture / evidence

历史 0069 已有真实样本：

- 《典籍里的中国》20210807，575 个 H5E 分片；
- 修复 TEA key pairing、type1 stride index、classic `o+80` 后，native 与官方 worker 244/250 个 type1/5 NAL 字节级一致；
- 剩余 6 个 `01a8` family NAL 当时未复现，故 WASM 保留。

2026-08-29 重新审查开源实现后新增事实：

- 2021 `videodl` 时代 CCTV 可从 `getHttpVideoInfo` 的 `chapters*` 取直接 MP4，当前这些 URL 对旧节目普遍已为空；
- `DevLARLEY/cctv-decrypt` 证明 classic TEA 可纯 Python 实现；
- `letr007/CCTVVideoDownloader` 当前已具备 pure native H5E：type25/new-mode、type1/type5、RBSP/EPB、TS/PES rebuild；
- 其 native worker 对完整 TS 创建一个 `Session`，不是每个 HLS segment 新建 Session；
- 当前上游已补 `01a8`、`61`、slice-header family flip masks，以及 type1/type5 RBSP/EPB 处理。

本轮已完成：

- `795fca1`：恢复 type25 → new-mode 的 Python Session dispatch；
- `9d4e488`：增加 mode switching focused tests；
- `b37b78e`：type1/type5 使用变换前原始 EPB positions；
- `81dea5c`：H5E 改为并发下载 → 顺序拼 encrypted TS → 单 Session 整流解密 → remux；
- `d233f6b`：增加完整 stream 单次 decrypt 测试；
- `3d7a431`：增加“解密后新产生 00 00 03 不应被误删”的 EPB tests；
- `81dea5c` 对应 Windows packaged install smoke 已全绿（该 CI 不运行 pytest）。

## Expected change surface

允许：

- `adapters/cctv_h5e.py`：协议级 native 修正；
- `adapters/cctv_download.py`：H5E stream 生命周期/真实下载修正；
- `tests/test_cctv_h5e_*.py`、必要的现有 CCTV focused tests；
- 本计划和与当前实现直接相关的事实文档。

只有真实 native 验收通过后才允许：

- 删除 `vendor/cctv-h5e/runtime`；
- 删除 Node/WASM fallback；
- 删除 pyproject 的 CCTV vendor package-data；
- 更新运行依赖/README 中相关说明。

默认不改：

- Skill；
- MCP public tool schema；
- 其他 Adapter；
- Job/SessionStore；
- Generic Web / archive。

## Acceptance criteria

- [x] AC-01：type25 marker 能在 Python Session 内开启 new-mode；其前 classic、其后 type1/type5 使用对应 native transform；
- [x] AC-02：type1/type5 RBSP grid 使用原始 EPB positions，解密后新产生的 `00 00 03` 不被误删；
- [x] AC-03：native H5E 不再按 segment 创建 fresh Session，而是对按播放列表顺序重建的完整 encrypted TS 只解密一次；
- [x] AC-04：native decrypt 明确验证 NAL count > 0 且 TS 总长度不变；
- [x] AC-05：包含上述行为的 focused regression tests 已落盘；
- [x] AC-06：包含当前 native 源码的 Windows packaged install / MCP runtime smoke 全绿；
- [ ] AC-07：实际运行 focused pytest，并记录真实结果；
- [ ] AC-08：至少验证 2 个旧 H5E 年代样本（至少一个 2021 或更早），native 产物 ffmpeg full decode 为 0 error 或有明确可解释的非解密错误；
- [ ] AC-09：重新验证历史 `01a8` family gap；若当前 flip mask 已解决，应有真实样本证据，而不是只根据上游代码判断；
- [ ] AC-10：在多样旧样本上 native 足以替代 fallback 后，才删除 JS/WASM/vendor；若真实样本仍存在 native gap，则保留 fallback 并明确记录原因，不为了目录整洁牺牲能力。

## Validation scope

### Focused code validation

- Session mode dispatch；
- classic existing roundtrip；
- type1/type5 EPB semantics；
- single stream-wide decrypt lifecycle；
- TS/PES residual/stuffing correctness。

### Real H5E validation

推荐至少：

- 2021 老 H5E：历史样本《典籍里的中国》20210807，如能恢复完整 GUID；
- 2021 公开 GUID `8fc41c33005f48318a920e9d15243ba0`；
- 2019/更早旧节目样本；
- 可选 2023/2025-08 前样本用于扩大年代覆盖。

每个样本记录：

```text
GUID / title / date
hls_h5e_url resolved?
segment count
native decrypt NAL count
ffmpeg remux result
ffmpeg -v error full decode error count
WASM comparison needed?
observed NAL header families
```

### Delete-fallback gate

只有 AC-08/09 给出真实覆盖证据后，才进入删除阶段。删除本身不是当前目标的先验要求。

## Steps

- [x] completed：重新研究 2021 下载器与当前 native H5E 开源实现；
- [x] completed：恢复 Python type25/new-mode dispatch 与新 header family 规则；
- [x] completed：修正 original EPB semantics；
- [x] completed：H5E 生命周期改为完整 TS 单 Session；
- [ ] in_progress：完成 focused test / TS-PES 边界复核；
- [ ] pending：真实旧 H5E 样本 native smoke；
- [ ] pending：根据真实样本决定是否删除 WASM/vendor；
- [ ] pending：若删除成功，更新依赖/文档并恢复 0077。

## Current checkpoint

```text
Public MCP surface changed?: no
New runtime state/source of truth?: no
New fallback added?: no
Existing WASM fallback removed?: no
Native H5E mode coverage improved?: yes
Packaged runtime imports/installs?: yes
Focused pytest actually run?: not yet
Real old-H5E native smoke after these changes?: not yet
Safe to delete vendor now?: no
```

## Result

进行中。当前已经从“classic-only + 每分片 fresh Session”修正为协议 marker 驱动、完整 TS 单 Session 的 native H5E 实现；下一门槛是真实旧视频解码证据，而不是继续堆算法或立即删除 fallback。
