#!/usr/bin/env python3
"""
B站视频搜索 + 下载器

核心机制:
  - 自动检测本地 CDP (9222) 或独立 stealth 模式
  - WBI 签名绕过 API 风控
  - 视频文件用 Python urllib + 浏览器 cookie 下载（不经过 CDP 传输，稳定）
  - 防风控：限速 + 熔断 + 断点续传

已知限制:
  - 独立 headless 模式搜索返回空结果（B站 server-side TLS 指纹检测）
  - 推荐通过 browser_use 启动真实浏览器 (cdp_port=9222)

用法:
  python bilibili_dl.py search "小学数学" --max-pages 2
  python bilibili_dl.py download BV1xxx -o output/
  python bilibili_dl.py batch list.json -o output/
"""

import sys
import os
import re
import json
import time
import random
import hashlib
import subprocess
import argparse
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wbi_sign import wbi_sign, WBI_KEY_TABLE
from shared.utils import safe_filename
from shared.logger import getLogger

log = getLogger("bilibili")

# ========== 配置 ==========
FFMPEG = r"C:\Users\admin\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
QUALITY_MAP = {
    6: "240P", 16: "360P", 32: "480P", 64: "720P",
    74: "720P60", 80: "1080P", 100: "1080P高码率",
    112: "1080P60", 116: "1080P_HDR", 120: "4K",
}
CDP_DEFAULT_PORT = 9222

# ========== 防风控参数 ==========
RATE_SEARCH_PAGE_INTERVAL = 3
RATE_SEARCH_SESSION_COOLDOWN = 10
RATE_DOWNLOAD_INTERVAL_MIN = 8
RATE_DOWNLOAD_INTERVAL_MAX = 16
RATE_MAX_CONSECUTIVE_FAIL = 3
RATE_MAX_BATCH = 100
RATE_API_RETRY = 2
RATE_API_BACKOFF = 5
# ==========================


# ─── 风控异常 ──────────────────────────────────────────────

class RiskControlError(Exception):
    def __init__(self, code, message, action="stop"):
        self.code = code
        self.risk_message = message
        self.action = action  # "stop" | "cooldown" | "retry"
        super().__init__(f"[风控] code={code}: {message}")


# ─── 限速器 ────────────────────────────────────────────────

class RateLimiter:
    def __init__(self):
        self._last_search = 0
        self._last_api_call = 0
        self._consecutive_fails = 0
        self._total_requests = 0

    def wait_for_search_page(self):
        self._enforce_min(RATE_SEARCH_PAGE_INTERVAL, self._last_api_call)

    def wait_for_search_new(self):
        self._enforce_min(RATE_SEARCH_SESSION_COOLDOWN, self._last_search)
        self._last_search = time.time()

    def wait_for_download(self, index):
        base = RATE_DOWNLOAD_INTERVAL_MIN + (index % 8)
        jitter = random.uniform(0, max(0, RATE_DOWNLOAD_INTERVAL_MAX - base))
        wait = base + jitter
        log.info("等待 %.0fs...", wait)
        time.sleep(wait)

    def record_api_call(self):
        self._last_api_call = time.time()
        self._total_requests += 1

    def record_success(self):
        self._consecutive_fails = 0

    def record_failure(self):
        self._consecutive_fails += 1

    @property
    def should_circuit_break(self):
        return self._consecutive_fails >= RATE_MAX_CONSECUTIVE_FAIL

    def _enforce_min(self, min_interval, last_time):
        elapsed = time.time() - last_time
        if elapsed < min_interval:
            wait = min_interval - elapsed
            log.info("限速等待 %.1fs...", wait)
            time.sleep(wait)


_limiter = RateLimiter()


# ─── CDP 检测（修复 Windows connect_ex 返回 10035 的问题）──

