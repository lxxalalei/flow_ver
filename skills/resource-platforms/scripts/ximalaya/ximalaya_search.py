#!/usr/bin/env python3
"""喜马拉雅搜索脚本 — 基于喜马拉雅站内搜索 API，输出标准 candidate JSON。

搜索策略（双路径）：
  1. 优先用官方 revision/search 主接口（公开 JSON API，无需登录/Cookie/签名）
  2. 接口异常时降级为 M站 search 接口（apis.netstart.cn 镜像，CSRF 伪造请求头）

支持搜索两种 core 类型：
  - album（专辑）→ 资源类型「音频」，source_url 指向专辑页
  - track（声音）→ 资源类型「音频」，source_url 指向单条声音页

输出由 adapter 归一化，接口见 resource-platforms/references/search-interface.md：
  resource_id / title / source_url / platform 为必填字段。

用法:
  python ximalaya_search.py search "小学必背古诗" --max 20 -o candidates.json
  python ximalaya_search.py search "儿歌 童谣" --core track --max 15
  python ximalaya_search.py search "英语启蒙" --free-only --max 20

依赖:
  - httpx（可选，有则用；无则降级 urllib）
  - 无需浏览器，无需登录
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

for path in (Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent.parent.parent):
    sys.path.insert(0, str(path))

from shared.logger import getLogger
from shared.http_client import urlopen_with_fallback

log = getLogger("ximalaya")

# ========== 配置 ==========

# 主搜索接口（官方，最稳定）
SEARCH_MAIN_API = "https://www.ximalaya.com/revision/search"

# M站镜像接口（降级用）
SEARCH_MIRROR_API = "https://apis.netstart.cn/ximalaya/search"

# 专辑详情页 URL 前缀
ALBUM_URL_PREFIX = "https://www.ximalaya.com/album/"
# 声音详情页 URL 前缀
TRACK_URL_PREFIX = "https://www.ximalaya.com/sound/"

# 封面图 CDN 前缀（接口返回的是 // 开头的协议相对 URL）
COVER_CDN = "https:"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# 喜马拉雅分类映射（category_id → 中文主题）
# 儿童相关分类：儿歌(17)、睡前故事(11)、国学(28)、童话(12)、英语(21)
CATEGORY_MAP = {
    "17": "儿歌",
    "11": "睡前故事",
    "28": "国学",
    "12": "童话",
    "21": "英语",
    "3": "有声书",
    "10": "教育培训",
    "14": "情感生活",
    "2": "通俗小说",
    "13": "历史",
    "1006": "生活",
    "1005": "其他",
}

# 儿童内容相关分类关键词（用于 subject 推断）
CHILD_CATEGORY_KEYWORDS = {
    "儿歌": ["儿歌", "童谣", "宝宝", "幼儿"],
    "睡前故事": ["睡前", "故事", "童话"],
    "国学": ["国学", "古诗", "诗词", "三字经", "弟子规", "论语"],
    "英语": ["英语", "英文", "启蒙"],
    "科普": ["科普", "十万个为什么", "百科", "知识"],
    "语文": ["语文", "拼音", "识字", "阅读"],
    "数学": ["数学", "算术", "思维"],
}
# ==========================


def _build_headers(cookie: str | None = None) -> dict[str, str]:
    """构建请求头。喜马拉雅搜索接口公开，无需登录 Cookie。"""
    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.ximalaya.com/",
    }
    # Cookie 可选（有则传入，可获取个性化结果，但不强制）
    cookie = cookie or os.environ.get("XIMALAYA_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    return headers


# ─── 主搜索接口（revision/search）──────────────────────────────


def search_via_main_api(
    keyword: str,
    core: str = "album",
    max_results: int = 20,
    cookie: str | None = None,
    free_only: bool = False,
    sort_by: str = "relevance",
) -> list[dict[str, Any]]:
    """通过喜马拉雅官方 revision/search 接口搜索。

    Args:
        keyword: 搜索关键词
        core: 搜索类型，album（专辑）或 track（声音）
        max_results: 最大返回数
        cookie: 可选 Cookie（增强个性化，不强制）
        free_only: 是否只返回免费内容
        sort_by: 排序方式 relevance/popularity/newest

    Returns:
        标准 candidate 列表
    """
    headers = _build_headers(cookie)
    candidates: list[dict[str, Any]] = []

    # 排序映射：relevance→relation, popularity→play, newest→time
    condition_map = {"relevance": "relation", "popularity": "play", "newest": "time"}
    condition = condition_map.get(sort_by, "relation")

    page = 1
    rows = min(max_results, 20)  # 单页最多 20 条

    while len(candidates) < max_results:
        params: dict[str, str] = {
            "core": core,
            "kw": keyword,
            "page": str(page),
            "rows": str(rows),
            "condition": condition,
            "device": "web",
            "spellchecker": "true",
        }
        # 免费过滤
        if free_only:
            params["fq"] = "is_paid:false,"

        url = f"{SEARCH_MAIN_API}?{urllib.parse.urlencode(params)}"
        log.info("主接口搜索: core=%s page=%d kw='%s'", core, page, keyword)

        try:
            req = urllib.request.Request(url, headers=headers)
            with urlopen_with_fallback(req, timeout=15) as resp:
                if resp.status != 200:
                    log.warning("主接口返回 HTTP %d", resp.status)
                    break
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
        except Exception as exc:
            log.error("主接口请求失败: %s", exc)
            break

        # 检查返回码
        ret = data.get("ret")
        if ret != 200:
            log.warning("主接口返回错误码 ret=%s, msg=%s", ret, data.get("msg"))
            break

        # 解析结果
        try:
            response = data["data"]["result"]["response"]
            docs = response.get("docs") or []
            total_found = response.get("numFound", 0)
            total_page = response.get("totalPage", 0)
        except (KeyError, TypeError):
            log.error("主接口响应结构异常")
            break

        if not docs:
            log.info("主接口无更多结果")
            break

        for doc in docs:
            cand = _parse_main_doc(doc, core)
            if cand:
                candidates.append(cand)
                if len(candidates) >= max_results:
                    break

        # 翻页判断
        if page >= total_page:
            break
        page += 1
        # 请求间隔，避免触发频率限制
        time.sleep(0.5)

    log.info("主接口搜索返回 %d 条候选（core=%s）", len(candidates), core)
    return candidates[:max_results]


def _parse_main_doc(doc: dict[str, Any], core: str) -> dict[str, Any] | None:
    """解析 revision/search 返回的单条结果为标准 candidate。"""
    resource_id = str(doc.get("id") or "")
    if not resource_id:
        return None

    title = _clean_html(doc.get("title") or doc.get("richTitle") or "无标题")
    # 构建 URL
    if core == "track":
        # 声音类型：url 字段可能是 /track/xxx 或 /sound/xxx
        raw_url = doc.get("url") or ""
        if raw_url:
            source_url = _normalize_ximalaya_url(raw_url, "track", resource_id)
        else:
            source_url = f"{TRACK_URL_PREFIX}{resource_id}"
    else:
        # 专辑类型
        raw_url = doc.get("url") or ""
        if raw_url:
            source_url = _normalize_ximalaya_url(raw_url, "album", resource_id)
        else:
            source_url = f"{ALBUM_URL_PREFIX}{resource_id}"

    # 简介
    intro = doc.get("intro") or doc.get("custom_title") or ""
    intro = _clean_html(intro).strip()[:300]

    # 分类
    category_title = doc.get("category_title") or ""
    category_id = str(doc.get("category_id") or "")
    subject = _infer_subject(title, intro, category_title, category_id)

    # 付费状态
    is_paid = doc.get("is_paid", False)
    is_vip_free = doc.get("isVipFree", False)

    # 播放量
    play_count = doc.get("play")
    if isinstance(play_count, str):
        try:
            play_count = int(play_count)
        except ValueError:
            play_count = None

    # 评论数
    comments = doc.get("count_comment") or doc.get("comments_count") or 0

    # 评分
    score = doc.get("score")

    # 主播信息
    nickname = doc.get("nickname") or ""
    is_verified = doc.get("is_v", False)

    # 封面
    cover_path = doc.get("cover_path") or ""
    if cover_path and not cover_path.startswith("http"):
        cover_path = COVER_CDN + cover_path

    # 是否完结
    is_finished = doc.get("is_finished")
    finished_status = ""
    if is_finished == 1:
        finished_status = "已完结"
    elif is_finished == 0:
        finished_status = "连载中"

    # 集数（专辑）
    tracks_count = doc.get("tracks") or 0

    # 标签
    tags_str = doc.get("tags") or ""
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    # 创建/更新时间（毫秒时间戳 → ISO）
    created_at = _ms_to_iso(doc.get("created_at"))
    updated_at = _ms_to_iso(doc.get("updated_at"))

    # 平台原生质量信号；最终评分由 resource-selector 统一完成。
    quality_score, quality_level = _estimate_quality(
        play_count=play_count,
        score=score,
        is_verified=is_verified,
        is_paid=is_paid,
        tracks_count=tracks_count,
    )

    # 下载可行性
    download_feasibility = _estimate_feasibility(is_paid, is_vip_free)

    # resource_type 统一为「音频」
    resource_type = "音频"

    candidate = {
        "resource_id": resource_id,
        "title": title,
        "source_url": source_url,
        "source_platform": "ximalaya",
        "source": "ximalaya-audio",
        "source_name": "喜马拉雅",
        "snippet": intro,
        "format": "m4a",
        "resource_type": resource_type,
        "subject": subject,
        "provider": nickname,
        "downloadable": not is_paid,
        "requires_auth": False,
        "metadata_confidence": 0.85,
        # 扩展字段
        "is_paid": is_paid,
        "is_vip_free": is_vip_free,
        "play_count": play_count,
        "comment_count": comments,
        "score": score,
        "is_verified_anchor": is_verified,
        "cover_url": cover_path,
        "is_finished": is_finished,
        "finished_status": finished_status,
        "tracks_count": tracks_count,
        "tags": tags,
        "category_title": category_title,
        "created_at": created_at,
        "updated_at": updated_at,
        # platform-search-contract 字段
        "platform_signals": {
            "views": play_count,
            "comments": comments,
            "native_score": quality_score,
            "native_level": quality_level,
            "is_verified": is_verified,
        },
        "download_feasibility": download_feasibility,
        "raw": {"core": core, "category_id": category_id},
    }

    return candidate


# ─── 降级方案：M站镜像接口 ──────────────────────────────────────


def search_via_mirror_api(
    keyword: str,
    core: str = "album",
    max_results: int = 20,
    cookie: str | None = None,
    free_only: bool = False,
    sort_by: str = "relevance",
) -> list[dict[str, Any]]:
    """降级方案：通过 M站镜像接口搜索。

    M站接口使用 CSRF 伪造请求头调用官方 API，参数格式略有不同。
    """
    headers = _build_headers(cookie)
    # M站需要额外的 CSRF 伪装头
    headers["Origin"] = "https://m.ximalaya.com"
    headers["X-Requested-With"] = "XMLHttpRequest"

    candidates: list[dict[str, Any]] = []
    condition_map = {"relevance": "relation", "popularity": "play", "newest": "recent"}
    condition = condition_map.get(sort_by, "relation")

    page = 1
    rows = min(max_results, 20)

    while len(candidates) < max_results:
        params: dict[str, str] = {
            "kw": keyword,
            "core": core,
            "page": str(page),
            "rows": str(rows),
            "condition": condition,
        }
        if free_only:
            params["paidFilter"] = "true"
            params["fq"] = "is_paid:false,"

        url = f"{SEARCH_MIRROR_API}?{urllib.parse.urlencode(params)}"
        log.info("镜像接口搜索: core=%s page=%d", core, page)

        try:
            req = urllib.request.Request(url, headers=headers)
            with urlopen_with_fallback(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
        except Exception as exc:
            log.error("镜像接口请求失败: %s", exc)
            break

        # M站返回结构可能不同，尝试多种解析路径
        docs = []
        total_found = 0
        total_page = 0
        try:
            # 路径1: data.album.docs（M站专辑搜索）
            if core == "album" and "data" in data:
                album_data = data["data"].get("album", {})
                docs = album_data.get("docs", [])
                total_found = album_data.get("total", 0)
                total_page = album_data.get("totalPage", 0)
            # 路径2: data.track.docs（声音搜索）
            elif core == "track" and "data" in data:
                track_data = data["data"].get("track", {})
                docs = track_data.get("docs", [])
                total_found = track_data.get("total", 0)
                total_page = track_data.get("totalPage", 0)
            # 路径3: 和主接口一样的结构
            elif "data" in data and "result" in data.get("data", {}):
                response = data["data"]["result"]["response"]
                docs = response.get("docs", [])
                total_found = response.get("numFound", 0)
                total_page = response.get("totalPage", 0)
        except (KeyError, TypeError):
            log.error("镜像接口响应结构异常")
            break

        if not docs:
            log.info("镜像接口无更多结果")
            break

        for doc in docs:
            cand = _parse_main_doc(doc, core)
            if cand:
                cand["raw"]["search_method"] = "mirror_api"
                candidates.append(cand)
                if len(candidates) >= max_results:
                    break

        if page >= total_page:
            break
        page += 1
        time.sleep(0.5)

    log.info("镜像接口搜索返回 %d 条候选", len(candidates))
    return candidates[:max_results]


# ─── 主搜索入口 ───────────────────────────────────────────────


def search(
    keyword: str,
    core: str = "album",
    max_results: int = 20,
    cookie: str | None = None,
    free_only: bool = False,
    sort_by: str = "relevance",
) -> list[dict[str, Any]]:
    """主搜索入口：主接口 → 镜像接口降级。

    Args:
        keyword: 搜索关键词
        core: 搜索类型 album/track，默认 album
        max_results: 最大返回数
        cookie: 可选 Cookie
        free_only: 是否只返回免费内容
        sort_by: 排序 relevance/popularity/newest

    Returns:
        标准 candidate 列表
    """
    log.info(
        "喜马拉雅搜索: kw='%s' core=%s max=%d free=%s sort=%s",
        keyword, core, max_results, free_only, sort_by,
    )

    # 路径1：官方主接口
    candidates = search_via_main_api(
        keyword, core=core, max_results=max_results,
        cookie=cookie, free_only=free_only, sort_by=sort_by,
    )
    if candidates:
        return candidates

    # 路径2：降级 M站镜像接口
    log.info("主接口无结果或异常，降级 M站镜像接口...")
    candidates = search_via_mirror_api(
        keyword, core=core, max_results=max_results,
        cookie=cookie, free_only=free_only, sort_by=sort_by,
    )
    return candidates


# ─── 辅助函数 ─────────────────────────────────────────────────


def _clean_html(text: str) -> str:
    """清理 HTML 标签和高亮标记。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&ensp;", " ").replace("&amp;", "&")
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    return text.strip()


