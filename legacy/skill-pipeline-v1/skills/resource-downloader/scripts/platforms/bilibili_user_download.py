#!/usr/bin/env python3
"""
B站UP主全部视频下载
用法: python bilibili_user_dl.py <空间URL或UID> [-o 输出目录]
需要: CDP 浏览器已在 9222 端口运行（通过 browser_use 启动）

策略:
  1. 用 expect_response 拦截页面自身的 arc/search API
  2. 翻页点击"下一页"继续拦截，直到拿完全部
  3. 每个视频单独重连 CDP 下载（避免长时间连接断开）
"""

import sys
import re
import json
import time
import random
import argparse
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILLS_ROOT / "resource-platforms" / "scripts"))
sys.path.insert(0, str(SKILLS_ROOT / "resource-platforms" / "scripts" / "bilibili"))
sys.path.insert(0, str(Path(__file__).parent))
from bilibili_dl import (
    resolve_cdp_url, create_browser_context, cleanup,
    _do_download, RateLimiter, RiskControlError,
)

from shared.logger import getLogger
log = getLogger("bilibili")


def extract_uid(url_or_uid):
    s = str(url_or_uid).strip()
    m = re.search(r"space\.bilibili\.com/(\d+)", s)
    if m:
        return int(m.group(1))
    if s.isdigit():
        return int(s)
    raise ValueError(f"无法提取 UID: {s}")


def fetch_user_videos(page, uid):
    """
    通过 expect_response 拦截页面的 arc/search API 获取视频列表。
    同步等待，不依赖异步回调。
    """
    all_videos = []
    seen = set()

    def _extract(resp):
        """从 API 响应提取视频，返回 (list, total)"""
        if "arc/search" not in resp.url:
            return [], 0
        try:
            data = resp.json()
            if data.get("code") != 0:
                log.warning("API %s: %s", data.get("code"), data.get("message", ""))
                return [], 0
            vlist = data.get("data", {}).get("list", {}).get("vlist") or []
            total = data.get("data", {}).get("page", {}).get("count", 0)
            results = []
            for v in vlist:
                bv = v.get("bvid", "")
                if not bv or bv in seen:
                    continue
                seen.add(bv)
                results.append({
                    "bvid": bv,
                    "title": v.get("title", bv),
                    "url": f"https://www.bilibili.com/video/{bv}",
                    "duration": v.get("length", ""),
                    "play": v.get("play", 0),
                })
            return results, total
        except:
            return [], 0

    # 第1页: 导航并等待 API
    log.info("第 1 页...")
    with page.expect_response(lambda r: "arc/search" in r.url, timeout=30000) as info:
        page.goto(f"https://space.bilibili.com/{uid}/upload",
                  wait_until="domcontentloaded", timeout=30000)
    page1, total = _extract(info.value)
    all_videos.extend(page1)
    log.info("%d 个 (累计 %d/%d)", len(page1), len(all_videos), total)

    # 后续页（带重试）
    empty_page_count = 0
    for pn in range(2, 30):
        if total and len(all_videos) >= total:
            break

        # 查找"下一页"按钮
        try:
            btn = page.locator("text=下一页").first
            if not btn.is_visible(timeout=2000):
                log.info("第 %d 页: 没有下一页按钮，结束", pn)
                break
        except:
            log.info("第 %d 页: 下一页按钮不可见，结束", pn)
            break

        log.info("第 %d 页...", pn)
        page_videos = []
        got_response = False

        # 最多重试 3 次拿这一页的数据
        for retry in range(1, 4):
            try:
                with page.expect_response(lambda r: "arc/search" in r.url, timeout=15000) as info:
                    btn.click()
                page_videos, new_total = _extract(info.value)
                got_response = True

                if page_videos:
                    if new_total > 0:
                        total = new_total
                    all_videos.extend(page_videos)
                    empty_page_count = 0  # 重置空页计数
                    log.info("%d 个 (累计 %d/%d)", len(page_videos), len(all_videos), total)
                    break
                else:
                    # API 返回了但列表为空
                    if retry < 3:
                        log.debug("空 (重试 %d/3)...", retry)
                        time.sleep(2 * retry)
                        # 重新获取按钮引用（DOM 可能刷新了）
                        try:
                            btn = page.locator("text=下一页").first
                        except:
                            break
                    else:
                        empty_page_count += 1
                        log.info("空 (连续 %d 页无数据)", empty_page_count)
                        if empty_page_count >= 2:
                            log.info("连续多页无数据，停止翻页")
                            break
            except Exception as e:
                if retry < 3:
                    log.debug("超时 (重试 %d/3)...", retry)
                    time.sleep(3 * retry)
                else:
                    log.error("失败: %s", e)
                    break

        if not got_response:
            log.warning("连续重试失败，停止翻页")
            break

        time.sleep(1 + random.uniform(0, 1))

    return all_videos


