# 0076 — CCTV 兼容运行时减重

- 状态：in_progress
- 创建日期：2026-08-28
- 完成日期：未完成
- 范围：CCTV WASM fallback 的运行时封装、Windows 安装、发布包和聚焦测试

## Objective

在保留 CCTV 现有 native → 官方 WASM fallback 行为、旧视频兼容和 MP4 健康检查的前提下，把 WASM fallback 改为构建期静态 JavaScript bundle，使用户安装阶段不再执行 `npm ci`，也不再需要 tsx、TypeScript、esbuild 或 node_modules。

## Non-goals

- 本阶段不删除 Node；定制 OpenClaw 已提供 Node 运行时；
- 不删除 ffmpeg，不改变 MP4 remux 与完整解码体检；
- 不重写或替换官方 WASM worker，不扩大 CCTV 搜索、展开、检查、画质或下载能力；
- 不声称纯 Python 已覆盖全部旧视频，不删除 native 健康门和 WASM fallback；
- 不处理独立 Windows 卸载链；生命周期继续由定制 OpenClaw 统一管理；
- 不新增 runtime registry、依赖管理框架或第二份能力真实来源。

## Business invariants

- CCTV public Tool、Provider 路由、输入输出和错误码不变；
- native 成功时仍返回 native；只有 native 失败或健康检查不通过时才进入 WASM；
- WASM 使用与当前 vendored MIT 上游相同的 CLI/worker 代码，只改变执行形态；
- 取消、超时、分片顺序、输出 MP4、SHA256、健康检查与失败聚合语义保持不变；
- 运行包必须包含 bundle 和许可证，不在用户安装阶段访问 npm registry。

## Current architecture

- `cctv_download.py` 当前通过 `node --import tsx src/cli/main.ts` 执行 fallback；
- Windows `install.ps1` 在 pip 安装后进入 vendor 目录执行 `npm ci`；
- vendor 源码约 6.4 MB，运行安装还会生成 node_modules；上游已提供 esbuild 的 `main.js`/`worker.js` 静态 bundle；
- Python native 路径仍存在旧视频差异，不能直接删除 WASM；ffmpeg 仍负责 remux 和最终健康证明。

## Expected change surface

- `vendor/cctv-h5e/runtime/`：构建期生成的 `main.js`、`worker.js` 与来源说明；
- `cctv_download.py`：解析 bundle 并用 `node main.js` 执行；
- `pyproject.toml`、`packaging/windows/install.ps1`、`scripts/build-release.ps1`：只分发静态 runtime，删除安装期 npm；
- CCTV 聚焦测试与相关 README/TOOLS 文档。

## Acceptance criteria

- [x] AC-01：fallback 不再调用 tsx/TypeScript，命令为 Node 直接执行静态 bundle；
- [x] AC-02：Windows 安装不检查 npm、不执行 `npm ci`，离线安装包内已有完整 CCTV runtime；
- [x] AC-03：wheel 只含 runtime 四文件；Windows release builder 删除源码/lock/build 并以严格 allowlist 阻止泄漏；实际 Windows ZIP 待推送后由 CI 构建；
- [x] AC-04：CCTV Tool/Provider 公共契约、native-first、健康门、fallback、取消和错误语义不变；
- [x] AC-05：聚焦测试覆盖 bundle 解析、执行命令、缺 Node/缺 bundle 和 fallback 成功失败；
- [x] AC-06：2018 公开 H5E 样本首分片经实际 Python fallback 函数调用静态 bundle，成功生成 TS、remux MP4，ffmpeg 全解码 0 错；更大样本矩阵未执行。

## Complexity exceptions

无。静态 bundle 替换安装期编译依赖，未增加新的抽象、source of truth 或 fallback。

## Steps

- [x] completed：审计现有 native/WASM/ffmpeg、安装和发布边界，确认上游 bundle 形态。
- [x] completed：生成并接入固定来源的静态 runtime bundle，移除安装期 npm/tsx。
- [x] completed：更新发布裁剪、文档和聚焦测试。
- [ ] in_progress：已完成聚焦自动化验证与有界真实旧视频 smoke；等待推送触发 Windows release/install CI 后收口归档。

## Validation scope

- `tests/test_cctv_platform.py` 聚焦测试；
- wheel/package-data 与 Windows release 静态检查；
- 一个公开旧视频的有界真实 fallback smoke；
- 不默认运行全量回归，不以测试替代真实样本健康检查。

## Current checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes; Node and ffmpeg retained
Business invariants still true?: yes; command packaging changed, download routing did not
New abstraction/source of truth/fallback?: no
Data truncation added?: no
Unrelated files changed?: no
Actual user flow affected?: installation no longer reaches npm; CCTV fallback uses static bundle
Actual user flow validated?: bounded real 2018 H5E segment -> TS -> MP4 -> ffmpeg 0 errors
Scope drift detected?: no
```

## Verification

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| `pytest -q tests/test_cctv_platform.py` | 28 passed | CCTV contracts/routes and new bundle resolution/command tests pass | real network and Windows install |
| wheel build + content inspection | pass; wheel 820,554 bytes | installed Python package contains only runtime LICENSE/README/main.js/worker.js under CCTV vendor | Windows ZIP builder execution |
| 2018 public H5E bounded smoke | pass; 865,928-byte TS, 814,517-byte MP4, ffmpeg health output 0 bytes | actual bundle and Python invocation decrypt/remux one known-old segment | full episode and broader old/new corpus |
| Windows release/install GitHub Actions | pending until push | final Windows packaging and install | broad CCTV corpus |
