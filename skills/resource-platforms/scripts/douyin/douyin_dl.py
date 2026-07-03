#!/usr/bin/env python3
"""
抖音视频下载器 (f2 引擎版)
  - 纯 Python API：f2 ABogus 签名 + Token 自动生成
  - 无需浏览器（CDP 作为 fallback）
  - 自动选择最高画质
  - urllib 下载 + 防风控 + 断点续传

用法:
  python douyin_dl.py download <视频URL或ID> -o output/
  python douyin_dl.py batch list.json -o output/
  python douyin_dl.py user <sec_uid> -o output/
  python douyin_dl.py user <sec_uid> -o output/ --list-only
  python douyin_dl.py search "关键词" --max 20 -o candidates.json

依赖:
  pip install f2 gmssl httpx playwright playwright-stealth
"""

import sys
import os
import re
import json
import time
import random
import asyncio
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared.logger import getLogger

log = getLogger("douyin")

# ========== 配置 ==========
FFMPEG = r"C:\Users\admin\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
CDP_DEFAULT_PORT = 9222

# 防风控
RATE_DOWNLOAD_INTERVAL_MIN = 6
RATE_DOWNLOAD_INTERVAL_MAX = 14
RATE_MAX_CONSECUTIVE_FAIL = 3
RATE_MAX_BATCH = 50

# API 端点
DETAIL_EP = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
USER_POST_EP = "https://www.douyin.com/aweme/v1/web/aweme/post/"
SEARCH_EP = "https://www.douyin.com/aweme/v1/web/search/item/"
# ==========================


# ─── 异常 ──────────────────────────────────────────────────

class RiskControlError(Exception):
    def __init__(self, code, message, action="stop"):
        self.code = code
        self.risk_message = message
        self.action = action
        super().__init__(f"[风控] code={code}: {message}")


class SignatureExpiredError(Exception):
    """ABogus 签名过期，需要降级到 CDP"""
    pass


# ─── 防风控 ────────────────────────────────────────────────

class RateLimiter:
    def __init__(self):
        self._consecutive_fails = 0

    def record_success(self):
        self._consecutive_fails = 0

    def record_failure(self):
        self._consecutive_fails += 1

    @property
    def should_circuit_break(self):
        return self._consecutive_fails >= RATE_MAX_CONSECUTIVE_FAIL

    def wait_for_download(self, index):
        base = RATE_DOWNLOAD_INTERVAL_MIN + (index % 5)
        jitter = random.uniform(0, max(0, RATE_DOWNLOAD_INTERVAL_MAX - base))
        wait = base + jitter
        log.info("等待 %.0fs...", wait)
        time.sleep(wait)

_limiter = RateLimiter()


# ─── f2 引擎：Token + 签名 ────────────────────────────────

