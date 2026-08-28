# 0076 — CCTV 兼容运行时减重

- 状态：completed
- 创建日期：2026-08-28
- 完成日期：2026-08-29
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

## Final architecture

```text
Python CCTV downloader
  ↓ native path first
  ├─ healthy → output
  └─ native failed/unhealthy
       ↓
     Node main.js
       ↓
     bundled worker.js / official WASM compatibility runtime
       ↓
     TS/media
       ↓
     ffmpeg remux + full decode health check
```

用户安装阶段不再执行：

```text
npm ci
node --import tsx
TypeScript runtime
esbuild
node_modules generation
```

Release / wheel 只分发当前运行所需的 CCTV runtime 文件与许可证。

## Acceptance criteria

- [x] AC-01：fallback 不再调用 tsx/TypeScript，命令为 Node 直接执行静态 bundle；
- [x] AC-02：Windows 安装不检查 npm、不执行 `npm ci`，离线安装包内已有完整 CCTV runtime；
- [x] AC-03：wheel 只含 runtime 四文件；Windows release builder 删除源码/lock/build 并以严格 allowlist 阻止泄漏；Windows ZIP 构建和内容检查真实通过；
- [x] AC-04：CCTV Tool/Provider 公共契约、native-first、健康门、fallback、取消和错误语义不变；
- [x] AC-05：聚焦测试覆盖 bundle 解析、执行命令、缺 Node/缺 bundle 和 fallback 成功失败；
- [x] AC-06：2018 公开 H5E 样本首分片经实际 Python fallback 函数调用静态 bundle，成功生成 TS、remux MP4，ffmpeg 全解码 0 错；
- [x] AC-07：Windows clean release/install GitHub Actions 真实通过 packaged install、runtime verify 和 artifact upload。

## Complexity exceptions

无。静态 bundle 替换安装期编译依赖，未增加新的抽象、source of truth 或 fallback。

## Completed steps

- [x] 审计现有 native/WASM/ffmpeg、安装和发布边界，确认上游 bundle 形态；
- [x] 生成并接入固定来源的静态 runtime bundle，移除安装期 npm/tsx；
- [x] 更新发布裁剪、文档和聚焦测试；
- [x] 修正 clean Windows CI 中 best-effort Gateway restart 遗留 `$LASTEXITCODE=1` 导致安装成功仍被判失败的问题；
- [x] clean Windows release/install CI 完整跑绿并上传发行 artifact。

## Final checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes; Node and ffmpeg retained
Business invariants still true?: yes
New abstraction/source of truth/fallback?: no
Data truncation added?: no
Actual user flow affected?: installation no longer reaches npm; CCTV fallback uses static bundle
Actual user flow validated?: bounded real 2018 H5E segment + clean Windows packaged install
Scope drift detected?: no
```

## Verification

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| `pytest -q tests/test_cctv_platform.py` | 28 passed | CCTV contracts/routes and bundle resolution/command behavior | broad live platform corpus |
| wheel build + content inspection | pass; wheel contains runtime LICENSE/README/main.js/worker.js | installed package no longer needs TS/npm build tree | every Windows environment |
| 2018 public H5E bounded smoke | pass; TS → MP4 → ffmpeg full decode 0 errors | static bundle can decrypt/remux a known-old H5E sample | full episode and broad old/new sample matrix |
| Windows release/install GitHub Actions run 33189616940 | success; build, allowlist, OpenClaw install, packaged install, runtime verify, artifact upload all passed | clean packaged Windows installation works through the current release gate | configured model/provider and real Agent conversation |

## Result

0076 完成。CCTV compatibility fallback 已从安装期 TypeScript/npm 运行工程收敛为随包静态 JavaScript runtime；最终用户不再承担 npm/tsx/TypeScript/esbuild/node_modules 安装负担。Node 和 ffmpeg 仍作为当前真实运行依赖保留。后续是否进一步改成 Python WASM runtime / 去掉 Node，必须另开独立计划并以真实收益重新评估，不作为当前系统发布阻塞项。
