"""SmartEdu (国家中小学智慧教育平台) resource downloader.

The active route rechecks the platform detail API, binds the confirmed direct
primary format, and materializes verified PDF, MP4, MP3, or M4A files.

Reference: tchMaterial-parser (happycola233) and smartedu-dl-go (hantang).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
import hashlib
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, TypeAlias
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlsplit, urlunparse, urlunsplit
from urllib.error import HTTPError
from urllib.request import Request

from ..archive import media_signature_matches
from ..config import Settings
from ..downloader import DownloadBatchResult, DownloadItemFailure, DownloadResult

from ..errors import DomainError
from ..sessions import SessionStore
from ..policy import (
    NetworkPolicy,
    PolicyError,
    Resolver,
    ensure_within_root,
    system_resolver,
)
from .smartedu_resource import (
    _ACTIVE_PRIMARY_FORMATS,
    _COURSE_TYPES,
    CDN_SPECIAL,
    _bounded_text,
    _detail_api_url,
    _find_files,
    _is_cover,
    _primary_candidate,
    _resolve_content,
    _role_for_candidate,
    _select_course_files,
    _smartedu_file_key,
    _smartedu_file_key_from_resource,
    _smartedu_representation_id,
)

from .http_client import urlopen_with_fallback


DownloadReturn: TypeAlias = DownloadResult | DownloadBatchResult

_SMARTEDU_DETAIL_HOSTS = frozenset(
    {
        "s-file-1.ykt.cbern.com.cn",
        "s-file-2.ykt.cbern.com.cn",
        "s-file-3.ykt.cbern.com.cn",
    }
)
_SMARTEDU_STORAGE_HOSTS = frozenset(
    {
        "r1-ndr.ykt.cbern.com.cn",
        "r2-ndr.ykt.cbern.com.cn",
        "r3-ndr.ykt.cbern.com.cn",
        "r1-ndr-private.ykt.cbern.com.cn",
        "r2-ndr-private.ykt.cbern.com.cn",
        "r3-ndr-private.ykt.cbern.com.cn",
    }
)
_SMARTEDU_KEY_HOSTS = frozenset(
    {
        "ndvideo-key.ykt.eduyun.cn",
    }
)
_SMARTEDU_ALLOWED_HOSTS = (
    _SMARTEDU_DETAIL_HOSTS | _SMARTEDU_STORAGE_HOSTS | _SMARTEDU_KEY_HOSTS
)
_HTTP_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SENSITIVE_QUERY_KEYS = frozenset(
    {"access_token", "accesstoken", "auth", "authorization", "token"}
)
_SENSITIVE_HEADER_KEYS = frozenset(
    {"access_token", "accesstoken", "authorization", "cookie", "x-nd-auth"}
)
_DETAIL_MAX_BYTES = 4 * 1024 * 1024
_RELATION_MAX_BYTES = 4 * 1024 * 1024
_PLAYLIST_MAX_BYTES = 2 * 1024 * 1024
_KEY_JSON_MAX_BYTES = 64 * 1024
_FATAL_CODES = frozenset({
    "AUTH_REQUIRED",
    "AUTH_FAILED",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "POLICY_DENIED",
    "NETWORK_BLOCKED",
    "REDIRECT_BLOCKED",
    "JOB_CANCELLED",
    "CANCELLED",
})
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{0,63}$")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _response_status(response: Any) -> int:
    raw = getattr(response, "status", None)
    if raw is None:
        raw = getattr(response, "code", None)
    if raw is None:
        return 200
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _response_url(response: Any, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return value
    value = getattr(response, "url", None)
    return value if isinstance(value, str) and value else fallback


def _response_header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:
        value = None
    if value is None:
        try:
            for key, candidate in headers.items():
                if str(key).casefold() == name.casefold():
                    value = candidate
                    break
        except Exception:
            value = None
    return None if value is None else str(value)


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _same_resource_url(left: str, right: str) -> bool:
    try:
        first = urlsplit(left)
        second = urlsplit(right)
    except ValueError:
        return left == right
    return urlunsplit((first.scheme, first.netloc, first.path, first.query, "")) == urlunsplit(
        (second.scheme, second.netloc, second.path, second.query, "")
    )


def _request_contains_credentials(request: Request) -> bool:
    try:
        query = parse_qs(urlsplit(request.full_url).query, keep_blank_values=True)
    except ValueError:
        query = {}
    if any(str(key).casefold() in _SENSITIVE_QUERY_KEYS for key in query):
        return True
    for name, value in request.header_items():
        normalized = str(name).casefold()
        if normalized not in _SENSITIVE_HEADER_KEYS:
            continue
        if normalized == "x-nd-auth" and 'id="0"' in str(value):
            continue
        return True
    return False


def _raise_for_http_status(response: Any) -> None:
    status = _response_status(response)
    if 200 <= status < 300:
        return
    if status in {401, 403}:
        raise DomainError("AUTH_REQUIRED", "下载需要认证", retryable=False)
    if status in {404, 410}:
        raise DomainError("RESOURCE_NOT_FOUND", "资源当前不可用", retryable=False)
    if status in {408, 429}:
        raise DomainError("RATE_LIMITED", "SmartEdu 暂时不可用", retryable=True)
    if status >= 500:
        raise DomainError("PLATFORM_UNAVAILABLE", "SmartEdu 暂时不可用", retryable=True)
    raise DomainError("DOWNLOAD_FAILED", "SmartEdu 响应状态无效", retryable=False)


def _read_bounded(response: Any, max_bytes: int, *, label: str) -> bytes:
    try:
        body = response.read(max_bytes + 1)
    except TypeError:
        body = response.read()
    if not isinstance(body, (bytes, bytearray, memoryview)) or not body:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            f"SmartEdu {label}内容为空",
            retryable=False,
        )
    payload = bytes(body)
    if len(payload) > max_bytes:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            f"SmartEdu {label}内容超过解析上限",
            retryable=False,
        )
    return payload


def _read_json_object(response: Any, max_bytes: int, *, label: str) -> dict[str, Any]:
    payload = _read_bounded(response, max_bytes, label=label)
    try:
        parsed = json.loads(payload.decode("utf-8", "replace"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            f"SmartEdu {label}格式无效",
            retryable=False,
        ) from exc
    if not isinstance(parsed, dict):
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            f"SmartEdu {label}格式无效",
            retryable=False,
        )
    return parsed


_HLS_PLAYLIST_MAX_BYTES = 2 * 1024 * 1024
_HLS_SEGMENT_MAX_BYTES = 64 * 1024 * 1024
_HLS_SEGMENT_RETRIES = 3


def _hls_attrs(raw: str) -> dict[str, str]:
    return {
        match.group(1).upper(): match.group(2).strip('"')
        for match in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', raw)
    }


def _hls_fetch(client: Any, url: str, token: str, *, limit: int, label: str) -> bytes:
    request = Request(url, headers=_smartedu_headers(token))
    with client.open(request, timeout=30) as resp:
        _raise_for_http_status(resp)
        return _read_bounded(resp, limit, label=label)


def _hls_fetch_bare(client: Any, url: str, *, limit: int, label: str) -> bytes:
    """GET with a bare User-Agent only.

    The ndvideo-key key-exchange endpoint rejects requests that carry auth
    headers (legacy platform finding: adding them turns 200 into 403).
    """

    request = Request(url, headers={"User-Agent": UA})
    with client.open(request, timeout=30) as resp:
        _raise_for_http_status(resp)
        return _read_bounded(resp, limit, label=label)


def _hls_json_field(payload: bytes, field: str, *, label: str) -> str:
    try:
        parsed = json.loads(payload.decode("utf-8", "replace"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            f"SmartEdu {label}格式无效",
            retryable=False,
        ) from exc
    if not isinstance(parsed, dict):
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            f"SmartEdu {label}格式无效",
            retryable=False,
        )
    value = parsed.get(field)
    if not isinstance(value, str) or not value:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            f"SmartEdu {label}缺少 {field}",
            retryable=False,
        )
    return value


def _aes_ecb_unwrap(ciphertext: bytes, key: bytes) -> bytes:
    from Crypto.Cipher import AES  # lazy: only encrypted streams need it

    if not ciphertext or len(ciphertext) % 16:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "HLS 密钥载荷长度非法",
            retryable=False,
        )
    plain = AES.new(key, AES.MODE_ECB).decrypt(ciphertext)
    pad = plain[-1] if plain else 0
    if 1 <= pad <= 16 and plain.endswith(bytes([pad]) * pad):
        plain = plain[:-pad]
    return plain


def _hls_fetch_decryption_key(http_client: Any, key_uri: str) -> bytes:
    """Resolve one SmartEdu AES-128 key through the ndvideo-key protocol.

    The key server is not a plain 16-byte key file; it runs a custom
    exchange (reference: smartedu-dl-go, tchMaterial-parser ecosystem):

    1. bare GET ``{base}/signs`` -> ``{"nonce": ...}``
    2. ``sign = md5(nonce + key_id)[:16]`` with key_id = URI tail
    3. bare GET ``{base}?nonce=...&sign=...`` -> ``{"key": <base64>}``
    4. AES-ECB-decrypt the payload using the ASCII sign bytes; the
       16-byte plaintext is the HLS AES-128 key.
    """

    base = key_uri.rstrip("/")
    key_id = base.rsplit("/", 1)[-1]
    nonce_payload = _hls_fetch_bare(
        http_client, base + "/signs", limit=_KEY_JSON_MAX_BYTES, label="HLS 密钥 nonce"
    )
    nonce = _hls_json_field(nonce_payload, "nonce", label="HLS 密钥 nonce")
    sign = hashlib.md5((nonce + key_id).encode("utf-8")).hexdigest()[:16]
    key_url = base + "?nonce=" + quote(nonce, safe="") + "&sign=" + sign
    key_payload = _hls_fetch_bare(
        http_client, key_url, limit=_KEY_JSON_MAX_BYTES, label="HLS 密钥数据"
    )
    key_b64 = _hls_json_field(key_payload, "key", label="HLS 密钥数据")
    try:
        ciphertext = base64.b64decode(key_b64)
    except (ValueError, TypeError) as exc:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "SmartEdu HLS 密钥数据不是合法 base64",
            retryable=False,
        ) from exc
    return _aes_ecb_unwrap(ciphertext, sign.encode("utf-8"))


def _hls_master_variant(text: str, base_url: str) -> str:
    """Return the highest-bandwidth variant URL of a master playlist."""

    best_url, best_bandwidth = "", -1
    pending: int | None = None
    for line in (raw.strip() for raw in text.splitlines()):
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            try:
                pending = int(_hls_attrs(line.split(":", 1)[1]).get("BANDWIDTH") or 0)
            except ValueError:
                pending = 0
        elif not line.startswith("#") and pending is not None:
            if pending > best_bandwidth:
                best_bandwidth, best_url = pending, urljoin(base_url, line)
            pending = None
    if best_bandwidth < 0:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED", "HLS 主播放列表没有可选码率", retryable=False
        )
    return best_url


def _hls_media_segments(
    text: str, base_url: str
) -> tuple[list[str], dict[str, str] | None]:
    """Return media segment URLs plus the active AES-128 key descriptor."""

    segments: list[str] = []
    key: dict[str, str] | None = None
    for line in (raw.strip() for raw in text.splitlines()):
        if not line:
            continue
        if line.startswith("#EXT-X-KEY:"):
            attrs = _hls_attrs(line.split(":", 1)[1])
            if str(attrs.get("METHOD") or "").upper() == "AES-128":
                uri = str(attrs.get("URI") or "")
                key = {"uri": urljoin(base_url, uri), "iv": str(attrs.get("IV") or "")}
            else:
                key = None
        elif not line.startswith("#"):
            segments.append(urljoin(base_url, line))
    if not segments:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED", "HLS 播放列表没有媒体分片", retryable=False
        )
    return segments, key


def _hls_decrypt(key: bytes, iv: bytes, payload: bytes) -> bytes:
    from Crypto.Cipher import AES  # lazy: only encrypted streams need it

    usable = len(payload) // 16 * 16
    plain = AES.new(key, AES.MODE_CBC, iv).decrypt(payload[:usable])
    pad = plain[-1] if plain else 0
    if 1 <= pad <= 16 and plain.endswith(bytes([pad]) * pad):
        plain = plain[:-pad]
    return plain


def _download_hls_to_mp4(
    url: str,
    destination: Path,
    cancel_event: threading.Event,
    token: str,
    http_client: Any,
) -> None:
    """Materialize one HLS stream: fetch segments, then remux to MP4 via ffmpeg.

    MP4 is the required deliverable; without a usable ffmpeg there is no
    fallback container.
    """

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise DomainError(
            "DOWNLOAD_FAILED", "ffmpeg 未安装，无法将 HLS 视频封装为 MP4", retryable=False
        )

    text = _hls_fetch(
        http_client, url, token, limit=_HLS_PLAYLIST_MAX_BYTES, label="HLS 播放列表"
    ).decode("utf-8", "replace")
    if "#EXT-X-STREAM-INF" in text:
        url = _hls_master_variant(text, url)
        text = _hls_fetch(
            http_client, url, token, limit=_HLS_PLAYLIST_MAX_BYTES, label="HLS 变体播放列表"
        ).decode("utf-8", "replace")
    segments, key = _hls_media_segments(text, url)

    cipher_key: bytes | None = None
    explicit_iv: bytes | None = None
    if key is not None:
        cipher_key = _hls_fetch_decryption_key(http_client, key["uri"])
        if len(cipher_key) != 16:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED", "HLS 密钥长度非法", retryable=False
            )
        if key["iv"]:
            try:
                raw_iv = bytes.fromhex(key["iv"].removeprefix("0x").removeprefix("0X"))
            except ValueError:
                raw_iv = b""
            if len(raw_iv) == 16:
                explicit_iv = raw_iv

    ts_path = destination.with_suffix(".ts.tmp")
    destination.unlink(missing_ok=True)
    try:
        with ts_path.open("wb") as handle:
            for index, segment_url in enumerate(segments):
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                payload: bytes | None = None
                for _attempt in range(_HLS_SEGMENT_RETRIES):
                    try:
                        payload = _hls_fetch(
                            http_client,
                            segment_url,
                            token,
                            limit=_HLS_SEGMENT_MAX_BYTES,
                            label="HLS 媒体分片",
                        )
                        break
                    except DomainError:
                        raise
                    except Exception:
                        continue
                if payload is None:
                    raise DomainError(
                        "DOWNLOAD_FAILED", "HLS 媒体分片下载失败", retryable=True
                    )
                if cipher_key is not None:
                    iv = explicit_iv or index.to_bytes(16, "big")
                    payload = _hls_decrypt(cipher_key, iv, payload)
                handle.write(payload)
        result = subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", str(ts_path),
                "-c", "copy", "-movflags", "+faststart", "-f", "mp4",
                str(destination),
            ],
            capture_output=True,
        )
        if result.returncode != 0 or not destination.is_file():
            detail = result.stderr.decode("utf-8", "replace")[-200:]
            raise DomainError(
                "DOWNLOAD_FAILED", f"ffmpeg 封装 MP4 失败: {detail}", retryable=False
            )
    finally:
        ts_path.unlink(missing_ok=True)


def _media_type_for_format(fmt: str) -> str:
    return {
        "pdf": "application/pdf",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "mp4": "video/mp4",
        # HLS 流交付的是经 ffmpeg 无损封装的 MP4。
        "m3u8": "video/mp4",
    }.get(fmt, "application/octet-stream")


def _validate_downloaded_file(path: Path, media_type: str) -> None:
    with path.open("rb") as handle:
        header = handle.read(64)
    if not media_signature_matches(media_type, path.name, header):
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "下载内容与声明格式不一致",
            retryable=False,
        )


class _SmartEduHttpClient:
    """SmartEdu-only HTTP boundary with exact hosts and explicit redirects."""

    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: Any | None = None,
        max_redirects: int = 5,
        allowed_hosts: frozenset[str] = _SMARTEDU_ALLOWED_HOSTS,
    ) -> None:
        self.policy = NetworkPolicy(
            allowed_hosts=allowed_hosts,
            resolver=resolver or system_resolver,
            max_redirects=max_redirects,
        )
        self.transport = transport
        self.max_redirects = max_redirects

    def _validate_url(self, url: str, *, redirect: bool) -> None:
        try:
            parsed = urlsplit(url)
            if parsed.scheme.casefold() != "https":
                raise PolicyError(
                    "unsupported_scheme",
                    "SmartEdu requests require HTTPS",
                )
            self.policy.validate_url(url)
        except PolicyError as exc:
            raise DomainError(
                "REDIRECT_BLOCKED" if redirect else "NETWORK_BLOCKED",
                "SmartEdu 重定向地址未通过网络策略"
                if redirect
                else "SmartEdu 请求地址未通过网络策略",
                retryable=False,
                details={"policy_code": exc.code},
            ) from exc
        except ValueError as exc:
            raise DomainError(
                "REDIRECT_BLOCKED" if redirect else "NETWORK_BLOCKED",
                "SmartEdu 重定向地址未通过网络策略"
                if redirect
                else "SmartEdu 请求地址未通过网络策略",
                retryable=False,
            ) from exc

    def validate_url(self, url: str) -> None:
        self._validate_url(url, redirect=False)

    def _request(self, request: Request, timeout: float) -> Any:
        if self.transport is None:
            return urlopen_with_fallback(
                request,
                timeout=timeout,
                follow_redirects=False,
            )
        target = self.transport
        method = getattr(target, "open", None)
        if callable(method):
            try:
                return method(request, timeout=timeout)
            except TypeError:
                return method(request, timeout)
        if not callable(target):
            raise TypeError("SmartEdu transport is not callable")
        try:
            return target(request, timeout=timeout)
        except TypeError:
            try:
                return target(request, timeout)
            except TypeError:
                return target(request)

    def open(self, request: Request, *, timeout: float) -> Any:
        current_url = request.full_url
        self._validate_url(current_url, redirect=False)
        headers = dict(request.header_items())
        method = request.get_method()
        data = request.data
        carries_credentials = _request_contains_credentials(request)
        redirects = 0

        while True:
            current_request = Request(
                current_url,
                data=data,
                headers=headers,
                method=method,
            )
            response: Any | None = None
            try:
                try:
                    response = self._request(current_request, timeout)
                except HTTPError as exc:
                    response = exc
                except DomainError:
                    raise
                except Exception as exc:
                    raise DomainError(
                        "PLATFORM_UNAVAILABLE",
                        "SmartEdu 网络请求失败",
                        retryable=True,
                    ) from exc

                final_url = _response_url(response, current_url)
                status = _response_status(response)
                if status in _HTTP_REDIRECT_STATUSES:
                    location = _response_header(response, "Location")
                    if not location or not location.strip():
                        raise DomainError(
                            "REDIRECT_BLOCKED",
                            "SmartEdu 重定向缺少有效目标",
                            retryable=False,
                        )
                    target_url = urljoin(current_url, location)
                    self._validate_url(target_url, redirect=True)
                    current_host = urlsplit(current_url).hostname
                    target_host = urlsplit(target_url).hostname
                    if carries_credentials and current_host != target_host:
                        raise DomainError(
                            "REDIRECT_BLOCKED",
                            "SmartEdu 凭据不得跨域重定向",
                            retryable=False,
                        )
                    if redirects >= self.max_redirects:
                        raise DomainError(
                            "REDIRECT_BLOCKED",
                            "SmartEdu 重定向次数超过上限",
                            retryable=False,
                            details={"max_redirects": self.max_redirects},
                        )
                    redirects += 1
                    current_url = target_url
                    continue

                self._validate_url(
                    final_url,
                    redirect=not _same_resource_url(final_url, current_url),
                )
                if not _same_resource_url(final_url, current_url):
                    raise DomainError(
                        "REDIRECT_BLOCKED",
                        "SmartEdu 传输层不得自动跟随重定向",
                        retryable=False,
                    )
                return response
            finally:
                if response is not None and (
                    _response_status(response) in _HTTP_REDIRECT_STATUSES
                    or not _same_resource_url(_response_url(response, current_url), current_url)
                ):
                    _close_response(response)


def _safe_error_code(value: Any, default: str = "DOWNLOAD_FAILED") -> str:
    code = str(value or default).upper().strip()
    return code if _SAFE_CODE.fullmatch(code) else default


def _safe_error_message(code: str) -> str:
    messages = {
        "AUTH_REQUIRED": "下载需要认证",
        "AUTH_FAILED": "下载认证失败",
        "UNAUTHORIZED": "下载认证失败",
        "FORBIDDEN": "下载被拒绝",
        "POLICY_DENIED": "下载被策略阻止",
        "NETWORK_BLOCKED": "网络请求被阻止",
        "REDIRECT_BLOCKED": "重定向被策略阻止",
        "JOB_CANCELLED": "下载已取消",
        "CANCELLED": "下载已取消",
        "CONTENT_VALIDATION_FAILED": "下载内容未通过校验",
        "RELATION_AUDIO_LOOKUP_FAILED": "伴随音频查询失败",
    }
    return messages.get(code, "文件下载失败")


def _exception_code(exc: BaseException) -> str:
    if isinstance(exc, DomainError):
        return _safe_error_code(exc.code)
    if isinstance(exc, HTTPError):
        if exc.code in {401, 403}:
            return "AUTH_REQUIRED"
        if exc.code in {407, 451}:
            return "POLICY_DENIED"
    if isinstance(exc, PolicyError):
        return "POLICY_DENIED"
    return "DOWNLOAD_FAILED"


def _is_fatal_code(code: str) -> bool:
    return code in _FATAL_CODES or code.startswith("AUTH_") or code.startswith("POLICY_")


def _make_item_failure(
    candidate: dict[str, Any], code: str, *, required: bool, role: str | None = None
) -> DownloadItemFailure:
    safe_code = _safe_error_code(code)
    metadata = dict(candidate.get("metadata") or {})
    metadata["required"] = bool(required)
    payloads = (
        {
            "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
            "code": safe_code,
            "message": _safe_error_message(safe_code),
            "role": role,
            "retryable": safe_code not in _FATAL_CODES,
            "required": bool(required),
            "details": metadata,
            "metadata": metadata,
        },
        {
            "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
            "code": safe_code,
            "message": _safe_error_message(safe_code),
            "role": role,
            "retryable": safe_code not in _FATAL_CODES,
            "required": bool(required),
        },
        {
            "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
            "code": safe_code,
            "message": _safe_error_message(safe_code),
            "role": role,
            "retryable": safe_code not in _FATAL_CODES,
        },
    )
    for payload in payloads:
        try:
            return DownloadItemFailure(**payload)  # type: ignore[arg-type]
        except TypeError:
            continue
    return DownloadItemFailure(  # type: ignore[call-arg]
        str(candidate.get("item_key") or "smartedu:unknown"),
        safe_code,
        _safe_error_message(safe_code),
    )


def _make_batch_result(
    results: list[DownloadResult], failures: list[DownloadItemFailure]
) -> DownloadBatchResult:
    """Construct B's envelope while tolerating its final field alias."""

    result_values = tuple(results)
    failure_values = tuple(failures)
    for result_field in ("results", "items", "downloads", "successes"):
        try:
            return DownloadBatchResult(
                **{result_field: result_values, "failures": failure_values}
            )  # type: ignore[arg-type]
        except TypeError:
            continue
    try:
        return DownloadBatchResult(result_values, failure_values)  # type: ignore[call-arg]
    except TypeError as exc:  # pragma: no cover - protects an incompatible B API
        raise TypeError("DownloadBatchResult interface is incompatible") from exc