class F2Engine:
    """
    f2 纯 Python 引擎：Token 自动生成 + ABogus 签名 + API 调用。
    不需要浏览器，不需要 CDP。
    """
    def __init__(self):
        cookie = os.environ.get("DOUYIN_COOKIE", "").strip()
        cookie_file = os.environ.get("DOUYIN_COOKIE_FILE", "").strip()
        if not cookie and cookie_file:
            path = Path(cookie_file).expanduser()
            if path.is_file():
                cookie = path.read_text(encoding="utf-8-sig").strip()
        self._cookie_str = cookie
        self._ttwid = self._cookie_value("ttwid")
        self._msToken = self._cookie_value("msToken")
        self._webid = self._cookie_value("s_v_web_id")

    def _cookie_value(self, name):
        match = re.search(rf"(?:^|;\s*){re.escape(name)}=([^;]+)", self._cookie_str or "")
        return match.group(1) if match else ""

    def ensure_tokens(self):
        """确保所有 token 已生成"""
        if self._ttwid and self._msToken:
            return
        from f2.apps.douyin.utils import TokenManager

        log.info("[f2] 生成 Token...")
        if not self._ttwid:
            try:
                self._ttwid = TokenManager.gen_ttwid()
                log.info("ttwid 已生成")
            except Exception as e:
                log.warning("ttwid 失败: %s", e)
                self._ttwid = ""

        if not self._msToken:
            try:
                self._msToken = TokenManager.gen_real_msToken()
                log.info("msToken 已生成")
            except Exception as e:
                log.warning("真实 msToken 失败，使用伪造版: %s", e)
                self._msToken = TokenManager.gen_false_msToken()

        if not self._webid:
            try:
                self._webid = TokenManager.gen_webid()
            except:
                self._webid = ""

        parts = [self._cookie_str] if self._cookie_str else []
        if self._ttwid and "ttwid=" not in (self._cookie_str or ""):
            parts.append(f"ttwid={self._ttwid}")
        if self._msToken and "msToken=" not in (self._cookie_str or ""):
            parts.append(f"msToken={self._msToken}")
        self._cookie_str = "; ".join(part for part in parts if part)

    def sign_url(self, endpoint, params):
        """ABogus 签名"""
        from f2.apps.douyin.utils import ABogusManager
        self.ensure_tokens()
        # msToken 放进参数
        if self._msToken and "msToken" not in params:
            params["msToken"] = self._msToken
        return ABogusManager.model_2_endpoint(UA, endpoint, params)

    def _headers(self):
        return {
            "User-Agent": UA,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
            "Cookie": self._cookie_str or "",
        }

    def fetch_detail_sync(self, video_id):
        """同步获取视频详情（线程中跑 async）"""
        return asyncio.run(self.fetch_detail(video_id))

    async def fetch_detail(self, video_id):
        """获取单个视频详情"""
        import httpx
        params = {
            "aweme_id": str(video_id),
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "platform": "PC",
            "downlink": "10",
            "qualityType": "1",
        }
        signed_url = self.sign_url(DETAIL_EP, params)

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(signed_url, headers=self._headers())

            if resp.status_code != 200:
                raise RiskControlError(resp.status_code, f"HTTP {resp.status_code}")

            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                # 空响应或签名过期
                body = resp.text[:100]
                if not body.strip():
                    raise SignatureExpiredError("API 返回空响应，签名可能过期")
                raise RiskControlError(-1, f"非 JSON 响应: {ct}")

            data = resp.json()
            sc = data.get("status_code", -1)
            if sc != 0:
                raise RiskControlError(sc, data.get("status_msg", "未知错误"))

            aweme = data.get("aweme_detail")
            if not aweme:
                return None
            return self._parse_aweme(aweme, video_id)

    async def fetch_user_post(self, sec_uid, max_cursor=0, count=18):
        """获取用户视频列表（一页）"""
        import httpx
        params = {
            "sec_user_id": sec_uid,
            "max_cursor": max_cursor,
            "count": count,
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "platform": "PC",
            "downlink": "10",
        }
        signed_url = self.sign_url(USER_POST_EP, params)

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(signed_url, headers=self._headers())

            if resp.status_code != 200:
                raise RiskControlError(resp.status_code, f"HTTP {resp.status_code}")

            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                raise SignatureExpiredError("用户列表 API 返回空响应")

            data = resp.json()
            sc = data.get("status_code", -1)
            if sc == 5:
                # 用户不存在 / 需要登录
                return [], 0, False
            if sc != 0:
                raise RiskControlError(sc, data.get("status_msg", ""))

            aweme_list = data.get("aweme_list") or []
            has_more = data.get("has_more", False)
            next_cursor = data.get("max_cursor", 0)

            videos = []
            for a in aweme_list:
                vid = str(a.get("aweme_id", ""))
                if not vid:
                    continue
                videos.append({
                    "video_id": vid,
                    "title": a.get("desc", vid),
                    "url": f"https://www.douyin.com/video/{vid}",
                    "duration": a.get("duration", 0) / 1000,
                    "author": a.get("author", {}).get("nickname", ""),
                })
            return videos, next_cursor, has_more

    async def fetch_search(self, keyword, offset=0, count=15, sort_type=0, publish_time=0):
        """搜索抖音视频。返回 (videos, next_offset, has_more)。

        基于 SEARCH_EP = "https://www.douyin.com/aweme/v1/web/search/item/"
        sort_type: 0=综合排序, 1=最多点赞, 2=最新发布
        publish_time: 0=不限, 1=一天内, 7=一周内, 180=半年内
        """
        import httpx
        params = {
            "keyword": keyword,
            "search_channel": "aweme_general",
            "sort_type": str(sort_type),
            "publish_time": str(publish_time),
            "offset": str(offset),
            "count": str(count),
            "search_source": "normal_search",
            "query_correct_type": "1",
            "is_filter_search": str(1 if (sort_type or publish_time) else 0),
            "from_group_id": "",
            "offset_level": "0",
            "count_down": "1",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "platform": "PC",
            "downlink": "10",
        }
        signed_url = self.sign_url(SEARCH_EP, params)

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(signed_url, headers=self._headers())

            if resp.status_code != 200:
                raise RiskControlError(resp.status_code, f"HTTP {resp.status_code}")

            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                body = resp.text[:200]
                if not body.strip():
                    raise SignatureExpiredError("搜索 API 返回空响应，签名可能过期")
                raise RiskControlError(-1, f"搜索非 JSON 响应: {ct}")

            data = resp.json()
            sc = data.get("status_code", -1)
            if sc != 0 and sc != 8:
                # status_code=8 可能是风控提示但仍有部分数据
                raise RiskControlError(sc, data.get("status_msg", "搜索失败"))

            items = data.get("data") or []
            has_more = data.get("has_more", False)
            next_offset = offset + len(items)

            videos = []
            for item in items:
                aweme = item.get("aweme_info") or item
                if not aweme:
                    continue
                vid = str(aweme.get("aweme_id", ""))
                if not vid:
                    continue
                author_info = aweme.get("author", {}) or {}
                videos.append({
                    "video_id": vid,
                    "title": aweme.get("desc", vid),
                    "url": f"https://www.douyin.com/video/{vid}",
                    "duration": (aweme.get("duration", 0) or 0) / 1000,
                    "author": author_info.get("nickname", ""),
                    "stats": {
                        "play": (aweme.get("statistics", {}) or {}).get("play_count", 0),
                        "like": (aweme.get("statistics", {}) or {}).get("digg_count", 0),
                    },
                })
            return videos, next_offset, has_more

    def _parse_aweme(self, aweme, video_id):
        """解析 aweme_detail 为标准格式"""
        video_data = aweme.get("video", {})
        play_addr = video_data.get("play_addr", {})
        bit_rate = video_data.get("bit_rate", [])

        # 选最高画质
        best_url = self._select_best_url(bit_rate, play_addr)
        if not best_url:
            return None

        best_url = best_url.replace("\\u002F", "/").replace("&amp;", "&")

        # 无水印
        download_addr = video_data.get("download_addr", {})
        download_urls = download_addr.get("url_list", [])
        no_wm = download_urls[0] if download_urls else None
        if no_wm:
            no_wm = no_wm.replace("\\u002F", "/").replace("&amp;", "&")

        return {
            "video_id": video_id,
            "title": aweme.get("desc", str(video_id)),
            "author": aweme.get("author", {}).get("nickname", ""),
            "duration": aweme.get("duration", 0) / 1000,
            "play_url": best_url,
            "no_watermark_url": no_wm,
            "bitrate_count": len(bit_rate),
            "stats": {
                "play": aweme.get("stats", {}).get("play_count", 0),
                "like": aweme.get("stats", {}).get("digg_count", 0),
                "comment": aweme.get("stats", {}).get("comment_count", 0),
            },
        }

    @staticmethod
    def _select_best_url(bit_rate, play_addr):
        """选最高画质 URL"""
        if not bit_rate:
            urls = play_addr.get("url_list", [])
            return urls[0] if urls else None

        best = None
        best_bitrate = -1
        for br in bit_rate:
            br_val = br.get("bit_rate", 0)
            urls = br.get("play_addr", {}).get("url_list", [])
            if urls and br_val > best_bitrate:
                best_bitrate = br_val
                best = urls[0]
        return best


