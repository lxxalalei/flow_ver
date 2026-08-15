#!/usr/bin/env python3
"""Direct capability test: the MCP's own search code and download code.

No MCP subprocess and no business chain (flow/presentation/selection/job).
It imports the same production classes the server uses:

  Search : education_resource_mcp.search.GenericWebSearchProvider
           (real engines: duckduckgo / baidu / bing, bounded by policy)
  Download: education_resource_mcp.acquisition.AcquisitionRouter with the
           exact generic registrations ResourceService builds:
             - generic-direct          (PublicHttpDownloader, direct_file)
             - generic-web-materializer (WebMaterializer, web_materialize)

Usage:
  python scripts/live_search_download_demo.py [--query "恐龙科普 图文"]
      [--limit 10] [--download-count 2] [--run-dir DIR] [--strategy all|direct|materialize]
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
import sys
import threading
import time

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_RUN_ROOT = REPO_ROOT / ".openclaw-test"

sys.path.insert(0, str(SERVICE_ROOT / "src"))

from education_resource_mcp.acquisition import (  # noqa: E402
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.acquisition.web_materializer import WebMaterializer  # noqa: E402
from education_resource_mcp.config import Settings  # noqa: E402
from education_resource_mcp.downloader import PublicHttpDownloader  # noqa: E402
from education_resource_mcp.search import GenericWebSearchProvider  # noqa: E402


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def _build_router(settings: Settings) -> AcquisitionRouter:
    # Mirrors ResourceService.__init__ generic registrations exactly.
    registrations = [
        ProviderRegistration(
            provider_id="generic-direct",
            provider_version="1.0.0",
            provider=PublicHttpDownloader(settings),
            strategies=(AcquisitionStrategy.DIRECT_FILE,),
            scopes=("primary_resource",),
        ),
        ProviderRegistration(
            provider_id="generic-web-materializer",
            provider_version="1.0.0",
            provider=WebMaterializer(settings=settings),
            strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
            scopes=("primary_resource", "landing_page"),
        ),
    ]
    return AcquisitionRouter(registrations)


def _run_search(settings: Settings, query: str, limit: int) -> tuple[list[dict], list[dict]]:
    print(f"\n===== SEARCH (MCP code: GenericWebSearchProvider) =====")
    print(f"query={query!r} limit={limit}")
    provider = GenericWebSearchProvider(settings)
    started = time.monotonic()
    resources, platform_runs = provider.search(
        [{"platform": "generic", "queries": [{"query": query}]}], limit
    )
    elapsed = time.monotonic() - started
    print(f"elapsed={elapsed:.1f}s resources={len(resources)}")
    for run in platform_runs:
        for qr in run.get("query_runs", []):
            print(f"run platform={run.get('platform')} status={run.get('status')} "
                  f"query={qr.get('query')!r} candidates={qr.get('candidate_count')} failures={qr.get('failure_count')}")
            for fail in qr.get("failures", []) or []:
                print(f"  engine_error={json.dumps(fail, ensure_ascii=False)[:300]}")
    for idx, item in enumerate(resources, start=1):
        print(f"[{idx}] {item.get('title')!r} type={item.get('type')} url={item.get('source_url')}")
    return resources, platform_runs


def _run_download(settings: Settings, resources: list[dict], count: int, strategy_filter: str) -> list[dict]:
    print(f"\n===== DOWNLOAD (MCP code: AcquisitionRouter + generic providers) =====")
    router = _build_router(settings)
    attempts: list[dict] = []
    jobs_root = settings.jobs_dir.resolve()
    for idx, item in enumerate(resources[:count], start=1):
        url = item.get("source_url")
        if not url:
            print(f"[{idx}] skipped: no source_url")
            continue
        resource = {
            "resource_id": _new_id("res"),
            "title": str(item.get("title") or url),
            "source_url": url,
            "resource_type": str(item.get("type") or "article"),
            "platform": str(item.get("platform") or "generic"),
        }
        print(f"\n--- target [{idx}] {resource['title']!r} url={url}")
        strategies = (
            [("direct_file", "generic-direct", "primary_resource", "original"),
             ("web_materialize", "generic-web-materializer", "landing_page", "html")]
            if strategy_filter == "all"
            else [("direct_file", "generic-direct", "primary_resource", "original")]
            if strategy_filter == "direct"
            else [("web_materialize", "generic-web-materializer", "landing_page", "html")]
        )
        for strategy, provider_id, scope, container in strategies:
            job_id = _new_id("job")
            request = AcquisitionRequest(
                job_id=job_id,
                resource=resource,
                strategy=strategy,
                provider_id=provider_id,
                provider_version="1.0.0",
                planned_scope=scope,
                representation_id=_new_id("repr"),
                preferred_container=container,
                cancel_event=threading.Event(),
                jobs_root=jobs_root,
            )
            started = time.monotonic()
            try:
                result: AcquisitionResult = router.acquire(request)
            except Exception as exc:  # structured failure expected from providers
                print(f"  [{strategy}] EXCEPTION {type(exc).__name__}: {exc}")
                attempts.append({"strategy": strategy, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                continue
            elapsed = time.monotonic() - started
            if not result.ok or result.bundle is None:
                failure = result.failure
                code = failure.code if failure is not None else "DOWNLOAD_FAILED"
                message = failure.message if failure is not None else "no bundle produced"
                print(f"  [{strategy}] FAILED code={code} message={message!r} elapsed={elapsed:.1f}s")
                attempts.append({"strategy": strategy, "ok": False, "code": code, "message": message})
                continue
            artifacts = result.bundle.artifacts
            print(f"  [{strategy}] OK provider={result.provider_id} scope={result.actual_scope} "
                  f"artifacts={len(artifacts)} elapsed={elapsed:.1f}s")
            all_exist = True
            for artifact in artifacts:
                exists = artifact.path.is_file()
                all_exist = all_exist and exists
                print(f"    artifact role={artifact.role} name={artifact.filename} "
                      f"size={artifact.byte_size} media={artifact.media_type} sha256={artifact.sha256[:16]} "
                      f"exists={exists} path={artifact.path}")
            attempts.append({"strategy": strategy, "ok": True, "artifacts": len(artifacts), "all_exist": all_exist})
    return attempts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="恐龙科普 图文")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--download-count", type=int, default=2)
    parser.add_argument("--strategy", choices=["all", "direct", "materialize"], default="all")
    parser.add_argument("--run-dir", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else DEFAULT_RUN_ROOT / f"direct-{time.strftime('%Y%m%d-%H%M%S')}"
    data_dir = run_dir / "data"
    jobs_dir = run_dir / "jobs"
    library_dir = run_dir / "library"
    for directory in (data_dir, jobs_dir, library_dir):
        directory.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=jobs_dir,
        library_dir=library_dir,
        search_timeout_seconds=20,
        download_timeout_seconds=30,
        max_workers=4,
    )
    print(f"[run-dir] {run_dir}")

    resources, _runs = _run_search(settings, args.query, args.limit)
    if not resources:
        print("\nSEARCH: no candidates returned (capability not demonstrated)")
        return 2

    attempts = _run_download(settings, resources, args.download_count, args.strategy)
    succeeded = [a for a in attempts if a.get("ok")]
    print(f"\n===== SUMMARY =====")
    print(f"search_candidates={len(resources)} download_attempts={len(attempts)} download_ok={len(succeeded)}")
    for attempt in attempts:
        print(json.dumps(attempt, ensure_ascii=False))
    if not succeeded:
        print("RESULT: search OK, download FAILED for all targets")
        return 2
    print("RESULT: search OK and download OK (files written under run-dir)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