def _make_download_result(
    path: Path,
    byte_size: int,
    media_type: str,
    sha256: str,
    filename: str,
    candidate: dict[str, Any],
    *,
    role: str,
    required: bool,
) -> DownloadResult:
    metadata = dict(candidate.get("metadata") or {})
    payload = {
        "path": path,
        "byte_size": byte_size,
        "media_type": media_type,
        "sha256": sha256,
        "filename": filename,
        "role": role,
        "required": bool(required),
        "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
        "metadata": metadata,
    }
    try:
        return DownloadResult(**payload)  # type: ignore[arg-type]
    except TypeError:
        # Keep old providers/test fixtures usable until downloader.py's
        # optional fields are present.
        return DownloadResult(path, byte_size, media_type, sha256, filename)


def _safe_destination_name(
    title: str, fmt: str, used_names: set[str], source_order: int
) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", title).strip("-._")[:80] or "resource"
    suffix = {
        "m3u8": ".mp4",
        "mp4": ".mp4",
        "webm": ".webm",
        "mov": ".mov",
        "mp3": ".mp3",
        "m4a": ".m4a",
        "wav": ".wav",
        "ogg": ".ogg",
        "pdf": ".pdf",
        "epub": ".epub",
        "doc": ".doc",
        "docx": ".docx",
        "ppt": ".ppt",
        "pptx": ".pptx",
        "srt": ".srt",
        "vtt": ".vtt",
        "jpg": ".jpg",
        "jpeg": ".jpg",
        "png": ".png",
        "json": ".json",
    }.get(fmt, ".bin")
    base = cleaned if cleaned.lower().endswith(suffix) else f"{cleaned}{suffix}"
    name = base
    if name in used_names:
        stem = Path(base).stem
        name = f"{stem}-{source_order + 1}{suffix}"
        while name in used_names:
            name = f"{stem}-{source_order + 1}-{len(used_names)}{suffix}"
    used_names.add(name)
    return name


