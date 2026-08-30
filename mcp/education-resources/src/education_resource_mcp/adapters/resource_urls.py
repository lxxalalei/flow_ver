"""Platform URL identification kept inside the adapter layer."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any
from urllib.parse import urlsplit

from ..search import canonical_http_url


_MD5_RE = re.compile(r"[0-9a-fA-F]{32}")


def identify_resource_url(source_url: str) -> dict[str, Any]:
    """Recognize a known URL into the smallest factual Resource shape."""

    url = canonical_http_url(str(source_url or "").strip())
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    path = parsed.path or "/"
    query = urllib.parse.parse_qs(parsed.query)

    def resource(
        platform: str,
        kind: str,
        title: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        return {
            "platform": platform,
            "title": title or (path.rstrip("/").rsplit("/", 1)[-1] or host or url)[:120],
            "source_url": url,
            "resource_type": kind,
            "metadata": metadata,
        }

    if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"} and path.startswith("/video/"):
        return resource("bilibili", "视频")
    if host == "space.bilibili.com":
        if "/lists/" in path or "/channel/collectiondetail" in path or "/channel/seriesdetail" in path:
            return resource("bilibili", "collection", "Bilibili collection")
        return resource("bilibili", "creator", "Bilibili creator")

    if host in {"douyin.com", "www.douyin.com"}:
        if path.startswith("/video/"):
            return resource("douyin", "视频")
        if path.startswith("/user/"):
            return resource("douyin", "creator", "Douyin creator")
        if path.startswith("/collection/"):
            return resource("douyin", "collection", "Douyin collection")

    if host in {"ximalaya.com", "www.ximalaya.com"}:
        if re.search(r"/sound/\d+", path):
            return resource("ximalaya", "track", "Ximalaya track")
        if re.search(r"/album/\d+", path):
            return resource("ximalaya", "album", "Ximalaya album")
        if re.search(r"/zhubo/\d+", path):
            return resource("ximalaya", "creator", "Ximalaya creator")

    if host == "basic.smartedu.cn":
        if "/tchMaterial/" in path:
            return resource("smartedu", "textbook", "SmartEdu textbook")
        if "activityId" in query or "courseId" in query:
            return resource("smartedu", "course", "SmartEdu course")
        return resource("smartedu", "网页")

    if host == "k.zjer.cn" and ("/courseAfter/" in path or "courseCateId" in query or "id" in query):
        return resource("zjer", "course", "Zjer course")

    if host in {"tv.cctv.com", "www.cctv.com", "cctv.com"}:
        if path.startswith("/lm/"):
            return resource("cctv", "column", "CCTV 栏目")
        if re.search(r"/\d{4}/\d{2}/\d{2}/VID[A-Za-z0-9]+\.shtml", path):
            return resource("cctv", "视频")
        return resource("cctv", "网页")

    if host.startswith("libgen."):
        md5_match = _MD5_RE.search(url)
        signals = {"md5": md5_match.group(0).lower()} if md5_match else {}
        return resource(
            "libgen",
            "book",
            "LibGen book",
            platform_signals=signals,
        )

    if host in {"z-library.ec", "z-library.sk", "1lib.sk"} or any(
        host.endswith(f".{suffix}")
        for suffix in ("z-library.ec", "z-library.sk", "1lib.sk")
    ):
        match = re.search(r"/book/(\d+)/([0-9A-Za-z_-]{4,128})(?:/|$)", path)
        signals = (
            {"book_id": match.group(1), "book_hash": match.group(2)}
            if match
            else {}
        )
        return resource(
            "zlibrary",
            "book",
            "Z-Library book",
            platform_signals=signals,
        )

    if host in {"www.zhihu.com", "zhuanlan.zhihu.com"}:
        return resource("zhihu", "文章")

    return resource("generic", "网页")


__all__ = ["identify_resource_url"]