def _normalize_ximalaya_url(raw_url: str, core: str, resource_id: str) -> str:
    """将喜马拉雅内部 URL 规范化为标准 https 链接。"""
    if raw_url.startswith("http"):
        return raw_url
    if raw_url.startswith("//"):
        return "https:" + raw_url
    if raw_url.startswith("/"):
        # /album/xxx 或 /sound/xxx 或 /track/xxx
        return "https://www.ximalaya.com" + raw_url
    # 回退到拼接
    if core == "album":
        return f"{ALBUM_URL_PREFIX}{resource_id}"
    return f"{TRACK_URL_PREFIX}{resource_id}"


def _infer_subject(title: str, intro: str, category_title: str, category_id: str) -> str:
    """根据标题、简介、分类推断主题分类。"""
    combined = f"{title} {intro} {category_title}".lower()

    # 先按分类 ID 精确匹配
    if category_id in CATEGORY_MAP:
        cat_name = CATEGORY_MAP[category_id]
        # 映射到资源规范的 8 大品类
        if cat_name in ("儿歌", "睡前故事", "童话"):
            return "兴趣拓展"
        if cat_name == "国学":
            return "古诗国学"
        if cat_name == "英语":
            return "英语"
        if cat_name == "教育培训":
            return "学科同步"

    # 按关键词匹配
    for subject, keywords in CHILD_CATEGORY_KEYWORDS.items():
        if any(kw.lower() in combined for kw in keywords):
            return subject

    return "兴趣拓展"