def _safe_fatal_error(exc: BaseException) -> DomainError:
    code = _exception_code(exc)
    retryable = isinstance(exc, DomainError) and bool(exc.retryable)
    return DomainError(code, _safe_error_message(code), retryable=retryable)


def _smartedu_headers(token: str = "") -> dict[str, str]:
    """Build auth headers for smartedu CDN requests.

    Uses only x-nd-auth header (matching smartedu-dl-go). Without a token,
    uses dummy auth that works for public resources.
    """
    t = token or "0"
    return {
        "User-Agent": UA,
        "Origin": "https://basic.smartedu.cn",
        "Referer": "https://basic.smartedu.cn/",
        "x-nd-auth": f'MAC id="{t}",nonce="0",mac="0"',
    }


def _stream_download(
    url: str, dest: Path, cancel_event: threading.Event,
    token: str = "",
    *,
    http_client: _SmartEduHttpClient | None = None,
) -> int:
    """Download one direct SmartEdu file through the validated HTTP boundary."""

    client = http_client or _SmartEduHttpClient()
    request = Request(url, headers=_smartedu_headers(token))
    written = 0
    with client.open(request, timeout=120) as response:
        _raise_for_http_status(response)
        with dest.open("wb") as f:
            while True:
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                f.write(chunk)
    return written


