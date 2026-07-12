#!/usr/bin/env python3
"""Execute archive-plan/v1 with path confinement and per-resource transactions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from validate_output import validate as validate_output


AUDIENCES = {"child", "parent", "family", "unknown"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


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


def safe_component(value: str, fallback: str = "待确认", limit: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return (cleaned or fallback)[:limit]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_plan(plan: dict[str, Any], download: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(plan) != {"_meta", "data"}:
        errors.append("archive plan 根节点只能包含 _meta 和 data")
    meta = plan.get("_meta")
    data = plan.get("data")
    if not isinstance(meta, dict) or meta.get("schema_version") != "archive-plan/v1":
        errors.append("archive plan schema_version 必须为 archive-plan/v1")
        meta = {}
    elif set(meta) != {"schema_version", "session_id"}:
        errors.append("archive plan _meta 只能包含 schema_version 和 session_id")
    if meta.get("session_id") != download.get("_meta", {}).get("session_id"):
        errors.append("archive plan session_id 必须继承 Stage 5")
    if not isinstance(data, dict):
        return errors + ["archive plan data 必须是 object"]
    if set(data) != {"library_root", "items"}:
        errors.append("archive plan data 只能包含 library_root 和 items")
    library_root = data.get("library_root")
    if not isinstance(library_root, str) or not library_root.strip() or not Path(library_root).expanduser().is_absolute():
        errors.append("archive plan data.library_root 必须是绝对路径")
    items = data.get("items")
    if not isinstance(items, list):
        return errors + ["archive plan data.items 必须是 array"]
    expected_ids = [
        item.get("resource_id")
        for item in download.get("data", {}).get("results", [])
        if isinstance(item, dict)
    ]
    actual_ids: list[Any] = []
    full_fields = {
        "resource_id", "primary_domain", "secondary_domains", "audience", "age_or_grade",
        "topics", "resource_type", "formats", "target_name",
    }
    download_by_id = {
        item.get("resource_id"): item
        for item in download.get("data", {}).get("results", [])
        if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
    }
    for index, item in enumerate(items):
        prefix = f"data.items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是 object")
            continue
        download_result = download_by_id.get(item.get("resource_id"), {})
        required = {"resource_id"} if download_result.get("download_status") == "failed" else full_fields
        extra = set(item) - full_fields
        missing = required - set(item)
        if extra:
            errors.append(f"{prefix} 存在未定义字段: {sorted(extra)}")
        if missing:
            errors.append(f"{prefix} 缺少字段: {sorted(missing)}")
        resource_id = item.get("resource_id")
        actual_ids.append(resource_id)
        for field in required.intersection({"resource_id", "primary_domain", "age_or_grade", "resource_type", "target_name"}):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"{prefix}.{field} 必须是非空字符串")
        if "audience" in required and item.get("audience") not in AUDIENCES:
            errors.append(f"{prefix}.audience 非法")
        for field in required.intersection({"secondary_domains", "topics", "formats"}):
            value = item.get(field)
            allow_empty = field == "secondary_domains"
            if (
                not isinstance(value, list)
                or (not allow_empty and not value)
                or any(not isinstance(entry, str) or not entry.strip() for entry in value)
                or len(value) != len(set(value))
            ):
                errors.append(f"{prefix}.{field} 必须是唯一字符串数组")
        if "topics" in required and isinstance(item.get("topics"), list) and len(item["topics"]) > 3:
            errors.append(f"{prefix}.topics 最多包含 3 项")
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_ids):
        errors.append("archive plan 必须与 Stage 5 结果一一对应")
    return errors


def load_or_create_index(library_root: Path) -> dict[str, Any]:
    index_path = library_root / ".library" / "index.json"
    if not index_path.exists():
        return {"schema_version": "library-index/v1", "resources": []}
    index = load_object(index_path)
    if index.get("schema_version") != "library-index/v1" or not isinstance(index.get("resources"), list):
        raise ValueError("资料库索引必须符合 library-index/v1")
    return index


@contextmanager
def library_lock(library_root: Path) -> Iterator[None]:
    internal = library_root / ".library"
    internal.mkdir(parents=True, exist_ok=True)
    lock_path = internal / "archive.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            lock = load_object(lock_path)
            pid = int(lock.get("pid"))
            os.kill(pid, 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            lock_path.unlink(missing_ok=True)
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        else:
            raise ValueError(f"资料库正在被其他归档任务使用: {lock_path}")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created_at": now_iso()}, handle)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def recover_transactions(library_root: Path, index: dict[str, Any]) -> None:
    transaction_root = library_root / ".library" / "transactions"
    if not transaction_root.exists():
        return
    indexed_ids = {
        item.get("resource_id")
        for item in index.get("resources", [])
        if isinstance(item, dict)
    }
    for transaction in transaction_root.iterdir():
        if not transaction.is_dir():
            continue
        journal_path = transaction / "journal.json"
        try:
            journal = load_object(journal_path)
        except (OSError, ValueError, json.JSONDecodeError):
            shutil.rmtree(transaction, ignore_errors=True)
            continue
        if journal.get("resource_id") not in indexed_ids:
            for raw_path in journal.get("final_paths", []):
                if isinstance(raw_path, str):
                    path = Path(raw_path)
                    try:
                        resolved = path.resolve()
                        if library_root == resolved or library_root in resolved.parents:
                            path.unlink(missing_ok=True)
                    except OSError:
                        pass
        shutil.rmtree(transaction, ignore_errors=True)


def confined_download_files(session_dir: Path, result: dict[str, Any]) -> list[Path]:
    downloads_root = (session_dir / "downloads").resolve()
    files: list[Path] = []
    for raw_path in result.get("files", []):
        path = Path(raw_path)
        if not path.is_absolute():
            raise ValueError(f"下载文件必须是绝对路径: {raw_path}")
        resolved = path.resolve(strict=True)
        if downloads_root not in resolved.parents or not resolved.is_file() or path.is_symlink():
            raise ValueError(f"下载文件不在本次会话 downloads 中: {raw_path}")
        files.append(resolved)
    return files


def find_duplicate(index: dict[str, Any], resource: dict[str, Any], hashes: list[str]) -> dict[str, Any] | None:
    for existing in index.get("resources", []):
        if not isinstance(existing, dict):
            continue
        if existing.get("resource_id") == resource.get("resource_id"):
            return existing
        if resource.get("source_url") and existing.get("source_url") == resource.get("source_url"):
            return existing
        existing_hashes = set(existing.get("content_hashes") or [])
        if hashes and existing_hashes.intersection(hashes):
            return existing
    return None


def unique_destination(directory: Path, filename: str, resource_id: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    token = safe_component(resource_id.replace(":", "-"), "resource", 24)
    candidate = directory / f"{stem}-{token}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{token}-{counter}{suffix}"
        counter += 1
    return candidate


def remove_empty_download_parents(path: Path, downloads_root: Path) -> None:
    current = path.parent
    while current != downloads_root and downloads_root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def archive_one(
    session_dir: Path,
    library_root: Path,
    index: dict[str, Any],
    plan_item: dict[str, Any],
    download_result: dict[str, Any],
    resource: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    resource_id = plan_item["resource_id"]
    if download_result.get("download_status") == "failed":
        return {
            "resource_id": resource_id,
            "archive_status": "failed",
            "library_paths": [],
            "archive_error": download_result.get("error") or {"message": "下载失败，无法归档"},
        }
    source_files = confined_download_files(session_dir, download_result)
    if not source_files:
        return {
            "resource_id": resource_id,
            "archive_status": "failed",
            "library_paths": [],
            "archive_error": {"error_code": "ARCHIVE_SOURCE_MISSING", "message": "没有可归档文件", "retryable": False},
        }
    hashes = [file_hash(path) for path in source_files]
    duplicate = find_duplicate(index, resource, hashes)
    if duplicate:
        downloads_root = (session_dir / "downloads").resolve()
        for source in source_files:
            source.unlink(missing_ok=True)
            remove_empty_download_parents(source, downloads_root)
        return {
            "resource_id": resource_id,
            "archive_status": "skipped",
            "library_paths": duplicate.get("library_paths") or [],
            "duplicate_of": duplicate.get("resource_id"),
        }

    topic = plan_item["topics"][0]
    destination_dir = (
        library_root
        / safe_component(plan_item["primary_domain"])
        / safe_component(plan_item["age_or_grade"], "unknown")
        / safe_component(topic)
    )
    destination_dir.mkdir(parents=True, exist_ok=True)
    transaction = library_root / ".library" / "transactions" / uuid.uuid4().hex
    staging = transaction / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    final_paths: list[Path] = []
    staged_paths: list[Path] = []
    index_committed = False
    index_entry: dict[str, Any] | None = None
    downloads_root = (session_dir / "downloads").resolve()
    try:
        base_name = safe_component(plan_item["target_name"], safe_component(str(resource.get("title") or resource_id)), 100)
        for index_number, source in enumerate(source_files, 1):
            if len(source_files) == 1:
                filename = base_name if Path(base_name).suffix else f"{base_name}{source.suffix}"
            else:
                filename = f"{Path(base_name).stem}-{index_number}{source.suffix}"
            staged = staging / filename
            shutil.copy2(source, staged)
            staged_paths.append(staged)
            destination = unique_destination(destination_dir, filename, resource_id)
            final_paths.append(destination)
        journal = {
            "resource_id": resource_id,
            "state": "prepared",
            "final_paths": [str(path.resolve()) for path in final_paths],
        }
        atomic_write(transaction / "journal.json", journal)
        for staged, destination in zip(staged_paths, final_paths):
            os.replace(staged, destination)
        journal["state"] = "files_moved"
        atomic_write(transaction / "journal.json", journal)

        quality = next(
            (item.get("quality_score") for item in selection.get("data", {}).get("selected", []) if item.get("resource_id") == resource_id),
            None,
        )
        index_entry = {
            "resource_id": resource_id,
            "title": resource.get("title") or plan_item["target_name"],
            "platform": resource.get("platform"),
            "source_url": resource.get("source_url"),
            "primary_domain": plan_item["primary_domain"],
            "secondary_domains": plan_item["secondary_domains"],
            "audience": plan_item["audience"],
            "age_or_grade": plan_item["age_or_grade"],
            "topics": plan_item["topics"],
            "resource_type": plan_item["resource_type"],
            "formats": plan_item["formats"],
            "quality_score": quality,
            "download_status": download_result.get("download_status"),
            "library_paths": [str(path.resolve()) for path in final_paths],
            "content_hashes": hashes,
            "archive_time": now_iso(),
        }
        index["resources"].append(index_entry)
        try:
            atomic_write(library_root / ".library" / "index.json", index)
        except Exception:
            index["resources"].remove(index_entry)
            raise
        index_committed = True
        try:
            journal["state"] = "committed"
            atomic_write(transaction / "journal.json", journal)
            for source in source_files:
                source.unlink(missing_ok=True)
                remove_empty_download_parents(source, downloads_root)
        except OSError:
            pass
        finally:
            shutil.rmtree(transaction, ignore_errors=True)
        return {"resource_id": resource_id, "archive_status": "archived", "library_paths": index_entry["library_paths"]}
    except Exception:
        if not index_committed:
            if index_entry in index.get("resources", []):
                index["resources"].remove(index_entry)
            for path in final_paths:
                path.unlink(missing_ok=True)
        shutil.rmtree(transaction, ignore_errors=True)
        raise


def run(session_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    stage3 = load_object(session_dir / "stage3_search_results.json")
    selection = load_object(session_dir / "stage4_selection.json")
    download = load_object(session_dir / "stage5_download.json")
    plan_errors = validate_plan(plan, download)
    if plan_errors:
        raise ValueError("; ".join(plan_errors))
    library_root = Path(plan["data"]["library_root"]).expanduser().resolve()
    if library_root == session_dir or session_dir in library_root.parents:
        raise ValueError("资料库根目录不得位于本次会话目录内")
    library_root.mkdir(parents=True, exist_ok=True)
    resources = {
        item["resource_id"]: item
        for item in stage3.get("data", {}).get("resources", [])
        if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
    }
    download_results = {
        item["resource_id"]: item
        for item in download.get("data", {}).get("results", [])
        if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
    }
    results: list[dict[str, Any]] = []
    with library_lock(library_root):
        index = load_or_create_index(library_root)
        index_path = library_root / ".library" / "index.json"
        if not index_path.exists():
            atomic_write(index_path, index)
        recover_transactions(library_root, index)
        for item in plan["data"]["items"]:
            resource_id = item["resource_id"]
            try:
                result = archive_one(
                    session_dir,
                    library_root,
                    index,
                    item,
                    download_results[resource_id],
                    resources.get(resource_id, {"resource_id": resource_id}),
                    selection,
                )
            except Exception as exc:
                result = {
                    "resource_id": resource_id,
                    "archive_status": "failed",
                    "library_paths": [],
                    "archive_error": {
                        "error_code": "ARCHIVE_TRANSACTION_FAILED",
                        "message": str(exc),
                        "retryable": False,
                    },
                }
            results.append(result)
    counts = {status: sum(item["archive_status"] == status for item in results) for status in ("archived", "skipped", "failed")}
    return {
        "_meta": {
            "schema_version": "archive/v1",
            "session_id": download.get("_meta", {}).get("session_id"),
            "created_at": now_iso(),
            "library_root": str(library_root),
        },
        "_summary": {
            "archived_count": counts["archived"],
            "skipped_count": counts["skipped"],
            "failed_count": counts["failed"],
        },
        "data": {"results": results},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="执行归档计划并事务化写入 Stage 6")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        session_dir = args.session_dir.resolve()
        plan_path = args.plan or session_dir / "archive_plan.json"
        output_path = args.output or session_dir / "stage6_archive.json"
        download = load_object(session_dir / "stage5_download.json")
        document = run(session_dir, load_object(plan_path))
        errors = validate_output(download, document)
        if errors:
            raise ValueError("; ".join(errors))
        atomic_write(output_path, document)
        print(json.dumps(document["_summary"], ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