# ─── 全局 f2 引擎 ──────────────────────────────────────────

_engine = F2Engine()


# ─── CDP fallback（签名过期时降级）────────────────────────

def detect_cdp(port=CDP_DEFAULT_PORT, timeout=3):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/version")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except:
        return False


def _cdp_fetch_detail(video_id, cdp_url=None):
    """CDP fallback：浏览器拦截 detail API"""
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
        has_stealth = True
    except ImportError:
        has_stealth = False

    port = CDP_DEFAULT_PORT
    if cdp_url:
        m = re.search(r':(\d+)', cdp_url)
        if m:
            port = int(m.group(1))

    pw = sync_playwright().start()
    try:
        if detect_cdp(port):
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            own = False
        else:
            log.warning("[CDP] 未检测到，启动独立浏览器...")
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA)
            own = True

        page = ctx.new_page()
        if own and has_stealth:
            Stealth().apply_stealth_sync(page)

        # 建立会话
        page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        # 拦截 detail API
        try:
            with page.expect_response(
                lambda r: f"aweme_id={video_id}" in r.url and "aweme/detail" in r.url,
                timeout=15000
            ) as resp_info:
                page.goto(f"https://www.douyin.com/video/{video_id}",
                          wait_until="domcontentloaded", timeout=20000)

            data = resp_info.value.json()
            aweme = data.get("aweme_detail")
            if not aweme:
                return None

            # 用引擎的解析方法
            return _engine._parse_aweme(aweme, video_id)

        except Exception as e:
            log.warning("[CDP] 拦截失败: %s", e)
            return None

    finally:
        try:
            for pg in ctx.pages:
                if not pg.is_closed():
                    pg.close()
        except:
            pass
        if own:
            try:
                browser.close()
            except:
                pass
        try:
            pw.stop()
        except:
            pass


