#!/usr/bin/env python3
"""Agent-facing wrapper for SmartEdu textbook downloads.

This script keeps crawler metadata in a work directory and moves only PDF files
into the final library directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILLS_ROOT / "resource-platforms" / "scripts"))
sys.path.insert(0, str(SKILLS_ROOT / "resource-platforms" / "scripts" / "smartedu"))

from shared.logger import getLogger
log = getLogger("smartedu")

import smartedu_tch_material as crawler


def safe_segment(value: Any, fallback: str = "未分类", limit: int = 80) -> str:
    text = str(value or fallback)
    return crawler.safe_name(text, limit=limit)


def ensure_index(data_dir: Path, force_sync: bool) -> None:
    if force_sync or not (data_dir / "textbooks.json").exists():
        log.info("syncing SmartEdu index into %s", data_dir)
        crawler.sync_index(data_dir, include_raw=False)


def filter_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        query=args.query,
        stage=args.stage,
        subject=args.subject,
        version=args.version,
        grade=args.grade,
        volume=args.volume,
        limit=args.limit,
    )


def destination_for(record: dict[str, Any], source_file: Path, library_dir: Path) -> Path:
    parts = [
        safe_segment(record.get("stage")),
        safe_segment(record.get("grade")),
        safe_segment(record.get("subject")),
        safe_segment(record.get("version")),
        safe_segment(record.get("volume")),
    ]
    title = safe_segment(record.get("title") or record.get("id"), limit=120)
    short_id = str(record.get("id") or "")[:8]
    name = f"{title}_{short_id}{source_file.suffix or '.pdf'}"
    return library_dir.joinpath(*parts, name)


def organize_downloads(manifest: list[dict[str, Any]], library_dir: Path) -> list[dict[str, Any]]:
    organized: list[dict[str, Any]] = []
    for item in manifest:
        if not item.get("downloaded") or not item.get("file"):
            organized.append({**item, "library_file": None})
            continue

        source = Path(str(item["file"]))
        if not source.exists():
            organized.append({**item, "library_file": None, "error": "downloaded file missing"})
            continue

        dest = destination_for(item, source, library_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        shutil.move(str(source), str(dest))
        organized.append({**item, "library_file": str(dest)})
    return organized


def remove_non_pdf_files(library_dir: Path) -> None:
    if not library_dir.exists():
        return
    for path in library_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() != ".pdf":
            path.unlink()


def write_run_summary(work_dir: Path, summary: dict[str, Any]) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "last_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def emit_summary(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


def metadata_confidence(record: dict[str, Any]) -> float:
    fields = ["title", "stage", "grade", "subject", "version", "volume"]
    present = sum(1 for field in fields if record.get(field))
    return round(present / len(fields), 2)


def standard_candidate(record: dict[str, Any], local_file: str | None = None) -> dict[str, Any]:
    providers = record.get("providers") or []
    provider = "/".join(providers) if providers else ""
    candidate = {
        "source": "smartedu",
        "source_name": "国家中小学智慧教育平台",
        "source_url": record.get("detail_page"),
        "resource_id": record.get("id"),
        "title": record.get("title"),
        "resource_type": "教材",
        "format": record.get("format") or "pdf",
        "stage": record.get("stage"),
        "grade": record.get("grade"),
        "subject": record.get("subject"),
        "version": record.get("version"),
        "volume": record.get("volume"),
        "topic": None,
        "provider": provider,
        "official": True,
        "downloadable": True,
        "requires_auth": True,
        "size": record.get("size"),
        "metadata_confidence": metadata_confidence(record),
        "raw": {
            "internal_adapter": "tchMaterial",
            "id": record.get("id"),
            "thumbnail": record.get("thumbnail"),
            "preview_count": record.get("preview_count"),
            "providers": providers,
        },
    }
    if local_file:
        candidate["local_file"] = local_file
    return candidate


def candidate_from_download(item: dict[str, Any]) -> dict[str, Any]:
    local_file = item.get("library_file") if item.get("downloaded") else None
    return standard_candidate(item, local_file=local_file)


def run(args: argparse.Namespace) -> int:
    token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    if not token and not args.probe_only and not args.list_only:
        log.error("SMARTEDU_ACCESS_TOKEN or --access-token is required for PDF downloads")
        return 2

    work_dir = Path(args.work_dir)
    data_dir = work_dir / "data"
    tmp_download_dir = work_dir / "tmp-downloads"
    library_dir = Path(args.library_dir)

    ensure_index(data_dir, args.sync)
    records = crawler.filter_records(crawler.load_records(data_dir), filter_args(args))
    if not records:
        log.warning("no matching textbooks")
        write_run_summary(work_dir, {"matched": 0, "downloaded": 0, "library_dir": str(library_dir)})
        return 1

    if args.list_only:
        summary = {
            "matched": len(records),
            "downloaded": 0,
            "library_dir": str(library_dir),
            "filters": {
                "stage": args.stage,
                "grade": args.grade,
                "subject": args.subject,
                "version": args.version,
                "volume": args.volume,
                "query": args.query,
            },
            "candidate_schema": "learning-resource-candidate/v1",
            "candidates": [standard_candidate(record) for record in records[: args.show]],
        }
        write_run_summary(work_dir, summary)
        emit_summary(args, summary)
        return 0

    manifest = crawler.download_pdfs(
        records=records,
        data_dir=data_dir,
        out_dir=tmp_download_dir,
        workers=args.workers,
        access_token=token,
        probe_only=args.probe_only,
    )

    if args.probe_only:
        organized = manifest
    else:
        organized = organize_downloads(manifest, library_dir)
        remove_non_pdf_files(library_dir)

    downloaded = [item for item in organized if item.get("downloaded")]
    summary = {
        "matched": len(records),
        "downloaded": len(downloaded),
        "library_dir": str(library_dir),
        "filters": {
            "stage": args.stage,
            "grade": args.grade,
            "subject": args.subject,
            "version": args.version,
            "volume": args.volume,
            "query": args.query,
        },
        "files": [item.get("library_file") for item in organized if item.get("library_file")],
        "candidate_schema": "learning-resource-candidate/v1",
        "candidates": [candidate_from_download(item) for item in organized if item.get("downloaded")],
        "failures": [
            {"id": item.get("id"), "title": item.get("title"), "error": item.get("error")}
            for item in organized
            if not item.get("downloaded")
        ],
    }
    write_run_summary(work_dir, summary)
    emit_summary(args, summary)
    return 0 if downloaded else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download SmartEdu textbooks into a clean PDF library")
    parser.add_argument("--stage", help="学段，例如 小学")
    parser.add_argument("--grade", help="年级，例如 三年级")
    parser.add_argument("--subject", help="学科，例如 数学")
    parser.add_argument("--version", help="教材版本，例如 人教版")
    parser.add_argument("--volume", help="册次，例如 上册")
    parser.add_argument("--query", help="额外关键词检索")
    parser.add_argument("--limit", type=int, help="限制下载数量")
    parser.add_argument("--library-dir", default="教材资料库", help="只存放 PDF 的最终资料库目录")
    parser.add_argument("--work-dir", default=".smartedu-textbooks-work", help="缓存元数据和临时下载的工作目录")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--access-token", help="SmartEdu access token; prefer SMARTEDU_ACCESS_TOKEN")
    parser.add_argument("--sync", action="store_true", help="强制重新同步教材索引")
    parser.add_argument("--probe-only", action="store_true", help="只测试可访问性，不保存 PDF")
    parser.add_argument("--list-only", action="store_true", help="只列出匹配教材，不下载也不需要 token")
    parser.add_argument("--show", type=int, default=20, help="list-only 模式展示的最大候选数量")
    parser.add_argument("-o", "--output", help="将 JSON 摘要写入指定文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