def _find_remaining(videos, output_dir):
    """找出未下载的视频"""
    output_dir = Path(output_dir)
    existing_stems = {f.stem[:25] for f in output_dir.glob("*.mp4")}
    return [v for v in videos if v["title"][:25] not in existing_stems]


def main():
    parser = argparse.ArgumentParser(description="B站UP主全部视频下载")
    parser.add_argument("uid", help="UP主空间 URL 或 UID")
    parser.add_argument("-o", "--output", default=".", help="输出目录")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cdp", default=None)
    args = parser.parse_args()

    uid = extract_uid(args.uid)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cdp = resolve_cdp_url(args.cdp)
    if not cdp:
        log.error("需要真实浏览器（CDP）。请先通过 browser_use 启动 (cdp_port=9222)")
        return

    log.info("%s", "=" * 60)
    log.info("UP主 UID: %s", uid)
    log.info("输出目录: %s", output_dir)
    log.info("%s", "=" * 60)

    # === 阶段1: 获取视频列表 ===
    p, browser, context, page, own = create_browser_context(cdp)
    try:
        log.info("获取视频列表...")
        videos = fetch_user_videos(page, uid)
    finally:
        cleanup(p, browser, context, own)

    if not videos:
        log.info("未获取到视频")
        return

    log.info("共 %d 个视频", len(videos))
    for i, v in enumerate(videos[:10], 1):
        log.info("  %d. [%s] %s (%s)", i, v["bvid"], v["title"][:55], v.get("duration", ""))
    if len(videos) > 10:
        log.info("  ... 还有 %d 个", len(videos) - 10)

    # 保存列表
    list_file = output_dir / f"up_{uid}_videos.json"
    list_file.write_text(json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("列表已保存: %s", list_file)

    if args.list_only:
        return

    # === 阶段2: 过滤已下载 + 批量下载 ===
    to_download = _find_remaining(videos, output_dir)
    if args.limit:
        to_download = to_download[:args.limit]

    if not to_download:
        log.info("全部已下载！")
        return

    log.info("待下载 %d 个（已跳过 %d 个已有）", len(to_download), len(videos) - len(to_download))
    log.info("%s", "=" * 60)

    limiter = RateLimiter()
    success, failed, skipped = 0, 0, 0

    for i, v in enumerate(to_download, 1):
        log.info("[%d/%d] %s", i, len(to_download), v["title"][:50])

        # 跳过已存在（双重检查）
        existing = {f.stem[:25] for f in output_dir.glob("*.mp4")}
        safe_prefix = v["title"][:25]
        if safe_prefix in existing:
            log.info("已存在，跳过")
            skipped += 1
            continue

        # 浏览器崩溃恢复：最多重试 3 次
        max_browser_retries = 3
        downloaded = False
        for browser_attempt in range(1, max_browser_retries + 1):
            cdp = resolve_cdp_url(args.cdp)
            if not cdp:
                if browser_attempt < max_browser_retries:
                    wait = 10 * browser_attempt
                    log.warning("CDP 断连，%ds 后重试 (%d/%d)...", wait, browser_attempt, max_browser_retries)
                    time.sleep(wait)
                    continue
                else:
                    log.error("CDP 持续不可用，停止")
                    break

            p, browser, context, page, own = create_browser_context(cdp)
            try:
                _do_download(page, v["bvid"], str(output_dir))
                success += 1
                limiter.record_success()
                downloaded = True
                break
            except RiskControlError as e:
                log.warning("风控: %s", e)
                failed += 1
                limiter.record_failure()
                if e.action == "stop":
                    from bilibili_dl import save_remaining
                    save_remaining(to_download[i-1:], output_dir)
                    log.info("成功 %d, 失败 %d, 跳过 %d", success, failed, skipped)
                    return
                break
            except Exception as e:
                err_str = str(e).lower()
                is_crash = any(kw in err_str for kw in [
                    "disconnect", "connection", "closed", "target closed",
                    "browser closed", "transport", "timeout",
                ])
                if is_crash and browser_attempt < max_browser_retries:
                    wait = 10 * browser_attempt
                    log.warning("浏览器断连 (%d/%d)，%ds 后重连...", browser_attempt, max_browser_retries, wait)
                    time.sleep(wait)
                    continue
                else:
                    log.error("%s", e)
                    failed += 1
                    limiter.record_failure()
                    break
            finally:
                cleanup(p, browser, context, own)

        if limiter.should_circuit_break:
            log.critical("连续失败 %d 次，熔断！", limiter._consecutive_fails)
            from bilibili_dl import save_remaining
            save_remaining(to_download[i-1:], output_dir)
            break

        if i < len(to_download):
            limiter.wait_for_download(i)

    done = len(list(output_dir.glob("*.mp4")))
    log.info("%s", "=" * 60)
    log.info("本次: 成功 %d, 失败 %d, 跳过 %d", success, failed, skipped)
    log.info("目录: %d 个文件", done)
    if failed > 0:
        log.info("重跑命令即可续传（已有文件自动跳过）")


if __name__ == "__main__":
    main()