# ─── 工具函数 ──────────────────────────────────────────────

def extract_video_id(url_or_id):
    s = str(url_or_id).strip()
    # 分享链接中的 ID
    m = re.search(r'douyin\.com/video/(\d+)', s)
    if m:
        return m.group(1)
    # 纯数字 ID
    if s.isdigit() and len(s) >= 15:
        return s
    raise ValueError(f"无法提取视频 ID: {s}")


def sanitize_filename(name, max_len=80):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', name).strip()
    return re.sub(r'[\s_]+', ' ', name)[:max_len]


# ─── 文件下载 ──────────────────────────────────────────────

def download_file(url, save_path, cookie_str=None, label="下载"):
    """urllib 下载（不经过 CDP）"""
    headers = {
        "Referer": "https://www.douyin.com/",
        "User-Agent": UA,
    }
    if cookie_str:
        headers["Cookie"] = cookie_str

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.status == 403:
            raise RiskControlError(-403, "CDN 拒绝访问", action="cooldown")
        if resp.status != 200:
            return False

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(save_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    log.info("%s: %.0f%% (%.1fMB)", label, pct, downloaded/1024/1024)

    log.info("%s完成 (%.1f MB)", label, downloaded/1024/1024)
    return True


# ─── 获取视频详情（f2 优先，CDP fallback）─────────────────

def get_video_detail(video_id, cdp_url=None):
    """
    获取视频详情。优先 f2 纯 Python，失败则降级 CDP。
    """
    # 优先：f2 纯 Python
    try:
        info = _engine.fetch_detail_sync(video_id)
        if info:
            log.info("[f2] API 获取成功")
            return info
    except SignatureExpiredError:
        log.warning("[f2] 签名过期，降级到 CDP...")
    except RiskControlError as e:
        log.error("[f2] API 错误: %s", e)
    except Exception as e:
        log.error("[f2] 异常: %s", e)

    # 降级：CDP 浏览器拦截
    log.info("[CDP] 降级到浏览器模式...")
    info = _cdp_fetch_detail(video_id, cdp_url)
    if info:
        log.info("[CDP] 获取成功")
    return info


# ─── 用户视频列表 ──────────────────────────────────────────

def fetch_user_videos(sec_uid, max_pages=50, cdp_url=None):
    """
    获取用户全部视频列表。优先 f2 API，失败降级 CDP。
    """
    all_videos = []
    seen_ids = set()

    # 尝试 f2 API
    try:
        cursor = 0
        for page_num in range(1, max_pages + 1):
            log.info("第%d页 (f2)...", page_num)
            videos, cursor, has_more = asyncio.run(
                _engine.fetch_user_post(sec_uid, max_cursor=cursor, count=18)
            )
            new = [v for v in videos if v["video_id"] not in seen_ids]
            for v in new:
                seen_ids.add(v["video_id"])
            all_videos.extend(new)
            log.info("%d 个 (累计 %d)", len(new), len(all_videos))

            if not has_more or not new:
                break
            time.sleep(1 + random.uniform(0, 1))

        if all_videos:
            return all_videos

    except (SignatureExpiredError, RiskControlError) as e:
        log.warning("[f2] 列表获取失败: %s", e)
        log.info("降级到 CDP...")
    except Exception as e:
        log.error("[f2] 异常: %s", e)

    # CDP fallback
    return _cdp_fetch_user_videos(sec_uid, max_pages, cdp_url)


def _cdp_fetch_user_videos(sec_uid, max_pages, cdp_url=None):
    """CDP fallback：浏览器获取用户视频列表"""
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
        has_stealth = True
    except ImportError:
        has_stealth = False

    port = CDP_DEFAULT_PORT
    if cdp_url:
        m = re.search(r':(\d+)', cdp_url)
        if m:
            port = int(m.group(1))

    all_videos = []
    seen_ids = set()

    pw = sync_playwright().start()
    try:
        if detect_cdp(port):
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            own = False
        else:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA)
            own = True

        page = ctx.new_page()
        if own and has_stealth:
            Stealth().apply_stealth_sync(page)

        # 建立会话
        page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        # 第 1 页
        log.info("第1页 (CDP)...")
        try:
            with page.expect_response(
                lambda r: "aweme/v1/web/aweme/post" in r.url,
                timeout=15000
            ) as info:
                page.goto(f"https://www.douyin.com/user/{sec_uid}",
                          wait_until="domcontentloaded", timeout=20000)

            data = info.value.json()
            aweme_list = data.get("aweme_list") or []
            for a in aweme_list:
                vid = str(a.get("aweme_id", ""))
                if vid and vid not in seen_ids:
                    seen_ids.add(vid)
                    all_videos.append({
                        "video_id": vid,
                        "title": a.get("desc", vid),
                        "url": f"https://www.douyin.com/video/{vid}",
                        "duration": a.get("duration", 0) / 1000,
                        "author": a.get("author", {}).get("nickname", ""),
                    })
            has_more = data.get("has_more", False)
            log.info("%d 个 (累计 %d)", len(aweme_list), len(all_videos))
        except Exception as e:
            log.error("失败: %s", e)
            return all_videos

        # 翻页
        for pn in range(2, max_pages + 1):
            if not has_more:
                break
            log.info("第%d页 (CDP)...", pn)
            try:
                with page.expect_response(
                    lambda r: "aweme/v1/web/aweme/post" in r.url,
                    timeout=15000
                ) as info:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)

                data = info.value.json()
                aweme_list = data.get("aweme_list") or []
                for a in aweme_list:
                    vid = str(a.get("aweme_id", ""))
                    if vid and vid not in seen_ids:
                        seen_ids.add(vid)
                        all_videos.append({
                            "video_id": vid,
                            "title": a.get("desc", vid),
                            "url": f"https://www.douyin.com/video/{vid}",
                            "duration": a.get("duration", 0) / 1000,
                            "author": a.get("author", {}).get("nickname", ""),
                        })
                has_more = data.get("has_more", False)
                log.info("%d 个 (累计 %d)", len(aweme_list), len(all_videos))
            except:
                log.warning("超时，停止")
                break
            time.sleep(1 + random.uniform(0, 1))

    finally:
        try:
            for pg in ctx.pages:
                if not pg.is_closed():
                    pg.close()
        except:
            pass
        if own:
            try:
                browser.close()
            except:
                pass
        try:
            pw.stop()
        except:
            pass

    return all_videos


