# 0078 — CCTV 旧 H5E 原生解密收口

- 状态：completed
- 创建日期：2026-08-29
- 完成日期：2026-08-30
- 范围：CCTV 最高画质选择、旧 H5E Python native 解密、focused tests、Windows installed-package 验证；公共 MCP Tool 面不变

## Objective

让 CCTV 公开单集视频以**当前可确认的最高可下载画质**完成 MP4 交付：先比较 clear/H5E 实际画质，再按所选 stream type 执行 clear 下载或 Python native H5E 解密。旧 JS/WASM/Node compatibility fallback 在真实样本门槛通过后彻底删除。

## 最终运行时行为

```text
CCTV video info
↓
collect supported clear / H5E candidates
↓
quality ranking
  1. resolution
  2. bandwidth
  3. equal quality -> clear
↓
selected highest stream
├─ clear -> native download/remux
└─ H5E  -> Python decrypt_ts -> remux
↓
ffmpeg full-decode health check
↓
success / explicit failure
```

业务不变量：

- 解密方式不参与画质排序；
- 不写死 2000 等画质 ceiling；master 若暴露 3000/4000 等更高档，按真实分辨率/码率排序；
- `maxbr` 只视为服务端请求约束，不作为候选实际码率；
- 同画质优先 clear，只为避免无意义解密，不牺牲画质；
- 最高画质失败时明确失败，不静默改下低画质，也不切另一种低画质 stream；
- H5E 分片可并发下载，但按原顺序拼接后由一个 Python Session 解完整 encrypted TS；
- H5E decrypt 前后 TS 总长度保持一致；
- CCTV 不再依赖 Node、JS worker、WASM 或 `vendor/cctv-h5e`。

## Native H5E 已验证协议修正

- type25 驱动模式切换；真实旧流中 ES3=`0x09` 进入 new-mode、`0x06` 回到 classic；
- classic 使用 RBSP grid 解密并正确处理 EPB；
- type1/type5 使用变换前原始 EPB positions；
- type1 step-13 由真实 worker/cell 对照校准为 header byte 1 bit 2；
- classic/new-mode 对短 type1/type5 使用 129-byte 最小处理门槛；
- complete ordered stream 使用一个 Session，不按 HLS segment 重置协议状态；
- 保留已有真实样本支持的 classic stride/guard 行为，不用新版上游差异覆盖本仓库实测证据。

## 真实样本证据

最终有界真实矩阵（MP4 full-decode error 行数）：

| 样本 | 实测档位 | Python native | 历史 WASM oracle |
| --- | --- | ---: | ---: |
| 2018 `ef2366...`《历史转折中的邓小平》第 1 集 | 当前最高 1200，前 10 分片 | **0** | 1 |
| 2018 `ef2366...` | 450，前 10 分片 | **0** | 未需要 |
| 2020 `6e97ca20...`《新闻联播》 | 2000，前 5 分片 | **0** | 未需要 |
| 2021 `8fc41c33...`《新闻直播间》 | 2000，前 5 分片 | **0** | 未需要 |
| 2026 `04373225...`《CCTV空中剧院》 | 2000，前 10 分片 | **1** | 2 |

2018 最高 1200 档曾为 native 334 errors，修复 classic RBSP/EPB、type25 双向切换和 129-byte 门槛后降为 0。原 450 档曾为 1,225 errors，type1 step-13 修正后也降为 0。

这些结果证明当前已知旧 H5E 真实反例已被 native 覆盖；它们不扩大成“央视所有年代、所有 host、所有未来加密形态均永久兼容”的承诺。

## 最高画质路由

`cctv_hls.py`：

- master 有 `RESOLUTION` 时按像素数优先；
- 同分辨率比较 `BANDWIDTH`；
- 无分辨率时按 `BANDWIDTH`；
- 不依赖 playlist 顺序；
- 支持 CCTV 属性逗号后带空格的真实 master 格式；
- relative / root-relative / absolute child URI 统一解析。

`CctvVideoDownloader`：

- 同时存在 clear/H5E 时先探测二者最高 representation 的真实画质；
- 只在完成画质比较后决定调用 `download_stream_native` 或 `download_h5e_native`；
- 同画质 clear 胜出；
- 两个真实候选但信息不足以证明高低时明确失败，不猜；
- 最高 stream 下载/解密/健康检查失败即真实失败，不做降质 fallback。

## WASM / vendor 删除结果

已物理删除：

- `education_resource_mcp/vendor/cctv-h5e/` 整个目录；
- static `main.js` / `worker.js`；
- 上游 TypeScript 源码、npm 元数据、worker diff/orig/test 文件；
- `download_wasm`、`resolve_wasm_m3u8`、`resolve_h5e_proj` 与相关 runtime constants；
- CCTV Node/runtime 安装检查；
- `pyproject.toml` 的 CCTV vendor package-data；
- release builder 的 CCTV vendor 白名单；
- WASM fallback 单测。

保留 `pycryptodome`，因为 Python native H5E 解密本身仍需要它。

## Release / focused test 证据

Windows `Build Windows Release` run #35（runtime commit `1d5fabd78f2bdcc4ec9f6a2f16ec10aa85ab3fc9`）结果：**success**。

- Build clean release ZIP：通过；
- release contents：通过，产物中无 `education_resource_mcp/vendor`；
- packaged install：通过；
- installed-package CCTV focused pytest：**48 passed**；
- OpenClaw Skill：ready；
- `openclaw mcp doctor education-resources --probe`：ok；
- artifact upload：通过。

体积变化：

- MCP wheel：约 `824 KB` → `271 KB`；
- Windows release artifact：约 `841 KB` → `300 KB`。

当前分支在该 runtime commit 后只追加了 smoke 文档更新，不包含新的 runtime 代码变更。

## Acceptance criteria

- [x] AC-01：type25/new-mode 与 classic dispatch 由真实流验证；
- [x] AC-02：type1/type5 EPB/RBSP 语义修正；
- [x] AC-03：完整 ordered encrypted TS 使用一个 native Session；
- [x] AC-04：native 明确验证 NAL count > 0 且 TS 总长度不变；
- [x] AC-05：master 内按分辨率优先、码率次之选择最高档，无固定 2000 ceiling；
- [x] AC-06：2018/2020/2021/2026 真实 H5E 样本完成 native 校准；
- [x] AC-07：删去 WASM/vendor 后的 installed-package CCTV focused tests 全绿（run #35，48 passed）；
- [x] AC-08：2018 原 450 档 1,225 errors → 0；
- [x] AC-09：2018 当前最高 1200 档 334 errors → 0；
- [x] AC-10：真实旧样本 native 结果达到或优于历史 WASM oracle；
- [x] AC-11：clear/H5E 跨 stream type 统一按真实画质选择整体最高，同档优先 clear；
- [x] AC-12：最高档失败不静默降质；
- [x] AC-13：Node/WASM fallback 与 `vendor/cctv-h5e` 已从 runtime、安装、release 和 focused tests 中物理删除。

## Non-goals / remaining boundaries

- 不宣称覆盖 CCTV 所有页面、所有 CDN host 或未来新增的未知加密协议；
- 本计划验证的是当前 downloader 已支持的 clear/H5E stream；若未来出现新的 stream 字段/协议，需要基于真实样本单独实现，而不是恢复 WASM；
- 不因为未来单个视频失败重新加入笼统 fallback；先定位真实协议或页面变化。

## Conclusion

0078 完成。CCTV 当前架构已经收敛为：

```text
最高画质选择
↓
clear native / Python H5E native
↓
ffmpeg
```

旧 JS/WASM/vendor compatibility chain 不再属于产品运行时。
