#!/usr/bin/env python3
"""Manage an optional SmartEdu browser session without leaking secrets."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.logger import getLogger
log = getLogger("smartedu")


DEFAULT_WORK_DIR = ".learning-resource-work/smartedu-browser"
DEFAULT_HOME_URL = "https://basic.smartedu.cn/"
DEFAULT_SEARCH_URL = "https://x-search.ykt.eduyun.cn/v1/resources/combine/search"
DEFAULT_SDP_APP_ID = "e5649925-441d-4a53-b525-51a2f1c4e0a8"
SECRET_HEADER_NAMES = {"authorization", "cookie", "x-nd-auth", "set-cookie", "accessToken".lower()}
DEFAULT_BROWSER_CANDIDATES = [
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path | None, data: Any) -> None:
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


def state_path(args: argparse.Namespace) -> Path:
    return Path(args.state_json or Path(args.work_dir) / "state.json")


def summary_path(args: argparse.Namespace) -> Path:
    return Path(args.summary_json or Path(args.work_dir) / "session-summary.json")


def playwright_module() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("缺少可选依赖 playwright；需要先安装并执行 `python3 -m playwright install chromium`。") from exc
    return sync_playwright


def browser_executable(args: argparse.Namespace) -> str | None:
    explicit = args.executable_path or os.environ.get("SMARTEDU_BROWSER_EXECUTABLE") or ""
    if explicit:
        return explicit
    return None


def cookie_domain(cookie: dict[str, Any]) -> str:
    return str(cookie.get("domain") or "").lstrip(".")


def summarize_state(state: dict[str, Any], state_file: Path | None = None) -> dict[str, Any]:
    cookies = [item for item in state.get("cookies") or [] if isinstance(item, dict)]
    origins = [item for item in state.get("origins") or [] if isinstance(item, dict)]
    domains = sorted({cookie_domain(item) for item in cookies if cookie_domain(item)})
    expires_values = [float(item.get("expires")) for item in cookies if isinstance(item.get("expires"), (int, float)) and float(item.get("expires")) > 0]
    smartedu_domains = [domain for domain in domains if "smartedu.cn" in domain or "ykt.cbern.com.cn" in domain or "eduyun.cn" in domain]
    return {
        "browser_session_schema": "smartedu-browser-session/v1",
        "created_at": now_iso(),
        "state_file": str(state_file) if state_file else "",
        "state_file_exists": bool(state_file and state_file.exists()),
        "auth_context": bool(cookies),
        "has_cookie": bool(cookies),
        "cookie_count": len(cookies),
        "cookie_domains": domains,
        "smartedu_cookie_domains": smartedu_domains,
        "local_storage_origins": sorted(str(item.get("origin")) for item in origins if item.get("origin")),
        "cookie_expires_min": min(expires_values) if expires_values else None,
        "cookie_expires_max": max(expires_values) if expires_values else None,
        "capabilities": {
            "can_use_browser_state": bool(cookies),
            "can_fetch_detail": None,
            "can_probe_private_ndr": None,
        },
        "secret_redaction": "不输出 cookie、Authorization、MAC、x-nd-auth 或浏览器 state 原文。",
    }


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    kept: dict[str, str] = {}
    for name, value in headers.items():
        lower = name.lower()
        if lower in SECRET_HEADER_NAMES:
            kept[name] = "***"
        elif lower in {"content-type", "content-length", "accept-ranges", "last-modified", "etag", "cache-control"}:
            kept[name] = value
    return kept


def response_summary(response: Any, include_json: bool = False, max_text_chars: int = 2000) -> dict[str, Any]:
    headers = dict(response.headers or {})
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    result: dict[str, Any] = {
        "ok": bool(response.ok),
        "status": response.status,
        "status_text": response.status_text,
        "url": response.url,
        "content_type": content_type,
        "headers": safe_headers(headers),
    }
    if "application/json" in content_type.lower():
        try:
            data = response.json()
            result["has_json"] = True
            result["json_keys"] = sorted(data.keys()) if isinstance(data, dict) else []
            if include_json:
                result["json"] = data
        except Exception as exc:
            result["has_json"] = False
            result["error"] = str(exc)
    elif include_json:
        try:
            result["text_sample"] = response.text()[:max_text_chars]
        except Exception as exc:
            result["error"] = str(exc)
    return result


def parse_headers(values: list[str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values or []:
        if ":" not in value:
            raise ValueError("--header must use 'Name: value' format")
        name, header_value = value.split(":", 1)
        name = name.strip()
        header_value = header_value.strip()
        if name and header_value:
            headers[name] = header_value
    return headers


def search_payload(keyword: str, limit: int) -> dict[str, Any]:
    return {
        "identity": "家长",
        "identity_code": "GUARDIAN",
        "keyword": keyword,
        "tab_codes": ["sedu", "qualityCourse", "prepareLesson", "questions", "examinationPapers", "tchMaterial"],
        "cross_tenant": True,
        "duplicate_filter": True,
        "search_order": {"field": "_score", "direction": "desc"},
        "offset": 0,
        "limit": limit,
        "combine_intentions": [],
        "combine_resources": [],
    }


def request_context(playwright: Any, state_file: Path, timeout_ms: int) -> Any:
    return playwright.request.new_context(
        storage_state=str(state_file),
        extra_http_headers={
            "Origin": "https://basic.smartedu.cn",
            "Referer": "https://basic.smartedu.cn/",
            "User-Agent": "Mozilla/5.0 smartedu-browser-session/0.1",
            "sdp-app-id": DEFAULT_SDP_APP_ID,
        },
        timeout=timeout_ms,
    )


def run_login(args: argparse.Namespace) -> int:
    sync_playwright = playwright_module()
    target_state = state_path(args)
    target_state.parent.mkdir(parents=True, exist_ok=True)
    executable = browser_executable(args)
    with sync_playwright() as p:
        if args.cdp_url:
            browser = p.chromium.connect_over_cdp(args.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            browser_type = p.firefox if args.browser == "firefox" else p.chromium
            browser_args = (
                [
                    "--disable-crash-reporter",
                    "--disable-crashpad",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                ]
                if args.browser == "chromium"
                else []
            )
            browser = browser_type.launch(
                headless=False,
                executable_path=executable,
                args=browser_args,
            )
            context = browser.new_context()
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
        print("请在打开的浏览器中完成 SmartEdu 登录。登录完成后回到终端按 Enter 保存会话。", file=sys.stderr)
        input()
        context.storage_state(path=str(target_state))
        browser.close()
    summary = summarize_state(load_json(target_state), target_state)
    write_json(summary_path(args), summary)
    write_json(args.output, summary)
    return 0


def run_export_context(args: argparse.Namespace) -> int:
    target_state = state_path(args)
    if not target_state.exists():
        raise FileNotFoundError(f"missing browser state: {target_state}")
    summary = summarize_state(load_json(target_state), target_state)
    if args.summary_json:
        write_json(summary_path(args), summary)
    write_json(args.output, summary)
    return 0


def run_check(args: argparse.Namespace) -> int:
    target_state = state_path(args)
    if not target_state.exists():
        raise FileNotFoundError(f"missing browser state: {target_state}")
    state_summary = summarize_state(load_json(target_state), target_state)
    probes: list[dict[str, Any]] = []
    if not args.offline:
        sync_playwright = playwright_module()
        with sync_playwright() as p:
            request = request_context(p, target_state, args.timeout * 1000)
            search_response = request.post(args.search_url, data=search_payload(args.query, args.limit))
            probes.append({"name": "x-search", **response_summary(search_response)})
            if args.detail_url:
                probes.append({"name": "detail-json", **response_summary(request.get(args.detail_url))})
            if args.ndr_url:
                probes.append({"name": "ndr-range", **response_summary(request.get(args.ndr_url, headers={"Range": "bytes=0-0"}))})
            request.dispose()
    capabilities = dict(state_summary["capabilities"])
    capabilities["can_fetch_detail"] = any(item.get("name") == "detail-json" and item.get("ok") for item in probes) if args.detail_url else None
    capabilities["can_probe_private_ndr"] = any(item.get("name") == "ndr-range" and item.get("ok") for item in probes) if args.ndr_url else None
    result = {
        **state_summary,
        "checked_at": now_iso(),
        "offline": bool(args.offline),
        "probes": probes,
        "capabilities": capabilities,
    }
    write_json(summary_path(args), result)
    write_json(args.output, result)
    return 0


def run_request(args: argparse.Namespace) -> int:
    target_state = state_path(args)
    if not target_state.exists():
        raise FileNotFoundError(f"missing browser state: {target_state}")
    sync_playwright = playwright_module()
    payload = None
    if args.json_body:
        payload = json.loads(args.json_body)
    elif args.body_file:
        payload = load_json(args.body_file)
    headers = parse_headers(args.header)
    with sync_playwright() as p:
        request = request_context(p, target_state, args.timeout * 1000)
        method = args.method.upper()
        if method == "GET":
            response = request.get(args.url, headers=headers)
        elif method == "POST":
            response = request.post(args.url, data=payload, headers=headers)
        elif method == "HEAD":
            response = request.head(args.url, headers=headers)
        else:
            raise ValueError("--method only supports GET, POST, HEAD")
        result = {
            "browser_request_schema": "smartedu-browser-request/v1",
            "requested_at": now_iso(),
            "method": method,
            "url": args.url,
            "auth_context": True,
            "response": response_summary(response, include_json=args.include_json, max_text_chars=args.max_text_chars),
            "secret_redaction": "输出不包含 cookie、Authorization、MAC、x-nd-auth 或请求头原文。",
        }
        request.dispose()
    write_json(args.output, result)
    return 0 if result["response"].get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartEdu browser session helper")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--work-dir", default=DEFAULT_WORK_DIR, help="浏览器会话工作目录")
        command.add_argument("--state-json", help="Playwright storage state 路径，默认 work-dir/state.json")
        command.add_argument("--summary-json", help="会话摘要路径，默认 work-dir/session-summary.json")
        command.add_argument("-o", "--output", help="写入 JSON 文件；省略时输出到 stdout")

    login = sub.add_parser("login", help="打开浏览器，由用户正常登录 SmartEdu 并保存 storage state")
    add_common(login)
    login.add_argument("--url", default=DEFAULT_HOME_URL, help="登录起始 URL")
    login.add_argument("--browser", choices=["chromium", "firefox"], default="chromium", help="登录浏览器，默认 chromium")
    login.add_argument("--executable-path", help="浏览器可执行文件路径；WSL 可使用 Windows Chrome/Edge 路径")
    login.add_argument("--cdp-url", help="连接已开启 remote-debugging-port 的浏览器，例如 http://127.0.0.1:9222")
    login.add_argument("--timeout", type=int, default=60, help="页面加载超时秒数")
    login.set_defaults(func=run_login)

    check = sub.add_parser("check", help="检查已保存浏览器 state 的可用性")
    add_common(check)
    check.add_argument("--offline", action="store_true", help="只检查本地 state 摘要，不发起网络请求")
    check.add_argument("--query", default="数学五年级", help="搜索探针关键词")
    check.add_argument("--limit", type=int, default=1, help="搜索探针 limit")
    check.add_argument("--search-url", default=DEFAULT_SEARCH_URL, help="搜索探针 URL")
    check.add_argument("--detail-url", help="可选详情 JSON 探针 URL")
    check.add_argument("--ndr-url", help="可选 NDR 文件 range 探针 URL")
    check.add_argument("--timeout", type=int, default=20, help="请求超时秒数")
    check.set_defaults(func=run_check)

    export_context = sub.add_parser("export-context", help="导出脱敏会话摘要，不输出 cookie 原文")
    add_common(export_context)
    export_context.set_defaults(func=run_export_context)

    request = sub.add_parser("request", help="使用浏览器 state 发起一次受控请求")
    add_common(request)
    request.add_argument("--url", required=True, help="请求 URL")
    request.add_argument("--method", default="GET", help="GET、POST 或 HEAD")
    request.add_argument("--json-body", help="POST JSON 字符串")
    request.add_argument("--body-file", help="POST JSON 文件")
    request.add_argument("--header", action="append", help="额外请求头，格式 'Name: value'；输出会脱敏敏感头")
    request.add_argument("--include-json", action="store_true", help="响应为 JSON 时输出响应 JSON；不要用于含敏感数据的接口")
    request.add_argument("--max-text-chars", type=int, default=2000, help="非 JSON 响应最多输出多少字符")
    request.add_argument("--timeout", type=int, default=20, help="请求超时秒数")
    request.set_defaults(func=run_request)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