# ─── 下载入口 ──────────────────────────────────────────────

def download_video(video_id_or_url, output_dir, cdp_url=None):
    """下载单个抖音视频"""
    video_id = extract_video_id(video_id_or_url)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取视频详情（f2 优先，CDP fallback）
    info = get_video_detail(video_id, cdp_url)
    if not info:
        log.error("无法获取视频 %s", video_id)
        return False

    title = sanitize_filename(info["title"])
    log.info("[%s] %s (%.0fs)", info['author'], title[:50], info['duration'])
    log.info("画质选项: %d 个", info['bitrate_count'])

    # 选择下载 URL
    dl_url = info.get("no_watermark_url") or info["play_url"]
    label = "无水印" if info.get("no_watermark_url") else "有水印"

    save_path = output_dir / f"{title}.mp4"
    if save_path.exists():
        log.info("已存在: %s", save_path.name)
        return True

    # 用 f2 引擎的 cookie 下载
    _engine.ensure_tokens()
    return download_file(dl_url, save_path, cookie_str=_engine._cookie_str, label=label)


def batch_download(items, output_dir, cdp_url=None):
    """批量下载"""
    if len(items) > RATE_MAX_BATCH:
        log.warning("防风控: 截断到 %d", RATE_MAX_BATCH)
        items = items[:RATE_MAX_BATCH]

    log.info("%d 个视频待下载", len(items))
    success, failed, skipped = 0, 0, 0

    for i, item in enumerate(items, 1):
        log.info("%s", "=" * 50)
        vid = item.get("video_id") or item.get("url", "")
        title = item.get("title", vid)[:50]
        log.info("[%d/%d] %s", i, len(items), title)

        # 跳过已存在
        output_dir_path = Path(output_dir)
        existing = {f.stem[:25] for f in output_dir_path.glob("*.mp4")}
        safe_prefix = sanitize_filename(title)[:25]
        if safe_prefix in existing:
            log.info("已存在，跳过")
            skipped += 1
            continue

        max_retries = 3
        downloaded = False
        for attempt in range(1, max_retries + 1):
            try:
                # 获取详情
                info = get_video_detail(vid, cdp_url)
                if not info:
                    raise Exception("无法获取视频详情")

                t = sanitize_filename(info["title"])
                save_path = output_dir_path / f"{t}.mp4"
                dl_url = info.get("no_watermark_url") or info["play_url"]

                _engine.ensure_tokens()
                if download_file(dl_url, save_path,
                                cookie_str=_engine._cookie_str,
                                label="无水印" if info.get("no_watermark_url") else "下载"):
                    success += 1
                    _limiter.record_success()
                    downloaded = True
                    break
                else:
                    raise Exception("下载失败")

            except RiskControlError as e:
                log.warning("风控: %s", e)
                failed += 1
                _limiter.record_failure()
                if e.action == "stop":
                    save_remaining(items[i-1:], output_dir)
                    break
                time.sleep(20 * attempt)

            except Exception as e:
                err = str(e).lower()
                if attempt < max_retries:
                    log.warning("(尝试 %d/%d): %s", attempt, max_retries, e)
                    time.sleep(5 * attempt)
                    continue
                log.error("%s", e)
                failed += 1
                _limiter.record_failure()
                if _limiter.should_circuit_break:
                    log.critical("连续失败 %d 次，熔断！", _limiter._consecutive_fails)
                    save_remaining(items[i-1:], output_dir)
                    break
                break

        if i < len(items):
            _limiter.wait_for_download(i)

    log.info("成功 %d, 失败 %d, 跳过 %d", success, failed, skipped)


