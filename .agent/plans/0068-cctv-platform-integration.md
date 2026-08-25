# 0068 — CCTV（央视网）平台接入

- 状态：in_progress
- 创建日期：2026-08-24
- 范围：`mcp/education-resources` CCTV 搜索 / 展开 / 检查 / 下载、URL 识别、注册点、聚焦测试与文档
- 能力来源：`C:\Users\admin\projects\mediacrawler` 已验证的 CCTV 实现（栏目/系列/单集 + cctv-dl 下载链）

## Objective

把 mediacrawler 中已经真实使用过的央视网采集能力接入当前统一的
Search / Expand / Inspect / Download 能力面：

```text
Search   关键词 -> 视频（叶子）+ 栏目（容器）双路
Expand   栏目(/lm/) -> video[]；纪录片系列页 -> video[]
Inspect  单集页解析 guid + getHttpVideoInfo 画质/版权事实
Download guid -> cctv-dl.exe -> MP4（720P 上限），ffmpeg 解码体检 + 重试
```

平台资源视图：

```text
容器: column（栏目 /lm/ 页）、series（系列页，页内 >=2 集链接）
叶子: video -> MP4
```

无创作者层；免登录。

## Non-goals

- 不新增 MCP Tool；公共面保持 Search / Expand / Inspect / Download 不变。
- 不重写 cctv-dl 的 C++ 解密核心为纯 Python（h5e 算法 Python 移植 459 行
  已存在且被弃用；生产级覆盖是 WASM 官方 worker 才解决的）。降级走
  官方 WASM worker（node + h5e_proj），算法不自己重写。
- 不为栏目列举编造未确认的 cntv 公共接口；栏目全集枚举走已验证的
  cctv-dl `list`（本地二进制，`CCTV_DL_EXE` 可覆盖路径）。
- 不接 m.cctv.com / 央视新闻等非 tv.cctv.com 形态。
- 不做画质选择 UI；默认 quality=0（2000 档 720P 最高），`CCTV_QUALITY` 可覆盖。

## Business invariants

1. Expand 只枚举候选，不授权下载；系列页判定必须基于页面真实链接数（>=2），
   不按 URL 猜测。
2. 叶子下载精确：没有 guid 的候选先从页面解析，解析不到显式失败，
   不降级成"栏目里第一个视频"。
3. cctv-dl 缺失是显式 `PROVIDER_UNAVAILABLE`（附 `CCTV_DL_EXE` 指引），
   不假装平台不可用，也不静默跳过。
4. 下载产物经 ffmpeg 全片解码体检（错误行 <=100 为干净），坏文件删除重试，
   最多 3 次；最终失败携带真实原因（rc / failed 分片数 / 体检错误数）。
5. **老视频（2021 及以前，cctv-dl 确定性解密坏/乱码）自动降级官方 WASM
   worker 重下**：Python 并发拉分片 → 分组并行 `node --import tsx` 解密 →
   拼接 → ffmpeg 封装 → 同体检门槛。降级不静默：成功/失败都在结果里
   携带路径（cctv-dl / wasm）与体检数据。
6. WASM 的 m3u8 **优先取视频自身的 `h5e_url`**（getHttpVideoInfo manifest，
   inspect 已存入 platform_signals）；为空才回退 `H5E_BASE` 模板
   （`CCTV_H5E_BASE` 可覆盖，默认 mediacrawler 常量 `2000/0303000a/3/default`，
   该模板通用性未确认，仅作兜底）。
7. node / h5e_proj 缺失是显式失败（附 `CCTV_H5E_PROJ` 指引），不静默跳过；
   `CCTV_H5E_PROJ` 默认 mediacrawler 的 h5e_proj，与 cctv-dl 同部署模式。
8. 无法解析 guid 的系列剧集不静默消失：以 URL 中的 VID 标识占位入候选，
   后续 Inspect/Download 再补齐事实。
9. 平台结构事实（接口、画质档位、系列页拓扑、降级链）记录在 TOOLS.md 平台节。

## Expected change surface

- `adapters/cctv.py`：视频搜索保留；新增栏目搜索（A-Z 目录并发扫描）、
  `iter_column`（cctv-dl list）、系列页链接提取与逐集解析助手。
- `adapters/cctv_download.py`（新增）：exe 解析（env `CCTV_DL_EXE` + 默认
  mediacrawler 安装路径）、带取消的子进程运行、download_complete 事件解析、
  ffmpeg 体检、`CctvVideoDownloader`；**WASM 降级链**（cctv-dl 确定性失败后
  Python 拉分片 → node 分组解密 → 拼接 → ffmpeg → 体检），`CCTV_H5E_PROJ` /
  `CCTV_H5E_BASE` env 覆盖。
- `adapters/inspect_cctv.py`（新增）：栏目/系列 -> 容器指引（不可下载）；
  单集 -> guid + 详情事实 + primary video/mp4 表示（含 `h5e_url` 供降级）。
- `adapters/resource_urls.py`：tv.cctv.com /lm/ -> column；
  /YYYY/MM/DD/VID*.shtml -> 视频。
- `adapters/expansion.py`：`_expand_cctv` 路由。
- `inspection_registry.py`、`acquisition/planner.py`（cctv-video spec）、
  `service.py`（import 平台识别 + provider 注册）。
- 测试：`tests/test_cctv_platform.py`（离线：URL 识别、栏目/系列展开、
  叶子错误、下载成功/体检失败重试/exe 缺失、**WASM 降级成功 / node 缺失 /**
  **h5e_url 优先**、检查器三形态）。
- 文档：`TOOLS.md` 平台视图表 + CCTV 节（含降级链说明）。

## Verification

1. 离线聚焦测试：`tests/test_cctv_platform.py` 15 passed（URL 识别、栏目/系列
   展开、叶子错误、exe 缺失、下载成功/体检重试/最终失败/guid 解析、检查器
   栏目/系列/单集/无流/非央视宿主）。
2. 全量回归：251 passed / 1 skipped / 3 failed。3 个失败为分支既有债务
   （已用 stash 验证 HEAD 同样失败）：`test_platform_adapters` 仍断言
   `annas-archive`（本分支已改名 `libgen`）；`test_mcp_stdio` /
   `test_session_public_contract` 在 Windows GBK 控制台下读子进程 stdout
   解码失败。本计划不修这三项。
3. compileall 通过。
4. 真实冒烟（待用户环境执行）：搜索"典籍里的中国"出栏目+视频候选；
   展开 `https://tv.cctv.com/lm/djldzg/index.shtml`；单集下载得到真实 MP4。