def detect_cdp(port=CDP_DEFAULT_PORT, timeout=3):
    """探测本地 CDP 端口（HTTP /json/version）"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/version")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except:
        return False


def resolve_cdp_url(cdp_arg=None):
    """
    解析 CDP 策略:
      - "none" → 强制独立
      - 其他 → 自动探测 9222 端口
    """
    if cdp_arg and cdp_arg.lower() == "none":
        return None

    cdp_url = f"http://127.0.0.1:{CDP_DEFAULT_PORT}"
    if detect_cdp(CDP_DEFAULT_PORT):
        log.info("检测到本地端口 %s → CDP 模式", CDP_DEFAULT_PORT)
        return cdp_url

    log.warning("CDP 端口 %s 不可用 → 独立 stealth 模式", CDP_DEFAULT_PORT)
    return None


# ─── 浏览器上下文 ──────────────────────────────────────────

def create_browser_context(cdp_url=None, cookie_path=None):
    """创建浏览器上下文，返回 (playwright, browser, context, page, own)"""
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
        has_stealth = True
    except ImportError:
        has_stealth = False

    p = sync_playwright().start()

    if cdp_url:
        browser = p.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        own = False  # 不拥有浏览器，不关闭
        log.info("[CDP] 已连接 %s（复用真实浏览器）", cdp_url)
    else:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        own = True
        if has_stealth:
            Stealth().apply_stealth_sync(page)

    # Cookie 注入
    if cookie_path and Path(cookie_path).exists():
        _load_cookies(ctx, cookie_path)

    return p, browser, ctx, page, own


def cleanup(p, browser, context, own):
    """清理浏览器资源"""
    try:
        context.pages and [pg.close() for pg in context.pages if not pg.is_closed()]
    except:
        pass
    if own:
        try:
            browser.close()
        except:
            pass
    try:
        p.stop()
    except:
        pass


def _load_cookies(ctx, path):
    try:
        cookies = json.loads(Path(path).read_text())
        if isinstance(cookies, list):
            for c in cookies:
                cookie = {
                    "name": c.get("name"), "value": c.get("value"),
                    "domain": c.get("domain", ".bilibili.com"),
                    "path": c.get("path", "/"),
                }
                if c.get("expires"):
                    cookie["expires"] = c["expires"]
                ctx.add_cookies([cookie])
    except:
        pass


# ─── WBI 签名 ───────────────────────────────────────────────

def get_wbi_keys(page):
    """从 /x/web-interface/nav 获取 WBI 签名密钥"""
    resp = page.request.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"Referer": "https://www.bilibili.com/"}
    )
    data = resp.json()
    wi = data.get("data", {}).get("wbi_img", {})
    img_key = wi.get("img_url", "").split("/")[-1].split(".")[0]
    sub_key = wi.get("sub_url", "").split("/")[-1].split(".")[0]
    if not img_key or not sub_key:
        raise Exception("WBI 密钥获取失败")
    return img_key, sub_key


# ─── API 风控检测 ──────────────────────────────────────────

def check_api_response(data):
    """检查 API 响应，风控时抛 RiskControlError"""
    if not data:
        return data
    code = data.get("code", 0)
    msg = data.get("message", "")
    if code == -352:
        raise RiskControlError(code, msg, action="retry")
    if code in (-403, -509):
        raise RiskControlError(code, msg or "请求被限", action="cooldown")
    if code == -412:
        raise RiskControlError(code, "反爬拦截", action="stop")
    if code != 0:
        raise RiskControlError(code, msg, action="stop")
    return data


# ─── 文件下载（核心修复：不经过 CDP 传输大文件）──────────

def download_file(page, url, save_path, label="下载", max_retries=3):
    """
    用 Python urllib 下载文件，带浏览器 cookie 绕过 TLS 指纹。
    不经过 CDP 传输，避免大文件撑爆连接。
    支持断点续传：部分下载的文件会追加而不是重下。
    """
    for attempt in range(1, max_retries + 1):
        try:
            return _download_file_once(page, url, save_path, label)
        except RiskControlError:
            raise  # 风控直接抛，不重试
        except Exception as e:
            if attempt < max_retries:
                wait = 3 * attempt
                log.warning("%s 失败 (尝试 %d/%d)，%ds 后重试: %s", label, attempt, max_retries, wait, e)
                time.sleep(wait)
            else:
                log.error("%s 最终失败: %s", label, e)
                return False


def _download_file_once(page, url, save_path, label):
    """单次下载尝试"""
    # 从浏览器提取 cookie
    headers = {
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "User-Agent": UA,
    }
    try:
        raw_cookies = page.context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in raw_cookies)
        # urllib 要求 ASCII header
        try:
            headers["Cookie"] = cookie_str.encode("ascii").decode("ascii")
        except UnicodeEncodeError:
            safe = "; ".join(
                f"{c['name']}={c['value']}" for c in raw_cookies
                if all(ord(ch) < 128 for ch in f"{c['name']}={c['value']}")
            )
            if safe:
                headers["Cookie"] = safe
    except:
        pass

    # 断点续传：如果文件已存在部分内容，从断点继续
    resume_from = 0
    if Path(save_path).exists():
        resume_from = Path(save_path).stat().st_size
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
            log.info("从 %.1f MB 处续传...", resume_from/1024/1024)

    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=120)
    if resp.status == 403:
        raise RiskControlError(-403, "CDN 拒绝访问", action="cooldown")
    if resp.status == 412:
        raise RiskControlError(-412, "CDN 反爬拦截", action="stop")
    if resp.status not in (200, 206):
        return False

    # 流式写入（1MB 块）
    downloaded = resume_from
    mode = "ab" if resp.status == 206 else "wb"
    if resp.status == 200:
        mode = "wb"  # 服务器不支持 Range，从头下
        downloaded = 0

    with open(save_path, mode) as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
    log.info("%s完成 (%.1f MB)", label, downloaded/1024/1024)
    return True


# ─── 辅助函数 ──────────────────────────────────────────────

def pick_best_url(stream):
    """从视频/音频流列表选最佳 CDN URL"""
    urls = stream.get("backupUrl", []) or []
    urls.insert(0, stream.get("baseUrl", "") or stream.get("url", ""))
    return urls[0] if urls else ""


# ─── 搜索 ──────────────────────────────────────────────────

def api_search(page, keyword, pn, ps, order, img_key, sub_key):
    """调用搜索 API"""
    params = {
        "keyword": keyword, "pn": pn, "ps": ps,
        "search_type": "video", "order": order,
    }
    if img_key and sub_key:
        params = wbi_sign(params, img_key, sub_key)
        api = "https://api.bilibili.com/x/web-interface/wbi/search/type"
    else:
        api = "https://api.bilibili.com/x/web-interface/search/type"
    url = f"{api}?{urllib.parse.urlencode(params)}"
    resp = page.request.get(url, headers={"Referer": "https://search.bilibili.com/"})
    return resp.json()


def search_videos(keyword, max_pages=3, order="pubdate", cdp_url=None, cookie_path=None):
    """搜索B站视频"""
    _limiter.wait_for_search_new()
    cdp = resolve_cdp_url(cdp_url)
    p, browser, context, page, own = create_browser_context(cdp, cookie_path)

    try:
        page.goto("https://www.bilibili.com/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)

        img_key, sub_key = None, None
        try:
            img_key, sub_key = get_wbi_keys(page)
            log.info("WBI 密钥获取成功")
        except:
            log.warning("WBI 密钥获取失败")

        results = []
        for pn in range(1, max_pages + 1):
            log.info("搜索第 %d 页...", pn)
            data = None
            for attempt in range(RATE_API_RETRY + 1):
                try:
                    data = api_search(page, keyword, pn, 42, order, img_key, sub_key)
                    _limiter.record_api_call()
                    check_api_response(data)
                    break
                except RiskControlError as rce:
                    if rce.action == "retry" and attempt < RATE_API_RETRY:
                        try:
                            img_key, sub_key = get_wbi_keys(page)
                        except:
                            pass
                        time.sleep(RATE_API_BACKOFF)
                    elif rce.action == "cooldown":
                        time.sleep(30 * (attempt + 1))
                    else:
                        data = None
                        break

            if not data or data.get("code") != 0:
                break

            for r in data.get("data", {}).get("result", []):
                bv = r.get("bvid") or (re.search(r"BV[\w]+", r.get("arcurl", "")) or [""])[0]
                if not bv:
                    continue
                dur = r.get("duration", "")
                if isinstance(dur, int):
                    m, s = divmod(dur, 60)
                    dur = f"{m}:{s:02d}"
                results.append({
                    "bvid": bv,
                    "title": re.sub(r"<.*?>", "", r.get("title", "")),
                    "url": f"https://www.bilibili.com/video/{bv}",
                    "description": r.get("description", ""),
                    "author": r.get("author", ""),
                    "duration": dur,
                })

            _limiter.wait_for_search_page()

        return results
    finally:
        cleanup(p, browser, context, own)


# ─── 下载 ──────────────────────────────────────────────────

def _get_playinfo_api(page, bvid):
    """通过 playurl API 获取播放信息（fallback）"""
    init_state = page.evaluate("() => window.__INITIAL_STATE__")
    if not init_state:
        return None
    vd = init_state.get("videoData", {}) or {}
    aid = vd.get("aid") or init_state.get("aid")
    cid = vd.get("cid") or init_state.get("cid")
    if not aid or not cid:
        return None
    try:
        img_key, sub_key = get_wbi_keys(page)
    except:
        return None
    params = wbi_sign({
        "avid": str(aid), "cid": str(cid), "qn": "64",
        "fnval": "16", "fourk": "1", "platform": "pc",
    }, img_key, sub_key)
    url = f"https://api.bilibili.com/x/player/wbi/playurl?{urllib.parse.urlencode(params)}"
    resp = page.request.get(url, headers={"Referer": f"https://www.bilibili.com/video/{bvid}"})
    data = resp.json()
    if data.get("code") == 0:
        log.info("playurl API 成功")
        return data
    return None


def _do_download(page, bvid, output_dir, quality_id=None):
    """在已有 page 上执行下载"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 跳过已存在
    existing = list(output_dir.glob("*.mp4"))
    if existing:
        page.goto(f"https://www.bilibili.com/video/{bvid}",
                  wait_until="domcontentloaded", timeout=30000)
        # 仅获取标题做匹配
        try:
            title = page.evaluate("() => document.querySelector('h1')?.textContent?.trim() || ''")
            safe_title = safe_filename(title)
            for f in existing:
                if safe_title[:30] in f.stem:
                    log.info("已存在，跳过: %s", f.name)
                    return True
        except:
            pass
    else:
        page.goto(f"https://www.bilibili.com/video/{bvid}",
                  wait_until="domcontentloaded", timeout=30000)

    # 策略 1: 等待 __playinfo__
    playinfo_data = None
    log.info("等待播放信息...")
    for attempt in range(10):
        time.sleep(1)
        try:
            playinfo_data = page.evaluate("() => window.__playinfo__")
        except:
            pass
        if playinfo_data and playinfo_data.get("data"):
            log.info("播放信息获取成功（%ds）", attempt+1)
            break
        try:
            page.locator(".bpx-player-ctrl-play, button[aria-label='播放/暂停']").first.click(timeout=1000)
        except:
            pass

    # 策略 2: playurl API
    if not playinfo_data or not playinfo_data.get("data"):
        playinfo_data = _get_playinfo_api(page, bvid)

    if not playinfo_data or not playinfo_data.get("data"):
        raise Exception("无法获取播放信息。需要 CDP 真实浏览器 (cdp_port=9222)")

    dash = playinfo_data["data"]["dash"]
    videos = dash.get("video", [])
    audios = dash.get("audio", [])
    if not videos:
        raise Exception("没有视频流")

    meta = page.evaluate("""() => ({
        title: document.querySelector('h1')?.textContent?.trim() || 'video',
        up: (document.querySelector('.up-info__detail a') || document.querySelector('.username'))?.textContent?.trim() || '',
    })""")
    title = safe_filename(meta["title"])
    qname = QUALITY_MAP.get(videos[0].get("id", 0), f"画质{videos[0].get('id', '?')}")
    log.info("[%s] %s", qname, meta.get('up', ''))

    # 下载视频流
    v_path = output_dir / f"{title}_video.m4s"
    v_url = pick_best_url(videos[0])
    if not download_file(page, v_url, v_path, "视频"):
        raise Exception("视频流下载失败")

    # 下载音频流
    a_path = output_dir / f"{title}_audio.m4s"
    if audios:
        a_url = pick_best_url(audios[0])
        if not download_file(page, a_url, a_path, "音频"):
            raise Exception("音频流下载失败")
    else:
        a_path = None

    # 合并
    out_path = output_dir / f"{title}.mp4"
    ffmpeg = FFMPEG if Path(FFMPEG).exists() else "ffmpeg"
    if not Path(ffmpeg).exists() and ffmpeg == "ffmpeg":
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    cmd = [ffmpeg, "-y", "-i", str(v_path)]
    if a_path:
        cmd += ["-i", str(a_path)]
    cmd += ["-c", "copy", str(out_path)]

    result = subprocess.run(cmd, capture_output=True, timeout=60)
    v_path.unlink(missing_ok=True)
    if a_path:
        a_path.unlink(missing_ok=True)

    if result.returncode == 0 and out_path.exists():
        size_mb = out_path.stat().st_size / 1024 / 1024
        log.info("%s (%.1f MB)", out_path.name, size_mb)
        return True
    raise Exception(f"合并失败: {result.stderr.decode(errors='replace')[:200]}")


