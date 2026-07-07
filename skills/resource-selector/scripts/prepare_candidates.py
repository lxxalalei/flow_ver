#!/usr/bin/env python3
"""Prepare Stage 3 resources for semantic review by resource-selector."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "spm", "from", "ref", "source"}


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in TRACKING_PARAMS))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))


def completeness(resource: dict[str, Any]) -> int:
    useful = (
        "title", "description", "author", "type", "duration", "publish_time",
        "is_free", "language", "thumbnail_url", "download_feasibility", "platform_signals",
    )
    return sum(resource.get(key) not in (None, "", [], {}) for key in useful)


def normalized_title(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def title_similarity(left: str, right: str) -> float:
    left = normalized_title(left)
    right = normalized_title(right)
    if min(len(left), len(right)) < 6:
        return 0.0
    if left == right:
        return 1.0
    left_pairs = {left[index:index + 2] for index in range(len(left) - 1)}
    right_pairs = {right[index:index + 2] for index in range(len(right) - 1)}
    return len(left_pairs & right_pairs) / max(1, len(left_pairs | right_pairs))


def exact_dedup(resources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    kept: list[dict[str, Any]] = []
    key_to_index: dict[tuple[str, str], int] = {}
    duplicates: list[dict[str, str]] = []
    for resource in resources:
        resource_id = str(resource.get("resource_id") or "")
        source_url = str(resource.get("source_url") or "")
        keys = [("resource_id", resource_id)]
        if source_url:
            keys.append(("source_url", normalize_url(source_url)))
        matched = next((key_to_index[key] for key in keys if key[1] and key in key_to_index), None)
        if matched is None:
            index = len(kept)
            kept.append(resource)
            for key in keys:
                if key[1]:
                    key_to_index[key] = index
            continue
        current = kept[matched]
        if completeness(resource) > completeness(current):
            kept[matched] = resource
            retained, removed = resource_id, str(current.get("resource_id") or "")
            for key in keys:
                if key[1]:
                    key_to_index[key] = matched
        else:
            retained, removed = str(current.get("resource_id") or ""), resource_id
        duplicates.append({"retained": retained, "removed": removed, "reason": "相同 resource_id 或规范化 URL"})
    return kept, duplicates


def possible_duplicate_pairs(resources: list[dict[str, Any]], threshold: float = 0.78) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(resources):
        for right in resources[index + 1:]:
            score = title_similarity(str(left.get("title") or ""), str(right.get("title") or ""))
            if score >= threshold:
                pairs.append({
                    "left": left.get("resource_id"),
                    "right": right.get("resource_id"),
                    "title_similarity": round(score, 3),
                })
    return sorted(pairs, key=lambda item: item["title_similarity"], reverse=True)


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(session_dir: Path) -> dict[str, Any]:
    intent = load_object(session_dir / "stage1_intent.json")
    stage3 = load_object(session_dir / "stage3_search_results.json")
    session_id = str(intent.get("_meta", {}).get("session_id") or "")
    if session_id != str(stage3.get("_meta", {}).get("session_id") or ""):
        raise ValueError("Stage 1 与 Stage 3 session_id 不一致")
    resources = stage3.get("data", {}).get("resources", [])
    if not isinstance(resources, list):
        raise ValueError("Stage 3 data.resources 必须是 array")
    valid = [resource for resource in resources if isinstance(resource, dict)]
    candidates, exact_duplicates = exact_dedup(valid)
    possible = possible_duplicate_pairs(candidates)
    return {
        "_meta": {
            "schema_version": "selector-input/v1",
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        },
        "_summary": {
            "raw_count": len(valid),
            "candidate_count": len(candidates),
            "exact_duplicate_count": len(exact_duplicates),
            "possible_duplicate_pair_count": len(possible),
            "platform_error_count": len(stage3.get("data", {}).get("errors", [])),
        },
        "data": {
            "candidates": candidates,
            "exact_duplicates": exact_duplicates,
            "possible_duplicates": possible,
            "platform_errors": stage3.get("data", {}).get("errors", []),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 Selector 候选")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.session_dir / "selector_input.json"
    document = prepare(args.session_dir)
    atomic_write(output, document)
    if output.resolve() == (args.session_dir / "selector_input.json").resolve():
        shutil.rmtree(args.session_dir / "selector_worker_reviews", ignore_errors=True)
    print(json.dumps(document["_summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
