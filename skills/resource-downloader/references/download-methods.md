# 通用下载方法详解

> **定位说明**：本文档是下载调度器的**通用兜底方案 + 平台下载方法参考**。
> - 当资源没有对应平台 Skill 时，使用本文档中的通用方法进行下载。
> - 有专属平台 Skill 的，优先走平台 Skill 通道，本文档也收录了各平台的下载方法说明供参考。
> - Platform 已收缩为搜索层；下载入口后续由 Downloader 自己维护。

本文档详细介绍各种资源的下载方法、工具使用技巧和最佳实践。

**目录索引**：
- [视频下载（yt-dlp）](#-视频下载yt-dlp)
- [文件下载（wget/curl）](#-文件下载wget--curl)
- [网页保存与转换](#-网页保存与转换)
- [HLS/m3u8 流媒体下载](#-hlsm3u8-流媒体下载) — smartedu 视频等
- [f2 引擎下载（抖音专用）](#-f2-引擎下载抖音专用) — douyin 短视频
- [音频处理（ffmpeg）](#-音频处理ffmpeg)
- [图片下载](#-图片下载)
- [平台-下载方法映射表](#-平台-下载方法映射表)
- [格式转换（pandoc）](#-格式转换pandoc)
- [故障排查指南](#-故障排查指南)

---

## 🎬 视频下载（yt-dlp）

### 基本用法

```bash
# 最简单的下载
yt-dlp <视频链接>

# 下载到指定目录
yt-dlp -P /path/to/directory <视频链接>

# 指定输出文件名
yt-dlp -o "自定义文件名.%(ext)s" <视频链接>
```

### 质量选择

```bash
# 查看可用的格式列表
yt-dlp -F <视频链接>

# 下载最佳质量（默认）
yt-dlp -f best <视频链接>

# 下载 720p
yt-dlp -f 'bestvideo[height<=720]+bestaudio/best[height<=720]' <视频链接>

# 下载 480p（文件更小）
yt-dlp -f 'bestvideo[height<=480]+bestaudio/best[height<=480]' <视频链接>

# 只下载音频
yt-dlp -f bestaudio <视频链接>
```

### 播放列表/合集下载

```bash
# 下载整个播放列表
yt-dlp -i <播放列表链接>

# 下载第 1-10 集
yt-dlp -i --playlist-start 1 --playlist-end 10 <链接>

# 下载第 3、5、7 集
yt-dlp -i --playlist-items 3,5,7 <链接>

# 播放列表命名模板
yt-dlp -o "%(playlist_index)s-%(title)s.%(ext)s" <链接>
```

### 音频提取

```bash
# 提取为 MP3
yt-dlp -x --audio-format mp3 <视频链接>

# 提取为 M4A（质量更好）
yt-dlp -x --audio-format m4a <视频链接>

# 指定音频质量（128kbps）
yt-dlp -x --audio-format mp3 --audio-quality 128K <链接>
```

### 常用参数

| 参数 | 说明 |
|------|------|
| `-i` | 忽略错误，继续下载（播放列表好用） |
| `-c` | 断点续传 |
| `--no-playlist` | 只下载单个视频，不下载整个列表 |
| `--yes-playlist` | 下载整个播放列表 |
| `--write-description` | 保存视频描述 |
| `--write-thumbnail` | 保存缩略图 |
| `--write-sub` | 下载字幕 |
| `--write-auto-sub` | 下载自动生成的字幕 |

### B站专用技巧

```bash
# 下载 B 站视频（基本用法）
yt-dlp "https://www.bilibili.com/video/BV1xx411c7mD"

# 下载合集
yt-dlp -i "https://www.bilibili.com/medialist/play/ml123456"

# 下载番剧
yt-dlp -i "https://www.bilibili.com/bangumi/play/ss1234"

# 下载字幕
yt-dlp --write-sub --sub-lang zh-CN <B站链接>
```

---

## 📄 文件下载（wget / curl）

### wget 基本用法

```bash
# 最简单的下载
wget <文件链接>

# 指定保存文件名
wget -O "自定义文件名.pdf" <链接>

# 指定保存目录
wget -P /path/to/directory <链接>

# 断点续传（重要！）
wget -c <链接>

# 后台下载
wget -b <链接>

# 限速下载（避免占满带宽）
wget --limit-rate=500k <链接>
```

### 批量下载

```bash
# 从文本文件读取 URL 列表批量下载
wget -i url-list.txt

# 批量下载并指定目录
wget -P /path/to/save -i url-list.txt
```

### curl 基本用法

```bash
# 下载文件
curl -O <链接>

# 指定文件名
curl -o "文件名.pdf" <链接>

# 跟随重定向
curl -L -O <链接>

# 断点续传
curl -C - -O <链接>
```

### wget vs curl 怎么选？

| 场景 | 推荐工具 | 原因 |
|------|---------|------|
| 单文件下载 | 都可以 | 差不多 |
| 批量下载 | wget | 原生支持 -i 参数 |
| 断点续传 | wget | 更简单，-c 就行 |
| 复杂 HTTP 请求 | curl | 更灵活 |
| 下载整个网站 | wget | 有镜像功能 |

**日常使用推荐 wget**，简单直接。

---

## 🌐 网页保存与转换

### 方法一：转 Markdown（推荐）

**优点**：文件小、干净、易读、易搜索
**缺点**：会丢失一些排版和图片

```bash
# 用 pandoc 转换（需要先下载 HTML）
wget -O page.html <网页链接>
pandoc page.html -o output.md

# 或者用其他工具（如 html2text）
```

### 方法二：转 PDF

**优点**：保留完整排版、可打印
**缺点**：文件较大

```bash
# 方法 1：wkhtmltopdf（如果已安装）
wkhtmltopdf <网页链接> output.pdf

# 方法 2：pandoc（效果一般）
pandoc input.html -o output.pdf

# 方法 3：浏览器打印（效果最好，但需要浏览器）
# 用 Chrome 的 --print-to-pdf 参数
```

### 方法三：保存完整 HTML

**优点**：和浏览器看到的一模一样
**缺点**：文件多、有广告、有多余内容

```bash
# wget 保存单页
wget -p -k <网页链接>

# wget 镜像整个网站（慎用！）
wget --mirror <网站链接>
```

### 推荐策略

| 网页类型 | 推荐格式 | 理由 |
|---------|---------|------|
| 练习题/试卷 | Markdown 或 PDF | 干净或可打印 |
| 课程介绍/目录 | Markdown | 轻量易读 |
| 知识科普文章 | PDF | 保留图文排版 |
| 资源列表 | Markdown + 链接 | 重点是链接 |

---

## 📺 HLS/m3u8 流媒体下载

> **适用平台**：smartedu（精品课、同步课堂等课程视频）、cctv、open163 等使用 HLS 协议的平台。
> **本系统权威实现**：`resource-platforms/scripts/smartedu/smartedu_download.py`。

### HLS 协议简介

HLS（HTTP Live Streaming）是 Apple 提出的流媒体协议，核心是 **m3u8 播放列表 + TS 分片**：

```
m3u8 播放列表
  ├── #EXTM3U                    ← 文件头
  ├── #EXT-X-VERSION:3           ← 版本
  ├── #EXT-X-KEY:METHOD=AES-128, ← 加密信息（如有）
  │   URI="https://key-server/...",IV=0x...
  ├── #EXTINF:10.0,              ← 分片时长（秒）
  ├── segment_001.ts             ← 分片1
  ├── #EXTINF:10.0,
  ├── segment_002.ts             ← 分片2
  └── ...
```

下载流程：**获取播放列表 → 解析分片 →（加密流）获取密钥 → 并发下载分片 →（加密流）逐片解密 → 合并**。

### 方法一：ffmpeg 直接下载（通用，适合未加密或标准加密流）

```bash
# 最简单：ffmpeg 直接处理 m3u8
ffmpeg -i "https://example.com/video.m3u8" -c copy output.mp4

# 指定 HTTP 头（某些平台需要 Referer）
ffmpeg -headers "Referer: https://basic.smartedu.cn/" \
  -i "https://example.com/video.m3u8" -c copy output.ts

# 限制并发连接数（避免被封）
ffmpeg -protocol_whitelist file,http,https,tcp,tls,crypto \
  -max_reload 5 \
  -i "https://example.com/video.m3u8" -c copy output.mp4
```

**优点**：一条命令搞定，ffmpeg 自动处理分片下载、解密、合并。
**缺点**：无法控制并发度、无法断点续传、自定义加密流（如 smartedu 的双重密钥交换）无法处理。

### 方法二：分片下载 + 合并（smartedu 实现，推荐）

这是本系统 smartedu 平台采用的方案，适合**自定义加密**或需要**高并发/断点续传**的场景。

#### 调用方式

```bash
# smartedu 全资源下载器（内部自动调用 m3u8 下载）
python3 resource-platforms/scripts/smartedu/smartedu_download.py download \
  "https://basic.smartedu.cn/qualityCourse?courseId=xxx"

# 指定只下载视频（m3u8），并设置并发数
python3 resource-platforms/scripts/smartedu/smartedu_download.py download "https://..." \
  --formats m3u8 --video-concurrency 8

# 指定输出格式为 mp4（需 ffmpeg）
python3 resource-platforms/scripts/smartedu/smartedu_download.py download "https://..." \
  --formats m3u8 --video-output mp4
```

#### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--formats m3u8` | 全部格式 | 只下载 m3u8 视频 |
| `--video-concurrency N` | 5 | TS 分片并发下载数 |
| `--video-output mp4` | ts | 输出格式（ts 直接合并 / mp4 需 ffmpeg 转封装） |
| `--timeout N` | 20 | 单个分片请求超时（秒） |
| `-o / --output-dir` | `./smartedu_downloads` | 输出目录 |

#### 下载流程详解（5 步）

```
步骤 1：获取 m3u8 播放列表
  GET <m3u8_url> → 解析出所有 TS 分片 URL
  （处理相对路径：base_url + segment_name）

步骤 2：解析加密信息
  检查 #EXT-X-KEY 标签
  ├── 无加密（METHOD=NONE）→ 直接跳到步骤 4
  └── 有加密（METHOD=AES-128）→ 提取 URI 和 IV，进入步骤 3

步骤 3：密钥交换（smartedu 专属，通用 HLS 用标准 URI 获取）
  ① GET {key_url}/signs → 获得 nonce
  ② sign = MD5(nonce + key_id)[:16]
  ③ GET {key_url}?nonce=...&sign=... → 获得 base64 编码的加密 key
  ④ AES-ECB 解密（key=sign 的前16字节）→ 得到最终 16 字节解密 key

步骤 4：并发下载 TS 分片
  ThreadPoolExecutor(max_workers=concurrency)
  每个分片：写入临时目录 .{stem}_ts_temp/00001.ts, 00002.ts...
  失败的分片自动重试（首次+2次即时重试，之后3轮逐个重试）

步骤 5：合并 + 解密
  按顺序读取所有 .ts 文件
  ├── 加密流：AES-CBC 解密（key + IV）每个分片
  └── 拼接写入最终 .ts 文件
  清理临时目录
```

#### 输出格式

| 格式 | 说明 | 是否需要 ffmpeg |
|------|------|----------------|
| `.ts`（默认） | 所有分片解密后直接二进制拼接 | 否 |
| `.mp4` | 用 ffmpeg 将 ts 转封装为 mp4（`-c copy`，无损快速） | 是 |

> `.ts` 文件可直接用 VLC、PotPlayer、ffmpeg 播放器播放，也可后续手动转 mp4：
> `ffmpeg -i input.ts -c copy output.mp4`

### 加密流处理

#### 标准 HLS 加密（AES-128）

m3u8 中的 `#EXT-X-KEY:METHOD=AES-128,URI="https://...",IV=0x...`：
- 密钥通过 URI 直接 GET 获取（通常是 16 字节二进制）
- IV 从标签读取，或用分片序号作为 IV
- 每个分片用 AES-128-CBC 解密

#### smartedu 自定义加密（双重密钥交换）

smartedu 的 m3u8 加密比标准 HLS 更复杂，使用**自定义密钥服务器**（`ndvideo-key.ykt.eduyun.cn`）：

```
┌─────────────┐     GET /signs      ┌──────────────┐
│  下载器      │ ──────────────────→ │  密钥服务器    │
│             │ ←─── nonce ──────── │              │
│             │                     │              │
│  sign = MD5(nonce + key_id)[:16]  │              │
│             │                     │              │
│             │ GET ?nonce=&sign=   │              │
│             │ ──────────────────→ │              │
│             │ ←── base64(key) ─── │              │
│             │                     │              │
│ AES-ECB解密  │ ← 最终解密 key      │              │
└─────────────┘                     └──────────────┘
```

**关键约束**：
- 密钥交换接口（`ndvideo-key`）**必须用裸 GET**，不能加 `Authorization`/`accessToken` 等 header，否则返回 403
- TS 分片从 `r1/r2/r3` 三个 CDN 节点轮换下载，单一节点高并发返回 `400 InvalidArgument`
- 最终分片解密用 AES-CBC（不是 ECB），IV 来自 m3u8 标签或默认全零

### ffmpeg 合并与转封装

```bash
# TS 合并为 MP4（无损转封装，速度快）
ffmpeg -i "concat:seg1.ts|seg2.ts|seg3.ts" -c copy output.mp4

# 从合并的 TS 转为 MP4
ffmpeg -i merged.ts -c copy output.mp4

# m3u8 直转 MP4（ffmpeg 内部处理分片下载）
ffmpeg -i "https://example.com/video.m3u8" -c copy output.mp4
```

> **注意**：smartedu 的 TS 合并是直接二进制拼接（`cat`），不需要 ffmpeg。只有当用户要求 `.mp4` 输出时才调用 ffmpeg 做转封装。

---

## 🚀 f2 引擎下载（抖音专用）

> **适用平台**：douyin（抖音）。
> **本系统权威实现**：`resource-platforms/scripts/douyin/douyin_dl.py`（`F2Engine` 类）。
> **依赖**：`pip install f2 gmssl httpx playwright playwright-stealth`

### f2 引擎简介

[f2](https://github.com/Johnserf-Seed/f2) 是一个异步抖音数据采集框架。本系统使用其 **纯 Python API 模式**，核心能力：

| 能力 | 说明 |
|------|------|
| **Token 自动生成** | `ttwid` / `msToken` / `webid` 三件套，自动获取 |
| **ABogus 签名** | 抖音 API 的反爬签名算法，`ABogusManager.model_2_endpoint()` 自动计算 |
| **无浏览器** | 纯 API 调用，不需要启动浏览器（CDP 作为 fallback） |
| **无水印下载** | 从 `play_addr` / `download_addr` 提取无水印视频 URL |

### 调用方式

```bash
# 单个视频下载（无水印）
python3 resource-platforms/scripts/douyin/douyin_dl.py download <视频URL或ID> -o ./downloads/

# 批量下载
python3 resource-platforms/scripts/douyin/douyin_dl.py batch list.json -o ./downloads/

# 用户全部视频
python3 resource-platforms/scripts/douyin/douyin_dl.py user <sec_uid> -o ./downloads/
python3 resource-platforms/scripts/douyin/douyin_dl.py user <sec_uid> -o ./downloads/ --list-only

# 搜索（输出标准 candidate JSON）
python3 resource-platforms/scripts/douyin/douyin_dl.py search "小学数学" --max 20 -o candidates.json

# 签名失效时降级到 CDP 浏览器模式
python3 resource-platforms/scripts/douyin/douyin_dl.py --cdp http://127.0.0.1:9222 download <URL>
```

### 参数说明

#### 全局参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--cdp <URL>` | 无 | CDP 浏览器地址（fallback 模式），如 `http://127.0.0.1:9222` |
| `-o <dir>` | `./downloads` | 输出目录 |

#### download 子命令

| 参数 | 说明 |
|------|------|
| `<URL或ID>` | 抖音视频链接（`https://www.douyin.com/video/xxx`）或纯视频 ID |

#### batch 子命令

| 参数 | 说明 |
|------|------|
| `<list.json>` | JSON 文件，包含视频 URL/ID 列表 |

#### user 子命令

| 参数 | 说明 |
|------|------|
| `<sec_uid>` | 用户 sec_uid 或空间 URL |
| `--list-only` | 只列出视频列表，不下载 |

#### search 子命令

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `<keyword>` | - | 搜索关键词 |
| `--max N` | 20 | 最大返回数 |

### f2 内部工作流程

```
┌──────────────────────────────────────────────────────┐
│  1. Token 生成                                        │
│     TokenManager.gen_ttwid()      → ttwid cookie      │
│     TokenManager.gen_real_msToken() → msToken（首选） │
│     TokenManager.gen_false_msToken()→ msToken（降级） │
│     TokenManager.gen_webid()      → webid             │
├──────────────────────────────────────────────────────┤
│  2. ABogus 签名                                       │
│     ABogusManager.model_2_endpoint(UA, endpoint, params)│
│     → 返回带签名的完整 URL                             │
├──────────────────────────────────────────────────────┤
│  3. API 调用                                          │
│     GET /aweme/v1/web/aweme/detail/?...&a_bogus=xxx   │
│     GET /aweme/v1/web/search/item/?...&a_bogus=xxx    │
│     GET /aweme/v1/web/aweme/post/?...&a_bogus=xxx     │
├──────────────────────────────────────────────────────┤
│  4. 解析视频地址                                      │
│     从 aweme_detail → video.bit_rate[] 选最高画质      │
│     play_addr.url_list[0]  → 有水印播放地址            │
│     download_addr.url_list[0] → 无水印下载地址         │
├──────────────────────────────────────────────────────┤
│  5. 下载视频文件                                      │
│     urllib + 防风控间隔（6-14秒随机）                  │
│     断点续传支持                                      │
└──────────────────────────────────────────────────────┘
```

### 输出格式

**下载结果**：MP4 视频文件（从抖音 API 返回的最高码率流下载）

```python
# douyin_dl.py 解析出的标准格式
{
    "video_id": "7xxxxxxxxxxx",
    "title": "视频描述",
    "author": "作者昵称",
    "duration": 15.0,           # 秒
    "play_url": "https://...",   # 有水印播放地址（最高画质）
    "no_watermark_url": "https://...",  # 无水印下载地址
    "bitrate_count": 3,          # 可选画质数
    "stats": {
        "play": 123456,
        "like": 8901,
        "comment": 234
    }
}
```

**搜索结果**：标准 `learning-resource-candidate/v1` 格式 JSON

### 防风控机制

| 机制 | 参数 | 说明 |
|------|------|------|
| 下载间隔 | 6-14 秒随机 | 每个视频下载后随机等待 |
| 连续失败熔断 | 3 次连续失败 | 触发 `RateLimiter.should_circuit_break` 停止 |
| 批量上限 | 50 个/批 | `RATE_MAX_BATCH` 防止单次请求过多 |
| 签名失效降级 | `SignatureExpiredError` | 自动降级到 CDP 浏览器模式 |

### API 端点

| 端点 | 用途 |
|------|------|
| `https://www.douyin.com/aweme/v1/web/aweme/detail/` | 视频详情 |
| `https://www.douyin.com/aweme/v1/web/aweme/post/` | 用户视频列表 |
| `https://www.douyin.com/aweme/v1/web/search/item/` | 搜索 |

### CDP Fallback 模式

当 ABogus 签名失效（API 返回空响应或风控错误）时，自动降级到 CDP 浏览器模式：

```bash
# 手动指定 CDP
python3 resource-platforms/scripts/douyin/douyin_dl.py --cdp http://127.0.0.1:9222 download <URL>

# 自动降级（无需手动指定）
# 脚本检测到 SignatureExpiredError 后自动尝试 detect_cdp()
# 若 9222 端口有 CDP → 连接现有浏览器
# 若无 → 启动独立 headless 浏览器（需 playwright + playwright-stealth）
```

CDP 模式下，脚本通过 Playwright 连接浏览器，在页面中注入 JS 拦截 API 响应，获取视频地址。

---

## 🎵 音频处理（ffmpeg）

### 格式转换

```bash
# MP4 转 MP3
ffmpeg -i input.mp4 -vn -acodec libmp3lame output.mp3

# MP4 转 M4A（质量更好）
ffmpeg -i input.mp4 -vn -acodec aac output.m4a

# 调整音频质量
ffmpeg -i input.mp4 -vn -acodec libmp3lame -ab 128k output.mp3
```

### 音频剪切

```bash
# 从第 30 秒开始，剪切 2 分钟
ffmpeg -i input.mp3 -ss 00:00:30 -t 00:02:00 -c copy output.mp3

# 从开头剪切到第 5 分钟
ffmpeg -i input.mp3 -t 00:05:00 -c copy output.mp3
```

### 音频合并

```bash
# 合并多个音频文件
ffmpeg -i "concat:file1.mp3|file2.mp3|file3.mp3" -c copy output.mp3
```

---

## 🖼️ 图片下载

### 单张图片

```bash
# 直接下载
wget <图片链接>

# 指定文件名
wget -O "图片名.jpg" <链接>
```

### 批量下载图片

```bash
# 方法 1：从网页提取所有图片
# 先用 wget 下载网页，然后提取图片链接

# 方法 2：用 gallery-dl（如果安装了）
gallery-dl <图集链接>
```

---

## 🗺️ 平台-下载方法映射表

> 本表汇总各平台支持的下载方式、工具和命令。有专属平台 Skill 的优先走平台通道，其余走通用兜底。
> 平台专属下载能力后续在 Downloader 内维护，本文件当前只描述通用方法。

### 已接入平台（有专属 Skill）

| 平台 | 资源类型 | 下载方法 | 工具/引擎 | 输出格式 | 脚本/命令 |
|------|---------|---------|----------|---------|----------|
| **bilibili** | 视频 | CDP 浏览器拦截 + ffmpeg 合并 | Playwright/CDP + ffmpeg | `.mp4` | `bilibili_dl.py download <BV号> -o <dir>` |
| **smartedu** | PDF 教材 | 直接下载（需 Token） | urllib + Access Token | `.pdf` | `smartedu_download.py download <url> --formats pdf` |
| **smartedu** | m3u8 视频 | 分片下载 + AES 解密 + 合并 | urllib + PyCryptodome（+ffmpeg 转 mp4） | `.ts` / `.mp4` | `smartedu_download.py download <url> --formats m3u8` |
| **smartedu** | 音频 | 直接下载 | urllib | `.mp3` / `.ogg` | `smartedu_download.py download <url> --formats mp3` |
| **smartedu** | 图片/白板 | 直接下载 | urllib | `.jpg` | `smartedu_download.py download <url> --formats jpg` |
| **smartedu** | 字幕 | 直接下载 | urllib | `.srt` | `smartedu_download.py download <url> --formats srt` |
| **douyin** | 短视频 | f2 引擎（Token + ABogus 签名） | f2 + gmssl + httpx | `.mp4`（无水印） | `douyin_dl.py download <url> -o <dir>` |
| **douyin** | 短视频（fallback） | CDP 浏览器拦截 | Playwright/CDP | `.mp4` | `douyin_dl.py --cdp http://127.0.0.1:9222 download <url>` |
| **zhihu** | 图文/问答 | API 提取正文 → Markdown | httpx/urllib + z_c0 Cookie | `.md` | `zhihu_dl.py download <url> -o <dir>` |
| **weibo** | 图文 | 页面爬取 → Markdown + 图片 | requests/urllib + SUB Cookie | `.md` + `.jpg` | `weibo_dl.py download <url> -o <dir>` |
| **weibo** | 短视频 | 视频地址提取 + 下载 | requests/urllib | `.mp4` | `weibo_dl.py download <url> -o <dir>` |

### 通用兜底通道（无专属 Skill）

| 资源类型 | 下载方法 | 工具 | 输出格式 | 典型场景 |
|---------|---------|------|---------|---------|
| 视频 | yt-dlp | yt-dlp + ffmpeg | `.mp4` | open163、cctv 等视频站 |
| 音频 | yt-dlp 提取 + ffmpeg 转码 | yt-dlp + ffmpeg | `.mp3` / `.m4a` | ximalaya 等音频站 |
| 文档直链 | wget/curl | wget / curl | `.pdf` / `.docx` | 直链 PDF 文件 |
| 图文网页 | 正文提取 + pandoc 转换 | wget + pandoc | `.md` / `.pdf` | baiduwenku 预览页 |
| 图片 | wget 批量下载 | wget / gallery-dl | `.jpg` / `.png` | xiaohongshu 图集 |
| m3u8 流（通用） | ffmpeg 直接下载 | ffmpeg | `.mp4` / `.ts` | 未知平台的 HLS 视频 |

### 平台工具依赖速查

| 平台 | 必需工具 | 可选/降级工具 |
|------|---------|--------------|
| bilibili | bilibili-api-python, httpx | Playwright（下载）, ffmpeg（合并） |
| smartedu | Python 3.10+, PyCryptodome/cryptography | ffmpeg（ts→mp4）, Access Token（私有资源） |
| douyin | f2, gmssl, httpx | Playwright + playwright-stealth（CDP fallback）, ffmpeg |
| zhihu | httpx（可选，降级 urllib） | z_c0 Cookie（完整内容） |
| weibo | requests/urllib | SUB Cookie（搜索） |

---

## 🔧 格式转换（pandoc）

### 常用转换

```bash
# Markdown 转 PDF
pandoc input.md -o output.pdf

# Markdown 转 Word
pandoc input.md -o output.docx

# HTML 转 Markdown
pandoc input.html -o output.md

# Word 转 Markdown
pandoc input.docx -o output.md
```

### 批量转换

```bash
# 批量把 md 转成 pdf
for f in *.md; do pandoc "$f" -o "${f%.md}.pdf"; done
```

---

## 📝 下载后的整理工作

### 1. 重命名

下载后的文件通常名字很乱，改成有意义的中文名：

```bash
# 单个文件重命名
mv "BV123456789.mp4" "小学四年级数学-四则运算-第1集.mp4"
```

### 2. 整理目录

按学科、年级、主题分类：

```
学习资料库/
└── 数学/
    └── 小学四年级/
        └── 四则混合运算/
            ├── 视频/
            │   ├── 第1集-加减法的意义.mp4
            │   └── ...
            ├── 练习题/
            │   ├── 四则混合运算100道.pdf
            │   └── ...
            └── 文档/
                └── 知识点总结.md
```

### 3. 生成索引

为每个目录生成一个 README 或索引文件，说明里面有什么内容。

---

## ⚡ 高级技巧

### 1. 下载限速

避免占满带宽，影响正常上网：

```bash
# wget 限速 500KB/s
wget --limit-rate=500k <链接>

# yt-dlp 限速
yt-dlp --limit-rate 500K <链接>
```

### 2. 后台下载

大文件可以放后台慢慢下：

```bash
# wget 后台下载
wget -b <链接>

# 查看进度
tail -f wget-log
```

### 3. 定时下载

可以用 cron 定时下载（但不建议，容易被封）

### 4. 代理下载

如果需要的话，可以设置代理：

```bash
# wget 用代理
wget -e use_proxy=yes -e http_proxy=proxy:port <链接>

# yt-dlp 用代理
yt-dlp --proxy http://proxy:port <链接>
```

---

## 🔍 故障排查

具体错误现象、排查步骤和降级建议统一见 `troubleshooting.md`；错误码使用 `error-codes.md`。本文件不再重复维护故障表。

## 🔗 相关文档

| 文档 | 说明 |
|------|------|
| `platform-download-contract.md` | 未来的平台下载接口 |
| `error-codes.md` | 下载错误码规范 |
| `../../resource-platforms/references/platforms/smartedu.md` | smartedu 平台能力与限制 |
| `../../resource-platforms/references/platforms/douyin.md` | douyin 平台能力与限制 |
| `../../resource-platforms/references/platforms/bilibili.md` | bilibili 平台能力与限制 |
| `../../resource-platforms/references/platforms/zhihu.md` | zhihu 平台能力与限制 |
| `../../resource-platforms/references/platforms/weibo.md` | weibo 平台能力与限制 |

---
