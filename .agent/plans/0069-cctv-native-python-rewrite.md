# 0069 — CCTV 自研化：移除 cctv-dl 外部二进制依赖

- 状态：in_progress
- 创建日期：2026-08-25
- 范围：`mcp/education-resources` CCTV 栏目列表 / 流解析 / 下载全链路 Python 自研，
  替代 cctv-dl.exe 外部二进制；保留 WASM 降级为过渡兜底
- 参考源码：`C:\Users\admin\projects\mediacrawler\downloads\cctv\cctv-dl-src`
  （letr007/CCTVVideoDownloader，**GPLv3**，仅作机制参考，不复制代码）

## Objective

cctv-dl.exe（C++/Qt 二进制）在维护（语言不同改不了）、分发（许可证
NOASSERTION/GPLv3、需随包携带 Qt 运行库）上是硬伤。其全部机制已从源码
确认是**公共接口 + 页面解析 + 标准算法**，可完整 Python 自研：

```text
栏目 URL -> 页面 var topicID/lmtopId = "TOPC..."（缺则抓 /lm/{slug}/videoset）
栏目列表 -> api.cntv.cn/NewVideo/getVideoListByColumn?sort=desc&id={columnId}&n=100&p={page}&d={date}&mode=0&serviceId=tvcctv （分页，支持月份过滤）
单视频   -> zy.api.cntv.cn/video/videoinfoByGuid?serviceId=tvcctv&guid=...
流解析   -> vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid={guid} 的 manifest：
           hls_h5e_url 存在 = H5E 加密模式（分片下载 + 解密 + 封装）
           否则普通流（hls_url / 直链）
h5e 解密 -> cctv_h5e_decrypt.hpp 的 decrypt_ts_inplace(data,len,Session,vpid)
           （Python 移植已存在于 mediacrawler tools/cctv_h5e_decrypt.py，459 行；
           需核对 Session/key05+head12 完整性与弃用原因）
```

## Non-goals

- 不复制 cctv-dl 的 C++ 代码（GPLv3 传染）；机制参考、独立实现。
- 不在这轮移除 WASM 降级；Python 解密经真实老视频对照验证前，WASM 保留兜底。
- 不改公共 Tool 面（仍是 Search/Expand/Inspect/Download）。
- 不实现 GUI / 断点续传 / 画质选择 UI（保持 quality 固定 2000 档上限）。
- 不动其它平台。

## 阶段

### M1 栏目列表自研（本轮）
- `cctv.py`：`column_id_from_page()`（topicID/lmtopId 正则 + videoset 兜底）、
  `iter_column_via_api()`（getVideoListByColumn 分页到真实结束）。
- `iter_column` 改为 **API 优先，cctv-dl 兜底**（过渡；M3 移除兜底）。
- 测试：离线 mock（id 解析两路径、分页终止、字段宽容解析、API 失败降级）。

### M2 下载自研
- 普通流：Python 分片/直链下载 → ffmpeg 封装（复用 smartedu_download 的 HLS 骨架）。
- H5E 流：Python 拉分片 → `cctv_h5e_decrypt.py` 解密（核对 Session 派生是否完整，
  与 h5e_proj 官方 WASM 对照）→ 拼接 → ffmpeg → 体检。
- `CctvVideoDownloader` 改为自研链，cctv-dl 仅 WASM 前的过渡兜底。
- 测试：离线 mock 全链 + 体检门槛。

### M3 清理与验收
- 移除 cctv-dl 依赖（`CCTV_DL_EXE` 退役）、移除 cctv-dl 兜底路径。
- 真实老视频冒烟：自研解密 vs WASM 对照（目标：解码体检 ≤100 错且内容一致）。
- **GPL 合规**：h5e 解密移植文件标注 GPLv3 渊源；分发策略（整体 GPLv3 或
  独立重实现）在验收时定。
- 更新 TOOLS.md / 0068 计划引用 / 同步 OpenClaw。

## Verification

1. 每阶段离线聚焦测试全绿 + 全量不回归（基线 239 passed / 2 环境性失败）。
2. M3 真实冒烟：栏目展开（典籍里的中国）、普通新视频、2021 老视频（自研 vs WASM）。
