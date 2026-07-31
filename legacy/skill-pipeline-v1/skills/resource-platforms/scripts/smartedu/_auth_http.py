#!/usr/bin/env python3
"""SmartEdu HTTP 与授权传输层。

Phase 3E 从 smartedu_resources.py 拆出的底层模块：.env.local 加载、请求头/token
构建、JSON 与文本请求。纯传输层，不含 SmartEdu 业务逻辑；smartedu_resources.py
通过 import 复用，行为与拆分前完全一致。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import urllib.parse
from urllib.error import HTTPError, URLError
from urllib.request import Request

from shared.http_client import urlopen_with_fallback


DEFAULT_SDP_APP_ID = "e5649925-441d-4a53-b525-51a2f1c4e0a8"


def load_local_env() -> None:
    roots = [Path.cwd(), Path(__file__).resolve().parents[3]]
    seen: set[Path] = set()
    for root in roots:
        env_file = root / ".env.local"
        if env_file in seen or not env_file.exists():
            continue
        seen.add(env_file)
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


# 导入本模块即加载 .env.local，与拆分前在 smartedu_resources.py 顶层调用 load_local_env() 行为一致。
load_local_env()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def parse_extra_headers(values: list[str] | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    raw_values = list(values or [])
    env_headers = os.environ.get("SMARTEDU_HEADERS")
    if env_headers:
        raw_values.extend(part.strip() for part in env_headers.splitlines() if part.strip())
    for value in raw_values:
        if ":" not in value:
            raise ValueError("--header must use 'Name: value' format")
        name, header_value = value.split(":", 1)
        name = name.strip()
        header_value = header_value.strip()
        if name and header_value:
            headers[name] = header_value
    return headers


def build_headers(access_token: str | None = None, cookie: str | None = None, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    extra_headers = extra_headers or {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://basic.smartedu.cn",
        "Referer": "https://basic.smartedu.cn/",
        "sdp-app-id": os.environ.get("SMARTEDU_SDP_APP_ID", DEFAULT_SDP_APP_ID),
    }
    token = _norm(access_token)
    if token:
        raw_token = token[7:].strip() if token.lower().startswith("bearer ") else token
        headers["Authorization"] = f"Bearer {raw_token}"
        headers["accessToken"] = raw_token
    authorization = os.environ.get("SMARTEDU_AUTHORIZATION")
    cookie = cookie or os.environ.get("SMARTEDU_COOKIE")
    if authorization:
        headers["Authorization"] = authorization
    if cookie:
        headers["Cookie"] = cookie
    headers.update(extra_headers)
    headers["Content-Type"] = "application/json;charset=UTF-8"
    return headers


def has_auth_context(access_token: str | None, cookie: str | None, extra_headers: dict[str, str]) -> bool:
    return bool(
        access_token
        or cookie
        or extra_headers
        or os.environ.get("SMARTEDU_COOKIE")
        or os.environ.get("SMARTEDU_AUTHORIZATION")
    )


def has_runtime_auth_context(access_token: str | None, cookie: str | None, extra_headers: dict[str, str], args: argparse.Namespace) -> bool:
    return has_auth_context(access_token, cookie, extra_headers) or bool(getattr(args, "browser_state", None))


def is_cdn_json_url(url: str) -> bool:
    """s-file-*.ykt.cbern.com.cn 的详情 JSON 是纯公开 CDN 资源——
    Go 项目 smartedu-dl-go 的 FetchJsonData 不加任何 header 就能获取。
    加了 Content-Type / Origin / Referer 反而触发 CDN WAF 403。
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    return host.startswith("s-file-") and host.endswith(".ykt.cbern.com.cn")


def bare_request_json(url: str, timeout: int = 20) -> Any:
    """对 s-file-* CDN 的 JSON 使用裸 GET（不附加任何业务 header），
    与 Go 项目 FetchJsonData 行为一致。"""
    request = Request(url, headers={"User-Agent": "Go-http-client/1.1"})
    with urlopen_with_fallback(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def bare_request_json_status(url: str, timeout: int = 20) -> tuple[dict[str, Any] | None, int | None, str, str]:
    """裸 GET 带 HTTP 状态码返回，用于详情 JSON 探测。"""
    request = Request(url, headers={"User-Agent": "Go-http-client/1.1"})
    try:
        with urlopen_with_fallback(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                return None, response.status, content_type, f"json decode failed: {exc}"
            return parsed if isinstance(parsed, dict) else {"data": parsed}, response.status, content_type, ""
    except HTTPError as exc:
        return None, exc.code, exc.headers.get("Content-Type", ""), str(exc)
    except (URLError, TimeoutError) as exc:
        return None, None, "", str(exc)


def request_json(
    url: str,
    access_token: str | None = None,
    timeout: int = 20,
    retries: int = 2,
    payload: Any = None,
    cookie: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    # s-file-* CDN JSON 使用裸 GET，不加业务 header（否则触发 403）
    if payload is None and is_cdn_json_url(url):
        return bare_request_json(url, timeout=timeout)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            data = None
            if payload is not None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request = Request(url, data=data, headers=build_headers(access_token, cookie=cookie, extra_headers=extra_headers))
            with urlopen_with_fallback(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_error}")


def request_json_status(
    url: str,
    access_token: str | None = None,
    timeout: int = 20,
    payload: Any = None,
    cookie: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, int | None, str, str]:
    # s-file-* CDN JSON 使用裸 GET，不加业务 header（否则触发 403）
    if payload is None and is_cdn_json_url(url):
        return bare_request_json_status(url, timeout=timeout)

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers=build_headers(access_token, cookie=cookie, extra_headers=extra_headers))
    try:
        with urlopen_with_fallback(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                return None, response.status, content_type, f"json decode failed: {exc}"
            return parsed if isinstance(parsed, dict) else {"data": parsed}, response.status, content_type, ""
    except HTTPError as exc:
        return None, exc.code, exc.headers.get("Content-Type", ""), str(exc)
    except (URLError, TimeoutError) as exc:
        return None, None, "", str(exc)


def browser_request_json_status(url: str, browser_state: str, timeout: int = 20) -> tuple[dict[str, Any] | None, int | None, str, str]:
    if not browser_state:
        return None, None, "", "missing browser state"
    state_file = Path(browser_state)
    if not state_file.exists():
        return None, None, "", f"missing browser state: {state_file}"
    script = Path(__file__).with_name("smartedu_browser_session.py")
    command = [
        sys.executable,
        str(script),
        "request",
        "--state-json",
        str(state_file),
        "--url",
        url,
        "--include-json",
        "--timeout",
        str(timeout),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    output = completed.stdout.strip()
    if not output:
        return None, None, "", completed.stderr.strip() or f"browser request failed: exit {completed.returncode}"
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        return None, None, "", f"browser request output decode failed: {exc}"
    response = data.get("response") if isinstance(data, dict) else {}
    if not isinstance(response, dict):
        return None, None, "", "browser request response missing"
    detail = response.get("json") if isinstance(response.get("json"), dict) else None
    status = response.get("status") if isinstance(response.get("status"), int) else None
    content_type = _norm(response.get("content_type"))
    error = _norm(response.get("error")) or (completed.stderr.strip() if completed.returncode not in {0, 1} else "")
    return detail, status, content_type, error


def request_text(
    url: str,
    access_token: str | None = None,
    timeout: int = 20,
    cookie: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> str:
    request = Request(url, headers=build_headers(access_token, cookie=cookie, extra_headers=extra_headers))
    with urlopen_with_fallback(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")