def save_remaining(items, output_dir):
    rf = Path(output_dir) / "_resume.json"
    rf.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("剩余 %d 个已保存: %s", len(items), rf)


# ─── 搜索 ──────────────────────────────────────────────────

def search_videos(keyword, max_results=20, cdp_url=None):
    """搜索抖音视频。优先 f2 API，失败降级 CDP。

    返回视频列表：[{video_id, title, url, duration, author, stats}, ...]
    """
    all_videos = []
    seen_ids = set()

    # 优先 f2 API
    try:
        offset = 0
        while len(all_videos) < max_results:
            count = min(15, max_results - len(all_videos))
            log.info("搜索 (f2): '%s' offset=%d...", keyword, offset)
            videos, next_offset, has_more = asyncio.run(
                _engine.fetch_search(keyword, offset=offset, count=count)
            )
            new = [v for v in videos if v["video_id"] not in seen_ids]
            for v in new:
                seen_ids.add(v["video_id"])
            all_videos.extend(new)
            log.info("%d 个 (累计 %d)", len(new), len(all_videos))

            if not has_more or not new or len(all_videos) >= max_results:
                break
            offset = next_offset
            time.sleep(1 + random.uniform(0, 1))

        if all_videos:
            return all_videos[:max_results]

    except (SignatureExpiredError, RiskControlError) as e:
        log.warning("[f2] 搜索失败: %s", e)
    except Exception as e:
        log.error("[f2] 搜索异常: %s", e)

    # CDP fallback
    log.info("降级到 CDP 搜索...")
    cdp_results = _cdp_search_videos(keyword, max_results, cdp_url)
    return cdp_results[:max_results]