def _get_decryption_key(
    key_url: str,
    token: str,
    *,
    http_client: _SmartEduHttpClient | None = None,
) -> bytes:
    """Obtain the AES decryption key for video segments.

    Implements the SmartEdu key derivation algorithm (ported from
    smartedu-dl-go):
      1. GET {keyURL}/signs → nonce
      2. sign = MD5(nonce + keyID)[:16]
      3. GET {keyURL}?nonce={nonce}&sign={sign} → base64 encrypted key
      4. AES-ECB decrypt with sign as key → raw decryption key
    """
    client = http_client or _SmartEduHttpClient()
    headers = _smartedu_headers(token)

    # Extract keyID from URL (last path segment).
    key_id = key_url.rstrip("/").rsplit("/", 1)[-1]

    # 1. Get nonce.
    signs_url = f"{key_url}/signs"
    req = Request(signs_url, headers=headers)
    with client.open(req, timeout=15) as resp:
        _raise_for_http_status(resp)
        signs_data = _read_json_object(
            resp, _KEY_JSON_MAX_BYTES, label="密钥签名响应"
        )
    nonce = signs_data.get("nonce")
    if not nonce:
        raise DomainError("DOWNLOAD_FAILED", "密钥服务未返回 nonce")

    # 2. Compute sign = MD5(nonce + keyID)[:16].
    sign = hashlib.md5(f"{nonce}{key_id}".encode()).hexdigest()[:16]

    # 3. Get encrypted key.
    key_req_url = f"{key_url}?nonce={nonce}&sign={sign}"
    req2 = Request(key_req_url, headers=headers)
    with client.open(req2, timeout=15) as resp2:
        _raise_for_http_status(resp2)
        key_data = _read_json_object(
            resp2, _KEY_JSON_MAX_BYTES, label="密钥响应"
        )
    encrypted_key_b64 = key_data.get("key")
    if not encrypted_key_b64:
        raise DomainError("DOWNLOAD_FAILED", "密钥服务未返回 key")

    # 4. AES-ECB decrypt.
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    encrypted_key = base64.b64decode(encrypted_key_b64)
    cipher = AES.new(sign.encode()[:16], AES.MODE_ECB)
    return unpad(cipher.decrypt(encrypted_key), 16)


