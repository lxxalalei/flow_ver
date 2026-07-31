#!/usr/bin/env python3
"""Crawler for SmartEdu textbook material metadata.

The public textbook page is a React app. Its textbook list is backed by static
JSON feeds under /zxx/ndrs/resources/tch_material, and per-resource details are
available under /zxx/ndrv2/resources/tch_material/details/{id}.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.logger import getLogger
log = getLogger("smartedu")

from _auth_http import load_local_env


# 与 smartedu_resources / download_selected 一致：import 即加载 .env.local，
# 使 standalone 运行（如 fetch_textbooks 直接调用）也能自动获取 SMARTEDU_ACCESS_TOKEN。
load_local_env()


VERSION_URL = (
    "https://s-file-2.ykt.cbern.com.cn/"
    "zxx/ndrs/resources/tch_material/version/data_version.json"
)
TAG_URL = (
    "https://s-file-1.ykt.cbern.com.cn/"
    "zxx/ndrs/tags/tch_material_tag.json"
)
DETAIL_URLS = (
    "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{id}.json",
    "https://s-file-2.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{id}.json",
)
DETAIL_PAGE = (
    "https://basic.smartedu.cn/tchMaterial/detail?"
    "contentType={content_type}&contentId={id}&catalogType=tchMaterial&subCatalog=tchMaterial"
)
PUBLIC_NDR_HOSTS = (
    "https://r1-ndr.ykt.cbern.com.cn",
    "https://r2-ndr.ykt.cbern.com.cn",
    "https://r3-ndr.ykt.cbern.com.cn",
)
PRIVATE_NDR_RE = re.compile(r"https://r[123]-ndr-private\.ykt\.cbern\.com\.cn")


TAG_DIMENSIONS = {
    "5036342742": "category",
    "tagView": "tag_view",
    "zxxxd": "stage",
    "zxxxk": "subject",
    "zxxbb": "version",
    "zxxnj": "grade",
    "zxxcc": "volume",
}


class FetchError(RuntimeError):
    pass


def build_headers(access_token: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 smartedu-tch-material-crawler/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://basic.smartedu.cn/tchMaterial",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        headers["accessToken"] = access_token
    if extra:
        headers.update(extra)
    return headers


def token_from_args(args: argparse.Namespace) -> str | None:
    token = getattr(args, "access_token", None) or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    return token.strip() if token else None


def request_json(url: str, timeout: int = 30, retries: int = 2, access_token: str | None = None) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(
                url,
                headers=build_headers(access_token),
            )
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            return json.loads(body.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise FetchError(f"fetch failed: {url}: {last_error}")


def request_bytes(
    url: str,
    timeout: int = 30,
    retries: int = 2,
    access_token: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(
                url,
                headers=build_headers(access_token, extra_headers),
            )
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise FetchError(f"download failed: {url}: {last_error}")


def append_access_token(url: str, access_token: str | None) -> str:
    if not access_token:
        return url
    parsed = urlparse(url)
    query = parsed.query
    sep = "&" if query else ""
    query = f"{query}{sep}{urlencode({'accessToken': access_token})}"
    return urlunparse(parsed._replace(query=query))


def mask_secret(text: str, access_token: str | None = None) -> str:
    if access_token:
        text = text.replace(access_token, "***")
    text = re.sub(r"(accessToken=)[^&\s'\"]+", r"\1***", text)
    text = re.sub(r"(Authorization: Bearer )[A-Za-z0-9._-]+", r"\1***", text)
    return text


def quote_url_path(url: str) -> str:
    parsed = urlparse(url)
    path = quote(unquote(parsed.path), safe="/:")
    return urlunparse(parsed._replace(path=path))


def download_file(url: str, path: Path, access_token: str | None = None, timeout: int = 60) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    attempts = [url]
    if access_token:
        attempts.append(append_access_token(url, access_token))

    for attempt_url in attempts:
        try:
            req = Request(attempt_url, headers=build_headers(access_token))
            with urlopen(req, timeout=timeout) as resp, path.open("wb") as out:
                while True:
                    chunk = resp.read(1024 * 512)
                    if not chunk:
                        break
                    out.write(chunk)
            size = path.stat().st_size
            if size <= 0:
                raise FetchError("downloaded empty file")
            return size
        except (HTTPError, URLError, TimeoutError, FetchError) as exc:
            last_error = exc
            if path.exists():
                path.unlink()
    raise FetchError(mask_secret(f"file download failed: {url}: {last_error}", access_token))


def probe_url(url: str, access_token: str | None = None) -> tuple[bool, str]:
    last_error: Exception | None = None
    attempts = [url]
    if access_token:
        attempts.append(append_access_token(url, access_token))
    for attempt_url in attempts:
        try:
            data = request_bytes(
                attempt_url,
                timeout=20,
                retries=0,
                access_token=access_token,
                extra_headers={"Range": "bytes=0-1023"},
            )
            return True, f"ok {len(data)} bytes"
        except Exception as exc:
            last_error = exc
    return False, mask_secret(str(last_error), access_token)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_name(value: str, limit: int = 120) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] or "untitled"


def parse_version_urls(version_data: dict[str, Any]) -> list[str]:
    urls = version_data.get("urls", "")
    if isinstance(urls, str):
        return [url.strip() for url in urls.split(",") if url.strip()]
    if isinstance(urls, list):
        return [str(url) for url in urls]
    return []


def sync_index(out_dir: Path, include_raw: bool = True) -> list[dict[str, Any]]:
    raw_dir = out_dir / "raw"
    version = request_json(VERSION_URL)
    urls = parse_version_urls(version)
    if not urls:
        raise FetchError("version feed did not contain part URLs")

    parts: list[list[dict[str, Any]]] = []
    for index, url in enumerate(urls):
        part = request_json(url)
        if not isinstance(part, list):
            raise FetchError(f"part feed is not a list: {url}")
        parts.append(part)
        if include_raw:
            write_json(raw_dir / f"part_{index}.json", part)

    records = [item for part in parts for item in part]
    tag_tree = request_json(TAG_URL)

    write_json(out_dir / "version.json", version)
    write_json(out_dir / "tags.json", tag_tree)
    write_json(out_dir / "textbooks.raw.json", records)
    normalized = [normalize_record(item) for item in records]
    write_json(out_dir / "textbooks.json", normalized)
    return normalized


def tags_by_dimension(record: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for tag in record.get("tag_list") or []:
        dim = TAG_DIMENSIONS.get(str(tag.get("tag_dimension_id")))
        if dim and dim not in values:
            values[dim] = tag.get("tag_name") or ""
    return values


def provider_names(record: dict[str, Any]) -> list[str]:
    providers = record.get("provider_list") or []
    names = [item.get("name") for item in providers if item.get("name")]
    return names or ["智慧中小学"]


def preview_urls(record: dict[str, Any]) -> list[str]:
    custom = record.get("custom_properties") or {}
    preview = custom.get("preview") or {}
    items: list[tuple[int, str]] = []
    for key, value in preview.items():
        if not isinstance(value, str):
            continue
        match = re.search(r"(\d+)$", str(key))
        order = int(match.group(1)) if match else len(items) + 1
        items.append((order, value))
    return [value for _, value in sorted(items)]


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    custom = record.get("custom_properties") or {}
    dimensions = tags_by_dimension(record)
    resource_id = record.get("id") or record.get("global_resource_id")
    content_type = record.get("resource_type_code") or "assets_document"
    title = record.get("title") or (record.get("global_title") or {}).get("zh-CN") or ""
    previews = preview_urls(record)
    thumb = None
    thumbnails = custom.get("thumbnails") or []
    if thumbnails:
        thumb = thumbnails[0]
    elif previews:
        thumb = previews[0]
    return {
        "id": resource_id,
        "version_id": record.get("version_id"),
        "title": title,
        "description": record.get("description") or "",
        "status": record.get("status"),
        "format": custom.get("format"),
        "size": custom.get("size"),
        "width": custom.get("width"),
        "height": custom.get("height"),
        "resolution": custom.get("resolution"),
        "stage": dimensions.get("stage"),
        "subject": dimensions.get("subject"),
        "version": dimensions.get("version"),
        "grade": dimensions.get("grade"),
        "volume": dimensions.get("volume"),
        "category": dimensions.get("category"),
        "providers": provider_names(record),
        "thumbnail": thumb,
        "preview_count": len(previews),
        "preview_urls": previews,
        "detail_page": DETAIL_PAGE.format(
            id=quote(str(resource_id)),
            content_type=quote(str(content_type)),
        ),
        "create_time": record.get("create_time"),
        "update_time": record.get("update_time"),
        "online_time": record.get("online_time"),
        "tag_list": record.get("tag_list") or [],
        "tag_paths": record.get("tag_paths") or [],
    }


def load_records(data_dir: Path, raw: bool = False) -> list[dict[str, Any]]:
    path = data_dir / ("textbooks.raw.json" if raw else "textbooks.json")
    if not path.exists():
        raise SystemExit(f"missing {path}; run sync first")
    data = read_json(path)
    if not isinstance(data, list):
        raise SystemExit(f"{path} is not a list")
    return data


def matches_filters(record: dict[str, Any], args: argparse.Namespace) -> bool:
    query = (args.query or "").strip().lower()
    if query:
        haystack = json.dumps(record, ensure_ascii=False).lower()
        if query not in haystack:
            return False
    for field in ("stage", "subject", "version", "grade", "volume"):
        expected = getattr(args, field, None)
        if expected and expected not in str(record.get(field) or ""):
            return False
    return True


def filter_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = [record for record in records if matches_filters(record, args)]
    if args.limit:
        rows = rows[: args.limit]
    return rows


def export_csv(records: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "title",
        "stage",
        "subject",
        "version",
        "grade",
        "volume",
        "providers",
        "format",
        "size",
        "preview_count",
        "thumbnail",
        "detail_page",
        "update_time",
    ]
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field) for field in fields}
            row["providers"] = "/".join(record.get("providers") or [])
            writer.writerow(row)


def fetch_detail(
    resource_id: str,
    detail_dir: Path | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    if detail_dir:
        cached = detail_dir / f"{resource_id}.json"
        if cached.exists():
            return read_json(cached)
    errors = []
    for template in DETAIL_URLS:
        url = template.format(id=quote(resource_id))
        try:
            detail = request_json(url, access_token=access_token)
            if detail_dir:
                write_json(detail_dir / f"{resource_id}.json", detail)
            return detail
        except FetchError as exc:
            errors.append(str(exc))
    raise FetchError("; ".join(errors))


def extract_pdf_items(detail: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for item in detail.get("ti_items") or []:
        if item.get("ti_format") == "pdf" or item.get("lc_ti_format") == "pdf":
            items.append(item)
    return items


def public_url_candidates(item: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for value in item.get("ti_storages") or []:
        if not isinstance(value, str):
            continue
        candidates.append(quote_url_path(value))
        candidates.append(quote_url_path(PRIVATE_NDR_RE.sub(PUBLIC_NDR_HOSTS[0], value)))

    storage = item.get("ti_storage")
    if isinstance(storage, str) and storage.startswith("cs_path:${ref-path}"):
        suffix = storage.replace("cs_path:${ref-path}", "")
        for host in PUBLIC_NDR_HOSTS:
            candidates.append(host + quote(unquote(suffix), safe="/:"))

    seen = set()
    unique = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def enrich_pdf_metadata(
    records: list[dict[str, Any]],
    data_dir: Path,
    workers: int,
    limit: int | None,
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    detail_dir = data_dir / "details"
    selected = records[:limit] if limit else records
    enriched: list[dict[str, Any]] = []

    def work(record: dict[str, Any]) -> dict[str, Any]:
        rid = str(record["id"])
        detail = fetch_detail(rid, detail_dir, access_token=access_token)
        pdf_items = extract_pdf_items(detail)
        result = dict(record)
        result["pdf_items"] = pdf_items
        result["pdf_urls"] = [url for item in pdf_items for url in public_url_candidates(item)]
        result["smart_link"] = (detail.get("smart_link") or {}).get("smart_link")
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, record): record for record in selected}
        for future in as_completed(futures):
            record = futures[future]
            try:
                enriched.append(future.result())
            except Exception as exc:
                failed = dict(record)
                failed["pdf_error"] = str(exc)
                enriched.append(failed)
    enriched.sort(key=lambda item: str(item.get("id")))
    write_json(data_dir / "textbooks.with_pdf_meta.json", enriched)
    return enriched


def download_previews(records: list[dict[str, Any]], out_dir: Path, workers: int, pages: int | None) -> None:
    tasks: list[tuple[str, Path]] = []
    for record in records:
        title = safe_name(f"{record.get('subject') or 'unknown'}_{record.get('title') or record.get('id')}")
        book_dir = out_dir / f"{record.get('id')}_{title}"
        urls = record.get("preview_urls") or []
        if pages:
            urls = urls[:pages]
        for index, url in enumerate(urls, start=1):
            parsed = urlparse(url)
            ext = Path(parsed.path).suffix or ".jpg"
            tasks.append((url, book_dir / f"{index:04d}{ext}"))

    def work(task: tuple[str, Path]) -> str:
        url, path = task
        if path.exists() and path.stat().st_size > 0:
            return f"skip {path}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(request_bytes(url))
        return f"ok {path}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, task) for task in tasks]
        for future in as_completed(futures):
            done += 1
            try:
                msg = future.result()
            except Exception as exc:
                msg = f"error {exc}"
            if done % 20 == 0 or msg.startswith("error"):
                log.info("[%d/%d] %s", done, len(tasks), msg)


def download_pdfs(
    records: list[dict[str, Any]],
    data_dir: Path,
    out_dir: Path,
    workers: int,
    access_token: str | None,
    probe_only: bool,
) -> list[dict[str, Any]]:
    detail_dir = data_dir / "details"
    manifest: list[dict[str, Any]] = []

    def work(record: dict[str, Any]) -> dict[str, Any]:
        rid = str(record["id"])
        title = safe_name(f"{record.get('subject') or 'unknown'}_{record.get('title') or rid}")
        result = {
            "id": rid,
            "title": record.get("title"),
            "stage": record.get("stage"),
            "subject": record.get("subject"),
            "version": record.get("version"),
            "grade": record.get("grade"),
            "volume": record.get("volume"),
            "downloaded": False,
            "file": None,
            "size": 0,
            "error": None,
        }
        detail = fetch_detail(rid, detail_dir, access_token=access_token)
        pdf_items = extract_pdf_items(detail)
        urls = [url for item in pdf_items for url in public_url_candidates(item)]
        result["pdf_url_count"] = len(urls)
        result["pdf_urls"] = urls
        if not urls:
            result["error"] = "no pdf url candidates"
            return result

        if probe_only:
            probes = []
            for url in urls[:4]:
                ok, message = probe_url(url, access_token=access_token)
                probes.append({"url": url, "ok": ok, "message": message})
                if ok:
                    result["downloaded"] = True
                    break
            result["probes"] = probes
            if not result["downloaded"]:
                result["error"] = probes[-1]["message"] if probes else "probe failed"
            return result

        errors = []
        for url in urls:
            parsed = urlparse(url)
            suffix = Path(unquote(parsed.path)).suffix or ".pdf"
            path = out_dir / f"{rid}_{title}{suffix}"
            try:
                size = download_file(url, path, access_token=access_token)
                result["downloaded"] = True
                result["file"] = str(path)
                result["size"] = size
                return result
            except Exception as exc:
                errors.append(str(exc))
        result["error"] = errors[-1] if errors else "download failed"
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, record): record for record in records}
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception as exc:
                record = futures[future]
                item = {
                    "id": record.get("id"),
                    "title": record.get("title"),
                    "downloaded": False,
                    "error": str(exc),
                }
            manifest.append(item)
            status = "ok" if item.get("downloaded") else "failed"
            log.info("%s\t%s\t%s", status, item.get('id'), item.get('title'))

    manifest.sort(key=lambda item: str(item.get("id")))
    write_json(out_dir / "manifest.json", manifest)
    return manifest


def cmd_sync(args: argparse.Namespace) -> None:
    records = sync_index(Path(args.data_dir), include_raw=not args.no_raw)
    log.info("synced %d textbook records into %s", len(records), args.data_dir)


def cmd_list(args: argparse.Namespace) -> None:
    records = filter_records(load_records(Path(args.data_dir)), args)
    for record in records:
        print(
            "\t".join(
                str(record.get(field) or "")
                for field in ("id", "stage", "subject", "version", "grade", "volume", "title")
            )
        )
    log.info("matched %d records", len(records))


def cmd_export_csv(args: argparse.Namespace) -> None:
    records = filter_records(load_records(Path(args.data_dir)), args)
    export_csv(records, Path(args.output))
    log.info("exported %d records to %s", len(records), args.output)


def cmd_pdf_meta(args: argparse.Namespace) -> None:
    records = filter_records(load_records(Path(args.data_dir)), args)
    enriched = enrich_pdf_metadata(records, Path(args.data_dir), args.workers, args.limit, token_from_args(args))
    ok = sum(1 for item in enriched if item.get("pdf_urls"))
    log.info("enriched %d records; %d records contain pdf URL candidates", len(enriched), ok)


def cmd_download_previews(args: argparse.Namespace) -> None:
    records = filter_records(load_records(Path(args.data_dir)), args)
    download_previews(records, Path(args.output_dir), args.workers, args.pages)
    log.info("downloaded previews for %d records into %s", len(records), args.output_dir)


def cmd_download_pdfs(args: argparse.Namespace) -> None:
    records = filter_records(load_records(Path(args.data_dir)), args)
    manifest = download_pdfs(
        records,
        Path(args.data_dir),
        Path(args.output_dir),
        args.workers,
        token_from_args(args),
        args.probe_only,
    )
    ok = sum(1 for item in manifest if item.get("downloaded"))
    action = "probed" if args.probe_only else "downloaded"
    log.info("%s %d/%d records; manifest: %s/manifest.json", action, ok, len(manifest), args.output_dir)


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", help="substring search over normalized JSON")
    parser.add_argument("--stage", help="小学/初中/高中")
    parser.add_argument("--subject", help="学科")
    parser.add_argument("--version", help="教材版本")
    parser.add_argument("--grade", help="年级")
    parser.add_argument("--volume", help="册次")
    parser.add_argument("--limit", type=int, help="maximum records to process")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartEdu textbook material crawler")
    parser.add_argument("--data-dir", default="data", help="metadata output directory")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="fetch all textbook metadata")
    sync.add_argument("--no-raw", action="store_true", help="do not keep raw part JSON files")
    sync.set_defaults(func=cmd_sync)

    list_cmd = sub.add_parser("list", help="list records")
    add_filter_args(list_cmd)
    list_cmd.set_defaults(func=cmd_list)

    export_cmd = sub.add_parser("export-csv", help="export records to CSV")
    add_filter_args(export_cmd)
    export_cmd.add_argument("-o", "--output", default="data/textbooks.csv")
    export_cmd.set_defaults(func=cmd_export_csv)

    pdf_cmd = sub.add_parser("pdf-meta", help="fetch per-book detail JSON and extract PDF candidates")
    add_filter_args(pdf_cmd)
    pdf_cmd.add_argument("--workers", type=int, default=4)
    pdf_cmd.add_argument("--access-token", help="SmartEdu access token; prefer SMARTEDU_ACCESS_TOKEN env")
    pdf_cmd.set_defaults(func=cmd_pdf_meta)

    previews = sub.add_parser("download-previews", help="download transcode preview images")
    add_filter_args(previews)
    previews.add_argument("-o", "--output-dir", default="downloads/previews")
    previews.add_argument("--workers", type=int, default=8)
    previews.add_argument("--pages", type=int, help="only download first N pages per book")
    previews.set_defaults(func=cmd_download_previews)

    pdf_dl = sub.add_parser("download-pdfs", help="download PDF source files from detail metadata")
    add_filter_args(pdf_dl)
    pdf_dl.add_argument("-o", "--output-dir", default="downloads/pdfs")
    pdf_dl.add_argument("--workers", type=int, default=2)
    pdf_dl.add_argument("--access-token", help="SmartEdu access token; prefer SMARTEDU_ACCESS_TOKEN env")
    pdf_dl.add_argument("--probe-only", action="store_true", help="only test first bytes instead of saving files")
    pdf_dl.set_defaults(func=cmd_download_pdfs)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        log.warning("interrupted")
        return 130
    except Exception as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