def _cdp_search_videos(keyword, max_results, cdp_url=None):
    """CDP fallback：浏览器搜索抖音视频"""
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
        has_stealth = True
    except ImportError:
        has_stealth = False

    port = CDP_DEFAULT_PORT
    if cdp_url:
        m = re.search(r':(\d+)', cdp_url)
        if m:
            port = int(m.group(1))

    all_videos = []
    seen_ids = set()
    pw = sync_playwright().start()
    try:
        if detect_cdp(port):
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            own = False
        else:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA)
            own = True

        page = ctx.new_page()
        if own and has_stealth:
            Stealth().apply_stealth_sync(page)

        page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        # 搜索页
        search_url = f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}"
        log.info("[CDP] 打开搜索页...")
        try:
            with page.expect_response(
                lambda r: "aweme/v1/web/search/item" in r.url,
                timeout=15000
            ) as resp_info:
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

            data = resp_info.value.json()
            items = data.get("data") or []
            for item in items:
                aweme = item.get("aweme_info") or {}
                vid = str(aweme.get("aweme_id", ""))
                if vid and vid not in seen_ids:
                    seen_ids.add(vid)
                    all_videos.append({
                        "video_id": vid,
                        "title": aweme.get("desc", vid),
                        "url": f"https://www.douyin.com/video/{vid}",
                        "duration": (aweme.get("duration", 0) or 0) / 1000,
                        "author": (aweme.get("author", {}) or {}).get("nickname", ""),
                    })
            log.info("%d 个", len(all_videos))
        except Exception as e:
            log.error("失败: %s", e)

    finally:
        try:
            for pg in ctx.pages:
                if not pg.is_closed():
                    pg.close()
        except:
            pass
        if own:
            try:
                browser.close()
            except:
                pass
        try:
            pw.stop()
        except:
            pass

    return all_videos


