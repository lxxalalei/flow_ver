#!/usr/bin/env python3
"""Execute Stage 2 platform tasks concurrently and write Stage 3."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
DEFAULT_REGISTRY = ROOT / "config" / "search-registry.json"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def load_adapter(entry: str):
    path = (ROOT / entry).resolve()
    if not path.is_file() or ROOT.resolve() not in path.parents:
        raise ValueError(f"无效 adapter: {entry}")
    spec = importlib.util.spec_from_file_location(f"lrs_adapter_{path.parent.name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter = getattr(module, "ADAPTER", None)
    if adapter is None or not callable(getattr(adapter, "search", None)):
        raise TypeError(f"adapter 必须导出 ADAPTER.search: {path}")
    return adapter


def check_runtime(config: dict[str, Any]) -> dict[str, Any] | None:
    runtime = config.get("runtime") or {}
    missing = [name for name in runtime.get("python_all", []) if importlib.util.find_spec(name) is None]
    if missing:
        return {
            "error_code": "SYSTEM_DEPENDENCY_MISSING",
            "message": f"缺少搜索依赖: {', '.join(missing)}",
            "retryable": False,
        }
    alternatives = runtime.get("python_any", [])
    if alternatives and not any(importlib.util.find_spec(name) is not None for name in alternatives):
        return {
            "error_code": "SYSTEM_DEPENDENCY_MISSING",
            "message": f"至少需要一个搜索依赖: {', '.join(alternatives)}",
            "retryable": False,
        }
    auth_env = runtime.get("auth_any_env", [])
    if auth_env and not any(os.environ.get(name) for name in auth_env):
        return {
            "error_code": "AUTH_REQUIRED",
            "message": f"需要运行时认证环境变量之一: {', '.join(auth_env)}",
            "retryable": False,
        }
    return None


async def execute_task(task: dict[str, Any], registry: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    platform = task.get("platform")
    config = registry.get(platform) if isinstance(platform, str) else None
    if not isinstance(config, dict) or config.get("status") != "available":
        return [], [{
            "platform": platform,
            "error_code": "SEARCH_PLATFORM_UNAVAILABLE",
            "message": "平台未注册或当前不可执行",
            "retryable": False,
        }]
    runtime_error = check_runtime(config)
    if runtime_error:
        return [], [{"platform": platform, **runtime_error}]
    try:
        adapter = load_adapter(config["entry"])
    except Exception as exc:
        return [], [{
            "platform": platform,
            "error_code": "SYSTEM_ADAPTER_LOAD_FAILED",
            "message": str(exc),
            "retryable": False,
        }]

    resources: list[dict] = []
    errors: list[dict] = []
    timeout = int(config.get("timeout_seconds", 60))
    # 同平台查询串行，平台之间由 gather 并行。
    for search in task.get("searches", []):
        query = search.get("query", "")
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    adapter.search,
                    query,
                    int(search.get("max_results", 20)),
                    dict(search.get("params") or {}),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            response = {"results": [], "error": {"error_code": "NETWORK_TIMEOUT", "message": "平台搜索超时", "retryable": True}}
        except Exception as exc:
            response = {"results": [], "error": {"error_code": "SEARCH_EXECUTION_FAILED", "message": str(exc), "retryable": False}}
        for item in response.get("results", []):
            if isinstance(item, dict):
                resources.append(item)
        error = response.get("error")
        if isinstance(error, dict):
            errors.append({"platform": platform, "query": query, **error})
    return resources, errors


def exact_dedup(resources: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    output = []
    for item in resources:
        key = (str(item.get("platform", "")), str(item.get("resource_id") or item.get("source_url") or ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


async def run(plan: dict[str, Any], registry_document: dict[str, Any]) -> dict[str, Any]:
    tasks = plan.get("data", {}).get("search_tasks", [])
    registry = registry_document.get("platforms", {})
    semaphore = asyncio.Semaphore(max(1, int(registry_document.get("max_concurrency", 4))))

    async def bounded(task: dict[str, Any]):
        async with semaphore:
            return await execute_task(task, registry)

    executions = await asyncio.gather(*(bounded(task) for task in tasks))
    resources = exact_dedup([item for result, _ in executions for item in result])
    errors = [error for _, task_errors in executions for error in task_errors]
    failed_platforms = []
    for task in tasks:
        platform = task.get("platform")
        platform_results = [item for item in resources if item.get("platform") == platform]
        platform_errors = [item for item in errors if item.get("platform") == platform]
        if not platform_results and platform_errors:
            failed_platforms.append(platform)
    return {
        "_meta": {
            "schema_version": "platform-results/v1",
            "session_id": plan.get("_meta", {}).get("session_id", ""),
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        },
        "_summary": {"resource_count": len(resources), "failed_platforms": failed_platforms},
        "data": {"resources": resources, "errors": errors},
    }


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="并行执行学习资源平台搜索计划")
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    document = asyncio.run(run(load_json(args.plan), load_json(args.registry)))
    atomic_write(args.output, document)
    print(json.dumps(document["_summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
