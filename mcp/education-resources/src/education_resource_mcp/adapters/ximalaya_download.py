"""Ximalaya audio downloader.

Self-contained implementation that handles xm-sign generation, encrypted audio
URL resolution and streaming download.  Ported from the standalone
xmly_downloader.py skill.

Requires pycryptodome for AES-ECB signing.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import uuid
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..sessions import SessionStore
from ..policy import PolicyError, ensure_within_root
from .http_client import urlopen_with_fallback


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE = "https://www.ximalaya.com"
BASE_INFO_URL = BASE + "/mobile-playpage/track/v3/baseInfo/{ts}"
TRACKS_LIST_URL = BASE + "/revision/album/getTracksList"
ALBUM_URL = BASE + "/album/{album_id}"
SOUND_URL = BASE + "/sound/{track_id}"
HDAA_REPORT_URL = "https://hdaa.shuzilm.cn/report?v=1.2.0&e=1&c=1&r={uid}"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
AES_KEY = b"m9ZtRrz:qujT8@da"
_URL_SAFE_CHARS = ")!~*'("

PERMUTATION_TABLE = [
    183,174,108,16,131,159,250,5,239,110,193,202,153,137,251,176,
    119,150,47,204,97,237,1,71,177,42,88,218,166,82,87,94,
    14,195,69,127,215,240,225,197,238,142,123,44,219,50,190,29,
    181,186,169,98,139,185,152,13,141,76,6,157,200,132,182,49,
    20,116,136,43,155,194,101,231,162,242,151,213,53,60,26,134,
    211,56,28,223,107,161,199,15,229,61,96,41,66,158,254,21,
    165,253,103,89,3,168,40,246,81,95,58,31,172,78,99,45,
    148,187,222,124,55,203,235,64,68,149,180,35,113,207,118,111,
    91,38,247,214,7,212,209,189,241,18,115,173,25,236,121,249,
    75,57,216,10,175,112,234,164,70,206,198,255,140,230,12,32,
    83,46,245,0,62,227,72,191,156,138,248,114,220,90,84,170,
    128,19,24,122,146,80,39,37,8,34,22,11,93,130,63,154,
    244,160,144,79,23,133,92,54,102,210,65,67,27,196,201,106,
    143,52,74,100,217,179,48,233,126,117,184,226,85,171,167,86,
    2,147,17,135,228,252,105,30,192,129,178,120,36,145,51,163,
    77,205,73,4,188,125,232,33,243,109,224,104,208,221,59,9,
]

XOR_KEY = [
    204,53,135,197,39,73,58,160,79,24,12,83,180,250,101,60,
    206,30,10,227,36,95,161,16,135,150,235,116,242,116,165,171,
]


# ---------------------------------------------------------------------------
# AES helpers (requires pycryptodome)
# ---------------------------------------------------------------------------
def _aes_encrypt(plaintext: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    cipher = AES.new(AES_KEY, AES.MODE_ECB)
    return cipher.encrypt(pad(plaintext, 16))


def _aes_decrypt(ciphertext: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    cipher = AES.new(AES_KEY, AES.MODE_ECB)
    return unpad(cipher.decrypt(ciphertext), 16)


# ---------------------------------------------------------------------------
# Device info template
# ---------------------------------------------------------------------------
_DEVICE_INFO: dict[str, Any] = {
    "Zf5": 0, "GF9": "2.0.0",
    "HW5": "t6pfoml9679z52kqw93uqu75eflqdg1bykhl",
    "uS7": "", "KFp": "h5_goyxvzyohd",
    "ew1": {
        "Wg7": "Mozilla", "lV1": "Google Inc.", "Xt4": "Netscape",
        "yV2": UA, "KY1": "Win32",
        "Le3": base64.b64encode(UA.encode()).decode(),
        "kH1": 900, "ad5": 1440, "Ua9": 24, "TQ6": 900, "kC7": 1440, "me8": 24,
        "eY9": True, "Kn2": False, "OM3": True, "sw8": False, "uW3": -1,
        "iO8": "https://www.ximalaya.com/", "By1": "www.ximalaya.com",
        "Gv4": "/", "ef2": "", "tZ2": "https:",
        "OG4": True, "kx1": True, "VD6": True, "Ov6": False,
        "lq3": "zh-CN", "ef5": ["zh-CN"], "OK3": 1, "Fg5": True,
        "qS2": [1440, 900, 1440, 900], "Fc5": "light",
    },
    "HK3": {
        "iI1": {"NF1": -1, "cA1": -1, "NK5": -1, "VP4": "-1.00", "RX5": -1, "VP6": -1, "tJ4": -1},
        "ti4": {"xm9": True, "is3": 1},
        "AV9": 8, "aK8": "Google Inc. (0x00001D17)",
        "df6": "ANGLE (0x00001D17, ZX C-960 (0x00003A04) Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "WB9": "8ba05e37b4b3f57bddb4904eb8f40204",
        "pD7": "d41d8cd98f00b204e9800998ecf8427e",
        "da2": "124.04347527516074", "dt2": 16, "Sy6": -480, "MS3": "Asia/Shanghai",
        "pi9": False, "Ao1": [], "BH5": 0,
        "UG4": ["Arial", "Consolas", "Courier New", "Georgia", "Tahoma", "Times New Roman", "Verdana"],
    },
    "fc9": {"cx4": "4g", "zY8": -1, "yj6": 1.5, "dV4": 200, "yX4": False},
    "adi": "070BF8:016D89:6BDE99:1600",
    "acd": "D2t6yNNzRqtSbN4GtZw4eGLn8tfc0Y1EYzqzMOCd9GiGMX17",
    "bdi": None, "bcd": None,
    "fd2": {"Pf5": 1783179255284, "Ja5": "070BF8:016D89:6BDE99:1600",
            "xz7": str(uuid.uuid4()), "av1": "D2t6yNNzRqtSbN4GtZw4eGLn8tfc0Y1EYzqzMOCd9GiGMX17", "cp9": 0},
    "exts": "", "startime": int(time.time() * 1000),
    "Zn6": {"oe2": "0", "EV9": "true",
            "xu2": "1441A790908125E9682A828824A003E99783D166409BBC4DD782F461C2955BA7",
            "CY8": "", "nE4": 928, "Tw1": [5799.099999904633, 6727.399999856949], "Sb1": False},
    "jm9": 2, "dla": "", "swp": "", "ecm": "", "emm": "", "asu": "", "asu1": 0,
    "GJ2": f"{uuid.uuid4()}-fcs011", "slw": "", "bds": "",
    "MT7": "33-00000-0000-1111111-000000-0011-000000-0000-00000-0", "bnd": "-0",
    "kec": "000000", "BG5": False, "Fd8": "1", "iq7": False,
    "DP5": "1441A7909C087DBBE7CE59881B9DF8B9", "lL1": hashlib.md5(uuid.uuid4().bytes).hexdigest(),
    "uT8": "-1", "sV5": 2, "Vo6": "",
    "infoF": {"lof": False, "baf": False, "auf": False, "iif": False},
    "infoCallback": None, "url_host": "hdaa.shuzilm.cn",
}


# ---------------------------------------------------------------------------
# xm-sign generation
# ---------------------------------------------------------------------------
def _json_dumps_compact(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _decode_uri_special(encoded: str) -> str:
    out: list[str] = []
    i, n = 0, len(encoded)
    while i < n:
        ch = encoded[i]
        if ch == "%":
            if i + 5 <= n and encoded[i + 1] == "u":
                h = encoded[i + 2:i + 6]
                if re.match(r"^[0-9A-Fa-f]{4}$", h):
                    out.append(chr(int(h, 16)))
                    i += 6
                    continue
            if i + 2 <= n:
                h = encoded[i + 1:i + 3]
                if re.match(r"^[0-9A-Fa-f]{2}$", h):
                    out.append(chr(int(h, 16)))
                    i += 3
                    continue
        out.append(ch)
        i += 1
    return "".join(out)


def _string_to_uint8(text: str) -> bytes:
    encoded = urllib.parse.quote(text, safe=_URL_SAFE_CHARS)
    decoded = _decode_uri_special(encoded)
    return bytes(ord(c) for c in decoded)


def _encrypt_payload(device_info: dict) -> bytes:
    json_str = _json_dumps_compact(device_info)
    uint8 = _string_to_uint8(json_str)
    compressed = zlib.compress(uint8, level=6)
    return _aes_encrypt(compressed)


def _generate_xm_sign() -> str:
    info = copy.deepcopy(_DEVICE_INFO)
    info["Zf5"] = int(time.time() * 1000)
    body = _encrypt_payload(info)
    url = HDAA_REPORT_URL.format(uid=str(uuid.uuid4()))
    request = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/octet-stream",
        "User-Agent": UA,
        "Host": "hdaa.shuzilm.cn",
    })
    with urlopen(request, timeout=15) as resp:
        raw = resp.read().decode("utf-8", "replace")
    decrypted = _aes_decrypt(base64.b64decode(raw))
    obj = json.loads(decrypted)
    cadd = str(obj.get("cadd") or "")
    sid = str(obj.get("sid") or "")
    if not cadd or not sid:
        raise DomainError("DOWNLOAD_FAILED", "喜马拉雅签名服务未返回有效凭据", retryable=True)
    return f"{cadd}&&{sid}"


# ---------------------------------------------------------------------------
# Audio URL decryption
# ---------------------------------------------------------------------------
def _decode_audio_url(encrypted_url: str) -> str:
    if not encrypted_url:
        return ""
    if encrypted_url.startswith("http"):
        return encrypted_url
    cleaned = encrypted_url.replace("_", "/").replace("-", "+")
    cleaned += "=" * (-len(cleaned) % 4)
    decoded = base64.b64decode(cleaned)
    if len(decoded) < 16:
        raise DomainError("DOWNLOAD_FAILED", "音频 URL 密文长度不足")
    data = bytearray(decoded[:-16])
    iv = decoded[-16:]
    for i in range(len(data)):
        data[i] = PERMUTATION_TABLE[data[i]]
    for i in range(0, len(data), 16):
        for j in range(min(16, len(data) - i)):
            data[i + j] ^= iv[j]
    for i in range(0, len(data), 32):
        for j in range(min(32, len(data) - i)):
            data[i + j] ^= XOR_KEY[j]
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Track info API
# ---------------------------------------------------------------------------
def _get_track_info(track_id: str, cookie: str) -> dict[str, Any]:
    xm_sign = _generate_xm_sign()
    url = BASE_INFO_URL.format(ts=int(time.time() * 1000))
    params = urlencode({"device": "www2", "trackId": str(track_id), "trackQualityLevel": "1"})
    request = Request(
        f"{url}?{params}",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": SOUND_URL.format(track_id=track_id),
            "Origin": BASE,
            "Cookie": cookie,
            "xm-sign": xm_sign,
            "User-Agent": UA,
        },
    )
    with urlopen_with_fallback(request, timeout=40) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))
    ret = body.get("ret")
    if ret not in (0, 200):
        msg = body.get("msg", "")
        if ret in (3005, 1001):
            raise DomainError("AUTH_REQUIRED", f"喜马拉雅认证失败: {msg}", retryable=False)
        raise DomainError("DOWNLOAD_FAILED", f"baseInfo 失败 ret={ret}: {msg}", retryable=True)
    track_info = (body.get("data") or {}).get("trackInfo") or body.get("trackInfo") or {}
    play_urls = track_info.get("playUrlList") or []
    if not play_urls:
        raise DomainError("DOWNLOAD_FAILED", "未获取到播放 URL（可能需要 VIP）", retryable=False)
    # Select best quality
    play_urls = sorted(
        [p for p in play_urls if p.get("url")],
        key=lambda p: int((p.get("type") or "0_0").split("_")[-1]) if (p.get("type") or "").split("_")[-1].isdigit() else 0,
        reverse=True,
    )
    best = play_urls[0]
    audio_url = _decode_audio_url(best["url"])
    return {
        "title": track_info.get("title", track_id),
        "url": audio_url,
        "file_size": int(best.get("fileSize") or 0),
        "type": best.get("type", ""),
    }


def _get_first_track_id(album_id: str) -> str:
    """Get the first track ID from an album."""
    url = TRACKS_LIST_URL + "?" + urlencode({"albumId": album_id, "pageNum": 1, "sort": 0})
    request = Request(url, headers={"User-Agent": UA, "Referer": ALBUM_URL.format(album_id=album_id)})
    with urlopen_with_fallback(request, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))
    tracks = (body.get("data") or {}).get("tracks") or []
    if not tracks:
        raise DomainError("DOWNLOAD_FAILED", "专辑无可用曲目", retryable=False)
    return str(tracks[0].get("trackId"))


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------
_ALBUM_RE = re.compile(r"/album/(\d+)")
_SOUND_RE = re.compile(r"/sound/(\d+)")


class XimalayaDownloader:
    """Download Ximalaya audio via signed API.

    Requires a valid login cookie (``1&_token``) in SessionStore.
    Downloads the first track of an album or the specified track.
    """

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.settings = settings

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        url = str(resource["source_url"])
        title = str(resource.get("title") or "ximalaya_audio")

        # Resolve track ID
        sound_match = _SOUND_RE.search(url)
        if sound_match:
            track_id = sound_match.group(1)
        else:
            album_match = _ALBUM_RE.search(url)
            if album_match:
                track_id = _get_first_track_id(album_match.group(1))
            else:
                # Fallback: try numeric ID
                nums = re.findall(r"(\d+)", url)
                track_id = nums[-1] if nums else ""

        if not track_id:
            raise DomainError("DOWNLOAD_FAILED", f"无法从 URL 解析曲目 ID: {url}")

        # Get cookie
        session_data = self.session_store.get_session_data("ximalaya")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""
        if not cookie:
            raise DomainError("AUTH_REQUIRED", "喜马拉雅下载需要登录 Cookie", retryable=False)

        # Get audio URL
        info = _get_track_info(track_id, cookie)
        audio_url = info["url"]
        if not audio_url:
            raise DomainError("DOWNLOAD_FAILED", "音频 URL 解密失败", retryable=False)

        # Download
        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        ext = ".m4a" if "M4A" in info.get("type", "") else ".mp3"
        safe_title = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", info["title"]).strip("-._")[:80] or "audio"
        filename = f"{safe_title}{ext}"
        destination = job_dir / filename
        ensure_within_root(destination, self.settings.jobs_dir)
        temporary = job_dir / f".{filename}.part"

        request = Request(audio_url, headers={"User-Agent": UA, "Referer": BASE + "/"})
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with urlopen_with_fallback(request, timeout=self.settings.download_timeout_seconds) as response:
                with temporary.open("wb") as handle:
                    while True:
                        if cancel_event.is_set():
                            raise DomainError("JOB_CANCELLED", "下载已取消")
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        byte_size += len(chunk)
                        digest.update(chunk)
                        handle.write(chunk)
        except DomainError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise DomainError("DOWNLOAD_FAILED", f"音频下载失败: {type(exc).__name__}: {exc}", retryable=True) from exc

        if byte_size == 0:
            temporary.unlink(missing_ok=True)
            raise DomainError("CONTENT_VALIDATION_FAILED", "下载内容为空")

        temporary.replace(destination)
        media_type = "audio/mp4" if ext == ".m4a" else "audio/mpeg"
        return DownloadResult(destination, byte_size, media_type, digest.hexdigest(), filename)