# ─── 候选格式输出 ──────────────────────────────────────────

def output_candidates(results, keyword, output_file=None):
    candidates = []
    for i, r in enumerate(results, 1):
        candidates.append({
            "source": "douyin-video",
            "source_name": "Douyin (抖音)",
            "source_url": r["url"],
            "source_platform": "douyin",
            "resource_id": r["video_id"],
            "title": r["title"],
            "resource_type": "视频",
            "format": "mp4",
            "provider": r.get("author", ""),
            "downloadable": True,
            "metadata_confidence": 0.7,
            "raw": {"rank": i, **r},
        })
    data = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "douyin-video",
        "query": keyword,
        "searched_at": datetime.now().isoformat(),
        "candidates": candidates,
    }
    if output_file:
        Path(output_file).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("候选列表已保存: %s", output_file)
    return data


# ─── CLI ───────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="抖音视频下载器 (f2 引擎)")
    p.add_argument("--cdp", default=None, help="CDP fallback URL (auto/none/URL)")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("download", help="下载单个视频")
    d.add_argument("url", help="视频 URL 或 ID")
    d.add_argument("-o", "--output", default=".")
    d.add_argument("--cookie", default=None, help="Cookie 文件路径（可选）")

    b = sub.add_parser("batch", help="批量下载")
    b.add_argument("list_file", help="视频列表 JSON")
    b.add_argument("-o", "--output", default=".")

    u = sub.add_parser("user", help="下载用户全部视频")
    u.add_argument("uid", help="用户 sec_uid 或主页 URL")
    u.add_argument("-o", "--output", default=".")
    u.add_argument("--list-only", action="store_true", help="仅获取列表")

    s = sub.add_parser("search", help="搜索抖音视频")
    s.add_argument("keyword", help="搜索关键词")
    s.add_argument("--max", type=int, default=20, help="最大返回数（默认 20）")
    s.add_argument("-o", "--output", default=None, help="输出 candidate JSON 文件路径")

    args = p.parse_args()

    if args.cmd == "download":
        download_video(args.url, args.output, cdp_url=args.cdp)

    elif args.cmd == "batch":
        items = json.loads(Path(args.list_file).read_text(encoding="utf-8"))
        batch_download(items, args.output, cdp_url=args.cdp)

    elif args.cmd == "user":
        uid = args.uid.strip()
        m = re.search(r'douyin\.com/user/(\S+)', uid)
        if m:
            uid = m.group(1)

        videos = fetch_user_videos(uid, cdp_url=args.cdp)
        if videos:
            log.info("共 %d 个视频", len(videos))
            out = Path(args.output)
            out.mkdir(parents=True, exist_ok=True)
            list_file = out / f"douyin_user_{uid[:20]}_videos.json"
            list_file.write_text(json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("已保存: %s", list_file)

            if not args.list_only:
                batch_download(videos, args.output, cdp_url=args.cdp)
        else:
            log.error("未获取到视频列表")
            log.info("提示: 用户视频列表可能需要登录 cookie (sessionid)")
            log.info("可通过 --cdp http://127.0.0.1:9222 使用已登录的浏览器")

    elif args.cmd == "search":
        log.info("搜索抖音视频: '%s' (max=%d)", args.keyword, args.max)
        videos = search_videos(args.keyword, max_results=args.max, cdp_url=args.cdp)
        if videos:
            log.info("搜索到 %d 个视频", len(videos))
            output_candidates(videos, args.keyword, args.output)
            if not args.output:
                for i, v in enumerate(videos, 1):
                    log.info("[%d] [%s] %s...", i, v.get('author', '?'), v['title'][:40])
                    log.info("    %s", v['url'])
        else:
            log.warning("未搜索到结果（可能需要登录或被风控）")
            log.info("提示: 可通过 --cdp http://127.0.0.1:9222 使用已登录浏览器")

    else:
        p.print_help()


if __name__ == "__main__":
    main()