def _decrypt_segment(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-CBC decrypt a video segment."""
    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(data)
    # PKCS7 unpad
    pad_len = decrypted[-1]
    if 0 < pad_len <= 16:
        decrypted = decrypted[:-pad_len]
    return decrypted


class SmartEduDownloader:
    """Download resources from SmartEdu via the public CDN detail API.

    Active route supports PDF, direct MP4, MP3, and M4A concrete primaries,
    plus HLS (m3u8) streams that are remuxed losslessly to MP4 with the
    system ffmpeg.
    """

    def __init__(
        self,
        session_store: SessionStore,
        settings: Settings,
        *,
        resolver: Resolver = system_resolver,
        transport: Any | None = None,
    ) -> None:
        self.session_store = session_store
        self.settings = settings
        self.detail_client = _SmartEduHttpClient(
            resolver=resolver,
            transport=transport,
            allowed_hosts=_SMARTEDU_DETAIL_HOSTS,
        )
        self.storage_client = _SmartEduHttpClient(
            resolver=resolver,
            transport=transport,
            allowed_hosts=_SMARTEDU_STORAGE_HOSTS | _SMARTEDU_KEY_HOSTS,
        )

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadReturn:
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")

        source_url = str(resource.get("source_url") or "")
        title = _bounded_text(resource.get("title") or "smartedu_resource", 120)
        content_id, content_type = _resolve_content(source_url)
        planned = resource.pop("_planned_representation", None)
        planned_container = ""
        if isinstance(planned, dict):
            planned_container = str(planned.get("container") or "").casefold()
        if planned_container not in _ACTIVE_PRIMARY_FORMATS:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "SmartEdu 下载缺少受支持的已确认格式",
                retryable=False,
            )
        if planned_container == "m3u8" and not shutil.which("ffmpeg"):
            # MP4 是硬性交付物：没有 ffmpeg 就没有可交付容器，提前失败而不是
            # 下载完分片后才在条目层报错。
            raise DomainError(
                "DOWNLOAD_FAILED",
                "ffmpeg 未安装，无法将 HLS 视频封装为 MP4",
                retryable=False,
            )

        session_data = self.session_store.get_session_data("smartedu")
        token = ""
        if session_data:
            tokens = session_data.get("tokens") or {}
            raw_token = tokens.get("accessToken") or ""
            if raw_token:
                raw_token = str(raw_token)
                token = raw_token[7:] if raw_token.lower().startswith("bearer ") else raw_token

        # Detail lookup is acquisition-wide: without it there is no safe item
        # identity to attach a partial failure to.
        api_url = _detail_api_url(content_id, content_type, source_url)
        request = Request(api_url, headers=_smartedu_headers(token))
        try:
            with self.detail_client.open(request, timeout=20) as resp:
                _raise_for_http_status(resp)
                data = _read_json_object(resp, _DETAIL_MAX_BYTES, label="资源详情")
        except Exception as exc:
            raise _safe_fatal_error(exc) from exc
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        if not isinstance(data, dict):
            raise DomainError("DOWNLOAD_FAILED", "资源详情格式无效", retryable=True)

        files = _find_files(data)
        lookup_failures: list[DownloadItemFailure] = []

        # Textbooks expose relation audio through a second endpoint.  The
        # endpoint failure is retained as a non-required item failure; an
        # authentication, policy, or cancellation failure still aborts the
        # whole acquisition.
        if content_type == "assets_document":
            audio_api = f"{CDN_SPECIAL}/resources/{content_id}/relation_audios.json"
            try:
                audio_req = Request(audio_api, headers=_smartedu_headers(token))
                with self.detail_client.open(audio_req, timeout=10) as audio_resp:
                    _raise_for_http_status(audio_resp)
                    audio_payload = _read_bounded(
                        audio_resp,
                        _RELATION_MAX_BYTES,
                        label="伴随音频详情",
                    )
                    audios = json.loads(
                        audio_payload.decode("utf-8", "replace")
                    )
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                if isinstance(audios, dict):
                    audios = audios.get("resources") or audios.get("data") or []
                if not isinstance(audios, list):
                    raise ValueError("invalid relation audio response")
                files.extend(
                    _find_files(
                        {"relations": {"relation_audios": audios}},
                        source_order_start=len(files),
                    )
                )
            except Exception as exc:
                code = _exception_code(exc)
                if cancel_event.is_set():
                    code = "JOB_CANCELLED"
                if _is_fatal_code(code):
                    raise _safe_fatal_error(exc) from exc
                lookup_candidate = {
                    "item_key": "smartedu:relation_audios:lookup",
                    "relation_key": "relation_audios",
                    "source_order": len(files),
                    "format": "mp3",
                    "ti_file_flag": "relation_lookup",
                    "metadata": {
                        "provider": "smartedu",
                        "relation_key": "relation_audios",
                        "source_order": len(files),
                        "format": "mp3",
                    },
                }
                lookup_failures.append(
                    _make_item_failure(lookup_candidate, "RELATION_AUDIO_LOOKUP_FAILED", required=False)
                )

        if not files:
            if lookup_failures:
                return _make_batch_result([], lookup_failures)
            raise DomainError("DOWNLOAD_FAILED", "该资源无可下载文件", retryable=False)

        active_files = [
            candidate
            for candidate in files
            if str(candidate.get("format") or "").casefold()
            in _ACTIVE_PRIMARY_FORMATS
        ]
        file_key = _smartedu_file_key_from_resource(resource)
        if file_key:
            course_files = _select_course_files(active_files)
            matches = [
                candidate
                for candidate in course_files
                if _smartedu_file_key(content_id, candidate) == file_key
            ]
            if len(matches) != 1:
                raise DomainError(
                    "RESOURCE_NOT_FOUND",
                    "SmartEdu 课程中已找不到所选文件",
                    retryable=False,
                )
            current_primary = matches[0]
            selected = [current_primary]
        else:
            current_primary = _primary_candidate(
                active_files,
                content_type,
                supported_formats=_ACTIVE_PRIMARY_FORMATS,
            )
        if current_primary is None or str(
            current_primary.get("format") or ""
        ).casefold() != planned_container or _smartedu_representation_id(
            resource, current_primary
        ) != str(planned.get("representation_id") or ""):
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "SmartEdu 资源主文件已经变化，请重新检查并准备下载",
                retryable=False,
            )

        if file_key:
            pass
        elif content_type in _COURSE_TYPES:
            selected = _select_course_files(active_files)
        else:
            primary_source = [
                candidate
                for candidate in active_files
                if str(candidate.get("relation_key") or "") != "relation_audios"
            ]
            primary = _primary_candidate(
                primary_source or active_files,
                content_type,
                supported_formats=_ACTIVE_PRIMARY_FORMATS,
            )
            selected = [primary] if primary is not None else []
            # An explicitly declared cover remains useful as an attachment.
            selected.extend(
                candidate
                for candidate in primary_source
                if _is_cover(candidate) and candidate is not primary
            )
            if content_type == "assets_document":
                selected.extend(
                    candidate
                    for candidate in active_files
                    if str(candidate.get("relation_key") or "") == "relation_audios"
                    and candidate is not primary
                )
        selected = sorted(
            {str(item.get("item_key")): item for item in selected}.values(),
            key=lambda item: int(item.get("source_order") or 0),
        )
        if not selected:
            if lookup_failures:
                return _make_batch_result([], lookup_failures)
            raise DomainError("DOWNLOAD_FAILED", "未找到可下载文件", retryable=False)

        primary = _primary_candidate(
            selected,
            content_type,
            supported_formats=_ACTIVE_PRIMARY_FORMATS,
        )
        if primary is None:
            raise DomainError("DOWNLOAD_FAILED", "未找到可用主资源", retryable=False)
        primary_key = str(primary.get("item_key") or "")

        job_dir = self.settings.jobs_dir / job_id
        created_paths: list[Path] = []
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            ensure_within_root(job_dir, self.settings.jobs_dir)
        except Exception as exc:
            raise _safe_fatal_error(exc) from exc

        results: list[DownloadResult] = []
        failures = list(lookup_failures)
        used_names: set[str] = set()
        for candidate in selected:
            required = str(candidate.get("item_key") or "") == primary_key
            role = (
                "primary"
                if file_key
                else _role_for_candidate(
                    candidate,
                    primary_key=primary_key,
                    content_type=content_type,
                )
            )
            destination = job_dir / _safe_destination_name(
                str(candidate.get("title") or title),
                str(candidate.get("format") or "bin"),
                used_names,
                int(candidate.get("source_order") or 0),
            )
            try:
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                ensure_within_root(destination, self.settings.jobs_dir)
                destination.unlink(missing_ok=True)
                fmt = str(candidate.get("format") or "").casefold()
                if fmt == "m3u8":
                    # HLS 物化：分片顺序拼接后经 ffmpeg 无损封装为 MP4。
                    _download_hls_to_mp4(
                        str(candidate["url"]),
                        destination,
                        cancel_event,
                        token,
                        http_client=self.storage_client,
                    )
                else:
                    _stream_download(
                        str(candidate["url"]),
                        destination,
                        cancel_event,
                        token,
                        http_client=self.storage_client,
                    )
                media_type = _media_type_for_format(fmt)
                byte_size = destination.stat().st_size
                if byte_size <= 0:
                    raise DomainError("CONTENT_VALIDATION_FAILED", "下载内容为空")
                _validate_downloaded_file(destination, media_type)
                digest = hashlib.sha256()
                with destination.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(64 * 1024), b""):
                        digest.update(chunk)
                created_paths.append(destination)
                results.append(
                    _make_download_result(
                        destination,
                        byte_size,
                        media_type,
                        digest.hexdigest(),
                        destination.name,
                        candidate,
                        role=role,
                        required=required,
                    )
                )
            except Exception as exc:
                destination.unlink(missing_ok=True)
                code = "JOB_CANCELLED" if cancel_event.is_set() else _exception_code(exc)
                if _is_fatal_code(code):
                    for path in created_paths:
                        path.unlink(missing_ok=True)
                    raise _safe_fatal_error(
                        DomainError(code, _safe_error_message(code))
                    ) from exc
                failures.append(
                    _make_item_failure(candidate, code, required=required, role=role)
                )

        if failures or len(results) > 1:
            return _make_batch_result(results, failures)
        if results:
            return results[0]
        return _make_batch_result([], failures)