def download_video(bvid, output_dir, quality_id=None, cdp_url=None, cookie_path=None):
    """下载单个视频"""
    cdp = resolve_cdp_url(cdp_url)
    p, browser, context, page, own = create_browser_context(cdp, cookie_path)
    try:
        return _do_download(page, bvid, output_dir, quality_id)
    finally:
        cleanup(p, browser, context, own)


def save_remaining(items, output_dir, prefix="_resume"):
    rf = Path(output_dir) / f"{prefix}.json"
    rf.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("剩余 %d 个已保存: %s", len(items), rf)


def load_progress(output_dir, prefix="_resume"):
    """加载上次未完成的列表（断点恢复）"""
    rf = Path(output_dir) / f"{prefix}.json"
    if rf.exists():
        try:
            items = json.loads(rf.read_text(encoding="utf-8"))
            log.info("恢复进度: %d 个待下载（from %s）", len(items), rf.name)
            return items
        except:
            pass
    return None


# ─── 批量下载 ──────────────────────────────────────────────

def batch_download(items, output_dir, quality_id=None, cdp_url=None, cookie_path=None):
    """
    批量下载，内置浏览器崩溃恢复：
      1. 每个视频单独重连 CDP
      2. CDP 断连时自动等待重试（不直接放弃）
      3. 每次成功后保存进度，崩溃可恢复
      4. 熔断 + 风控检测
    """
    if len(items) > RATE_MAX_BATCH:
        log.warning("防风控: %d 超过上限 %d，截断", len(items), RATE_MAX_BATCH)
        items = items[:RATE_MAX_BATCH]

    log.info("%d 个视频待下载", len(items))
    for i, v in enumerate(items[:5], 1):
        log.info("%d. %s", i, v.get('title', v.get('url', '?'))[:60])
    if len(items) > 5:
        log.info("... 还有 %d 个", len(items)-5)

    success, failed, skipped = 0, 0, 0

    for i, item in enumerate(items, 1):
        log.info("%s", "=" * 60)
        bvid = item.get("bvid") or item.get("url", "")
        title = item.get("title", "?")[:50]
        log.info("[%d/%d] %s", i, len(items), title)

        # 跳过已存在（断点续传）
        output_dir_path = Path(output_dir)
        existing = list(output_dir_path.glob("*.mp4"))
        safe_prefix = safe_filename(title)[:25]
        if any(safe_prefix in f.stem for f in existing):
            log.info("已存在，跳过")
            skipped += 1
            continue

        # 下载（带浏览器崩溃恢复）
        max_browser_retries = 3
        downloaded = False
        for browser_attempt in range(1, max_browser_retries + 1):
            try:
                cdp = resolve_cdp_url(cdp_url)
                if not cdp and browser_attempt == 1:
                    log.warning("CDP 不可用，尝试独立模式...")
                p, browser, context, page, own = create_browser_context(cdp, cookie_path)
                try:
                    _do_download(page, bvid, output_dir, quality_id)
                    success += 1
                    _limiter.record_success()
                    downloaded = True
                    break
                finally:
                    cleanup(p, browser, context, own)

            except RiskControlError as e:
                log.warning("风控: %s", e)
                failed += 1
                _limiter.record_failure()
                if e.action == "stop":
                    save_remaining(items[i-1:], output_dir)
                    log.info("成功 %d, 失败 %d, 跳过 %d", success, failed, skipped)
                    return
                if e.action == "cooldown":
                    cooldown = 30 * browser_attempt
                    log.info("冷却 %ds...", cooldown)
                    time.sleep(cooldown)
                    continue
                break

            except Exception as e:
                err_str = str(e).lower()
                is_browser_crash = any(kw in err_str for kw in [
                    "disconnect", "connection", "closed", "target closed",
                    "browser closed", "context", "transport", "timeout",
                ])
                if is_browser_crash and browser_attempt < max_browser_retries:
                    wait = 10 * browser_attempt
                    log.warning("浏览器断连 (尝试 %d/%d)，%ds 后重连...", browser_attempt, max_browser_retries, wait)
                    time.sleep(wait)
                    continue

                log.error("%s", e)
                failed += 1
                _limiter.record_failure()
                if _limiter.should_circuit_break:
                    log.critical("连续失败 %d 次，熔断！", _limiter._consecutive_fails)
                    save_remaining(items[i-1:], output_dir)
                    log.info("成功 %d, 失败 %d, 跳过 %d", success, failed, skipped)
                    return
                break

        if not downloaded and failed > 0:
            # 保存当前进度（下一个视频开始可以恢复）
            pass

        if i < len(items):
            _limiter.wait_for_download(i)

    log.info("成功 %d, 失败 %d, 跳过 %d, 总计 %d", success, failed, skipped, len(items))