def _ms_to_iso(ms_timestamp: Any) -> str | None:
    """毫秒时间戳转 ISO 格式字符串。"""
    if not ms_timestamp or not isinstance(ms_timestamp, (int, float)):
        return None
    try:
        # 喜马拉雅时间戳是毫秒级
        dt = datetime.fromtimestamp(ms_timestamp / 1000)
        return dt.isoformat()
    except (ValueError, OSError):
        return None


def _estimate_quality(
    play_count: int | None,
    score: float | None,
    is_verified: bool,
    is_paid: bool,
    tracks_count: int,
) -> tuple[int, str]:
    """估算平台质量分（0-100）和等级（S/A/B/C）。

    评估维度（遵循 quality-rubric.md）：
    - 内容质量与完整性（tracks_count + score）
    - 权威可信度（is_verified）
    - 可获取性（is_paid）
    - 安全与体验（play_count）
    """
    q_score = 60  # 基础分

    # 播放量加分（安全与体验维度）
    if play_count:
        if play_count > 10_000_000:  # 千万播放
            q_score += 18
        elif play_count > 1_000_000:  # 百万播放
            q_score += 14
        elif play_count > 100_000:  # 十万播放
            q_score += 10
        elif play_count > 10_000:  # 万播放
            q_score += 6

    # 评分加分（内容质量维度）
    if score and isinstance(score, (int, float)):
        if score >= 9.5:
            q_score += 10
        elif score >= 9.0:
            q_score += 8
        elif score >= 8.0:
            q_score += 5

    # 认证主播加分（权威可信度维度）
    if is_verified:
        q_score += 6

    # 集数加分（内容完整性维度）
    if tracks_count:
        if tracks_count >= 50:
            q_score += 6
        elif tracks_count >= 20:
            q_score += 4
        elif tracks_count >= 5:
            q_score += 2

    # 免费加分（可获取性维度）
    if not is_paid:
        q_score += 4

    q_score = max(0, min(100, q_score))

    # 等级映射
    if q_score >= 90:
        level = "S"
    elif q_score >= 75:
        level = "A"
    elif q_score >= 60:
        level = "B"
    else:
        level = "C"

    return q_score, level


