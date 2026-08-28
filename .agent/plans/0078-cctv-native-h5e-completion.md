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
- [x] AC-07：已实际运行 focused pytest：36 passed、1 failed；唯一失败是 test fixture 将 27 字节输入伪造成 17 字节输出，生产代码正确触发 TS 长度不变约束，测试需修正；
- [ ] AC-08：至少验证 2 个旧 H5E 年代样本（至少一个 2021 或更早），native 产物 ffmpeg full decode 为 0 error 或有明确可解释的非解密错误；
- [x] AC-09：2021 与 2026 真实 H5E 样本均观察到 `01a8` header family，测试窗口 native ffmpeg full decode 为 0 error；但这不代表其他旧 slice-header family 已覆盖；
- [x] AC-10：2018 真实样本 native 产生 1225 条解码错误、同数据 WASM 仅 1 条，已据此决定保留 JS/WASM/vendor，不进入删除阶段。

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
- [x] completed：执行 focused test / TS-PES 边界复核并记录唯一 fixture 失败；
- [x] completed：执行多年代有界真实 H5E native smoke 与 2018 WASM 对照；
- [x] completed：根据真实反例决定保留 WASM/vendor；
- [ ] in_progress：修复 2018 slice-header native 差异、测试 fixture 与 HLS 画质选择缺口后重新验收；
- [ ] pending：只有 native 真实门槛通过后才允许删除 fallback，并恢复 0077。

## Current checkpoint

```text
Public MCP surface changed?: no
New runtime state/source of truth?: no
New fallback added?: no
Existing WASM fallback removed?: no
Native H5E mode coverage improved?: yes
Packaged runtime imports/installs?: yes
Focused pytest actually run?: yes; 36 passed, 1 invalid-fixture failure
Real old-H5E native smoke after these changes?: yes; 2021 pass, 2018 fail
Safe to delete vendor now?: no
```

## 2026-08-29 Luna 独立审计与真实样本记录

### 审计范围

用户要求调用 Luna 模型验证“当前实现是否覆盖央视页面所有视频”。`luna_worker`
以只读方式检查 CCTV Search / Expand / Import / Inspect / Download、native H5E、
static WASM fallback、Windows/runtime packaging 与 CCTV focused tests；主 Agent
独立复跑 focused tests，并对关键年代样本执行有界真实下载、native/WASM 对照和
ffmpeg full decode。审计没有修改生产代码、测试或运行时文件。

### Focused tests

实际命令：

```text
cd mcp/education-resources
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_cctv_platform.py \
  tests/test_cctv_h5e_modes.py \
  tests/test_cctv_h5e_stream_session.py
```

结果：`36 passed, 1 failed`。失败项为
`test_native_h5e_decrypts_joined_stream_once`：fixture 拼接的 encrypted input 为
27 字节，mock decrypt 却返回 17 字节 `plain-full-stream`；生产实现按业务不变量
拒绝 TS 总长度变化。该失败是待修测试 fixture，不是放宽生产约束的理由。

### 真实 H5E 样本矩阵

所有样本只取公开 H5E 的有界分片；不下载整部版权视频。`ffmpeg error` 是 remux
后的 MP4 执行 `ffmpeg -v error -i ... -f null` 的非空错误行数。

| 年代 / 样本 | GUID | 播放列表 / 实测分片 | 输入字节 | Native NAL | Native ffmpeg error | WASM 对照 | 判定 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2021《新闻直播间》红色游 | `8fc41c33005f48318a920e9d15243ba0` | 5 / 5 | 2,691,972 | 4,480 | 0 | 未需要 | native 通过；观察到 `01a8` family |
| 2018《历史转折中的邓小平》第 1 集 | `ef2366a50f644f00918966e786cefc76` | 264 / 10 | 4,524,032 | 10,004 | 1,225 | 1 | native 确定失败；fallback 有效 |
| 2026《CCTV空中剧院》越剧《春香传》 | `043732250b304099a3e8ee245400bc89` | 827 / 10 | 6,154,556 | 10,388 | 0 | 未需要 | 当前样本 native 通过；不扩大为 2025-08 后全覆盖承诺 |

2018 同一批 10 个分片由 static WASM 解密后只剩 1 条错误，而 native 为 1,225
条，差距远大于截断片段常见的 SPS/DTS 噪声，因此这是 native 解密差异，不是
网络失败或简单截断误报。现有 `HEALTH_ERROR_THRESHOLD=100` 会拒绝 native 并
接受 WASM，故当前整体用户链仍可兜底，但 native 尚不能替代 fallback。

### 页面与路由覆盖抽样

Luna 对 64 个公开搜索得到的唯一页面做只读 manifest/路由审计：61 个同时返回
HLS/H5E/ENC，3 个状态不可用且没有任何流；另验证 `djldzg` 栏目 API 返回 11
个条目。结果支持 `tv.cctv.com/YYYY/MM/DD/VID*.shtml`、`/lm/...` 栏目和页面内
多 episode 系列的主要路径，但不支持“央视所有页面均覆盖”的结论：

- `local.cctv.com`、`sports.cctv.com`、`xwzs.cctv.com`、`v.cctv.com` 的直接 URL
  导入可能保持 generic，而不是恢复 CCTV 身份；
- `/special/...` 等特殊页没有专门容器路由；
- 来源状态为 unavailable、没有真实流的视频只能显式失败，不能由解密器补出内容。

### 已确认的实现/契约缺口

1. `_fetch_media_m3u8` docstring 声称选择 2000 档，实际取 master playlist 第一个
   非注释 variant；公开 master 通常按 `450/850/1200/2000` 排列，真实执行选择
   了 450，与 `TOOLS.md` 的 2000 档/720P 说明不一致。
2. clear HLS 若返回多码率 master，`download_stream_native` 当前直接返回
   `FEATURE_NOT_SUPPORTED`，尚未验证 HLS-only 页面闭环。
3. native 默认只处理 video PID `0x100`；其他 PID 尚无真实覆盖证据。
4. 当前 H5E 路径先拼完整 encrypted TS，再以 `read_bytes()` 和 bytearray/bytes
   副本整体解密；超长节目存在显著峰值内存风险。
5. `enc_url` 没有成为独立下载路线；相对/绝对 HLS segment URL 形态的覆盖仍有限。
6. 当前计划本来就明确不承诺 2025-08 后新加密；单个 2026 样本通过不能改写该边界。

### Release / fallback 判定

```text
Native covers all known CCTV page videos?: no
Main tv.cctv.com H5E path materially improved?: yes
Known native counterexample?: yes, 2018 ef2366...
Can static WASM / Node fallback be deleted?: no
Can 2000/720P quality contract be claimed?: no, selector currently chooses first/450
Can "all CCTV pages" be claimed?: no, host/special-page/HLS/PID evidence gaps remain
```

## Result

进行中。实现已经从“classic-only + 每分片 fresh Session”修正为协议 marker 驱动、完整 TS 单 Session，但 2026-08-29 真实审计证明 native 尚未覆盖全部旧 H5E：2018 样本仍需 WASM。下一步不是删除 fallback，而是修复 2018 slice-header 差异、450/2000 variant 选择和错误 test fixture，再重复相同真实矩阵。