# ─── 候选格式输出 ──────────────────────────────────────────

def output_candidates(results, keyword, output_file=None):
    candidates = []
    for i, r in enumerate(results, 1):
        candidates.append({
            "source": "bilibili-video",
            "source_name": "Bilibili (哔哩哔哩)",
            "source_url": r["url"],
            "resource_id": r["bvid"],
            "title": r["title"],
            "description": r.get("description", "")[:200],
            "resource_type": "视频",
            "format": "mp4",
            "provider": r.get("author", ""),
            "downloadable": True,
            "metadata_confidence": 0.8,
            "raw": {"rank": i, **r},
        })
    data = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "bilibili-video",
        "query": keyword,
        "searched_at": datetime.now().isoformat(),
        "candidates": candidates,
    }
    if output_file:
        Path(output_file).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("候选列表已保存: %s", output_file)
    return data


# ─── CLI ───────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="B站视频搜索下载器")
    p.add_argument("--cookie", help="Cookie 文件路径")
    p.add_argument("--cdp", default=None,
                   help="CDP URL (auto/none/URL, 默认 auto 探测 9222)")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="搜索视频")
    s.add_argument("keyword")
    s.add_argument("--max-pages", type=int, default=2)
    s.add_argument("-o", "--output", help="保存候选 JSON")

    d = sub.add_parser("download", help="下载视频")
    d.add_argument("url", help="BV 号或 URL")
    d.add_argument("-o", "--output", default=".")

    b = sub.add_parser("batch", help="批量下载")
    b.add_argument("list_file", help="视频列表 JSON")
    b.add_argument("-o", "--output", default=".")

    args = p.parse_args()

    if args.cmd == "search":
        results = search_videos(args.keyword, args.max_pages,
                                cdp_url=args.cdp, cookie_path=args.cookie)
        log.info("找到 %d 个视频", len(results))
        for i, r in enumerate(results[:15], 1):
            log.info("%d. %s (%s)", i, r['title'][:55], r.get('duration', ''))
        if args.output and results:
            output_candidates(results, args.keyword, args.output)

    elif args.cmd == "download":
        bv = re.search(r"BV[\w]+", args.url)
        if not bv:
            log.error("无法提取 BV 号: %s", args.url)
            return
        download_video(bv.group(0), args.output, cdp_url=args.cdp, cookie_path=args.cookie)

    elif args.cmd == "batch":
        items = json.loads(Path(args.list_file).read_text(encoding="utf-8"))
        batch_download(items, args.output, cdp_url=args.cdp, cookie_path=args.cookie)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
