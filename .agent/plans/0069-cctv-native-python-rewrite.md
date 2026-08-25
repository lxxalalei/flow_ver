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

### M2 下载自研（已完成 2026-08-25）
- **核对发现并修复移植 bug**：mediacrawler `cctv_h5e_decrypt.py` 与 hpp 逐行
  对应，但 `tea_decrypt_block` 的 **`>>5` 项 key 对调**（v1 行误用 k1、v0 行
  误用 k3）——这就是当年"老方案"被弃用的**真实原因**（解密结果错误=乱码，
  不是性能）。已按 hpp 标准配对（v1: k2/k3、v0: k0/k1）修复。
- 解密模块搬入：`adapters/cctv_h5e.py`（GPLv3 渊源标注：移植自
  letr007/CCTVVideoDownloader 的 cctv_h5e_decrypt.hpp）。
- 普通流：`getHttpVideoInfo` manifest 无 h5e 时 → 普通 HLS（m3u8 分片 +
  ffmpeg 拼接）或直链 MP4 下载（`download_stream_native`）。
- H5E 流：Python 拉分片 → **ProcessPool 分片级并行解密**（每分片独立 TEA，
  天然并行）→ 顺序拼接 → ffmpeg → 体检（`download_h5e_native`）。
- `CctvVideoDownloader.download` 三级：**native → cctv-dl → WASM**，最终失败
  聚合三条路径原因。
- 测试（34 个）：含 classic 模式 TEA 往返（加密 TS 构造 + 解密恢复）、
  非视频 PID pass-through、native 普通流/h5e/降级全路径。往返测试还验证了
  TS 层（PES 跨包、AF 零吸收、0xFF 残留）的字节级一致性。

### M3 清理与验收（已完成 2026-08-25）
- **cctv-dl 依赖已完全移除**：栏目列表走 getVideoListByColumn（M1）、下载走
  native（M2），cctv-dl.exe / CCTV_DL_EXE / run_cctv_dl_list 全部退役删除。
- **真实冒烟（典籍里的中国 20210807，guid 63f1bd…）**：
  - 栏目 id 解析（页面 topicID 正则 + videoset 兜底）✓
  - 列表 API 11 条 ✓（响应嵌套 `data.list` 解析已修）
  - h5e m3u8 575 分片 ✓、native 解密 ✓
  - **修复 3 个移植 bug**（对照 hpp + 官方 WASM 实测）：
    1. `tea_decrypt_block` >>5 key 对调（老方案弃用真相）
    2. `type1_stride_f1` OR 项索引差 1
    3. classic 网格终止 o+8 → **o+80**（WASM 语义；o+8 会解编码器未加密的
       尾部块 → 乱码，正是"cctv-dl 老视频乱码"的根源）
  - 修复后与官方 WASM 字节级一致：**244/250** 个 type1/5 NAL 完全相同。
- **已知 gap（诚实记录）**：6 个 01a8 flip 家族 NAL（seg0 IDR 内）为官方 WASM
  独有的全覆盖变换（非 TEA 变体，参数扫描不匹配），离线无法复现 → 含此类
  NAL 的老视频 native 解码脏（20 片 1762 错）→ **自动 WASM 降级兜底**（现有
  体检门槛架构生效）。结论：**WASM 仍是必要兜底，不可移除**；native 是主路径。
- **GPL 合规**：`adapters/cctv_h5e.py` 头部标注 GPLv3 渊源；分发时该文件按
  GPLv3 条款处理（含源码获取说明）。
- 更新 TOOLS.md / 0068 计划引用 / 同步 OpenClaw。

## Verification

1. 每阶段离线聚焦测试全绿 + 全量不回归（26 个 CCTV 测试 + 全量 237+）。
2. M3 真实冒烟完成（见上）：栏目展开 ✓、老视频 h5e 链 ✓、自研 vs WASM 对照 ✓
   （244/250 NAL 一致 + 6 个 01a8 家族 gap → WASM 兜底）。
3. 后续待验证：新视频（非 2021）native 路径是否干净（无 01a8 家族时）。