def _estimate_feasibility(is_paid: bool, is_vip_free: bool) -> str:
    """估算下载可行性：高/中/低。"""
    if is_paid and not is_vip_free:
        return "低"
    if is_vip_free:
        return "中"
    return "中"  # 免费音频一般需解析，标记为中


# ─── 输出 ─────────────────────────────────────────────────────


def output_candidates(
    results: list[dict[str, Any]],
    keyword: str,
    core: str,
    output_file: str | None = None,
) -> dict[str, Any]:
    """格式化为标准 candidate JSON 输出。"""
    data: dict[str, Any] = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "ximalaya-audio",
        "query": keyword,
        "core": core,
        "searched_at": datetime.now().isoformat(),
        "total": len(results),
        "candidates": results,
    }
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(output + "\n", encoding="utf-8")
        log.info("候选列表已保存: %s (%d 条)", output_file, len(results))
    else:
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
    return data


# ─── CLI ─────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="喜马拉雅搜索脚本 — 搜索专辑/声音，输出标准 candidate JSON"
    )
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="搜索喜马拉雅音频")
    s.add_argument("keyword", help="搜索关键词")
    s.add_argument(
        "--core",
        choices=["album", "track"],
        default="album",
        help="搜索类型：album（专辑，默认）/ track（声音）",
    )
    s.add_argument("--cookie", default=None, help="喜马拉雅 Cookie（可选，增强个性化）")
    s.add_argument("--max", type=int, default=20, help="最大返回数（默认 20）")
    s.add_argument(
        "--free-only",
        action="store_true",
        help="只返回免费内容",
    )
    s.add_argument(
        "--sort",
        choices=["relevance", "popularity", "newest"],
        default="relevance",
        help="排序方式：relevance（相关度，默认）/ popularity（热度）/ newest（最新）",
    )
    s.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    if args.cmd == "search":
        results = search(
            args.keyword,
            core=args.core,
            max_results=args.max,
            cookie=args.cookie,
            free_only=args.free_only,
            sort_by=args.sort,
        )
        output_candidates(results, args.keyword, args.core, args.output)
        return 0 if results else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
