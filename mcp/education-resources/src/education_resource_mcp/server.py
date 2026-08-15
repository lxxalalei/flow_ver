"""MCP 2.0 stdio adapter for the education resource domain service."""

from __future__ import annotations

from typing import Any, Callable, Literal

from mcp.server.mcpserver import MCPServer

from .errors import DomainError, failure, ok
from .models import (
    ArchiveMetadata,
    DownloadOptions,
    FlowTask,
    LibraryFilters,
    SearchFilters,
    SearchTask,
)
from .service import ResourceService


CONTRACT_VERSION = "1.0.0"
PUBLIC_RECOVERY_CANDIDATE_LIMIT = 20
PUBLIC_SEARCH_SUMMARY_LIMIT = 600


def _invoke(
    function: Callable[[], dict[str, Any]], **identifiers: str | None
) -> dict[str, Any]:
    try:
        return ok(function())
    except DomainError as exc:
        return failure(exc, **identifiers)


def _compact_candidate(
    value: dict[str, Any], *, summary_limit: int = PUBLIC_SEARCH_SUMMARY_LIMIT
) -> dict[str, Any]:
    """Project one durable candidate into a compact Agent-facing summary."""

    result = {
        key: value[key]
        for key in (
            "resource_id",
            "platform",
            "title",
            "resource_type",
            "canonical_url",
            "availability",
        )
        if value.get(key) is not None
    }
    summary = str(value.get("summary") or "")
    if summary and summary_limit > 0:
        result["summary"] = summary[:summary_limit]
        result["summary_complete"] = len(summary) <= summary_limit
    elif summary:
        # Creator enumeration remains complete, but verbose per-item summaries
        # are deliberately omitted from the public list. Inspect one item when
        # its content details would change a decision.
        result["summary_complete"] = False
    else:
        result["summary_complete"] = True
    for key in ("author", "language", "duration_seconds", "published_at", "rights_hint"):
        if value.get(key) is not None:
            result[key] = value[key]
    return result


def _compact_search_result(
    value: dict[str, Any], *, summary_limit: int = PUBLIC_SEARCH_SUMMARY_LIMIT
) -> dict[str, Any]:
    """Expose all returned candidates without the heavy ResultSet internals."""

    candidates = [item for item in value.get("candidates") or [] if isinstance(item, dict)]
    result: dict[str, Any] = {
        "flow_id": value["flow_id"],
        "stage": value.get("stage") or "reviewing",
        "status": value.get("status") or "ready",
        "candidate_count": len(candidates),
        "candidates": [
            _compact_candidate(item, summary_limit=summary_limit) for item in candidates
        ],
        "failures": list(value.get("failures") or []),
    }
    if value.get("round") is not None:
        result["round"] = int(value["round"])
    return result


def _compact_inspect_result(value: dict[str, Any]) -> dict[str, Any]:
    """Keep decision-relevant inspect facts and hide internal evidence machinery."""

    resolved = value.get("resolved_resource")
    if not isinstance(resolved, dict):
        resolved = {}
    resource: dict[str, Any] = {
        "resource_type": str(resolved.get("resource_type") or "other"),
        "availability": resolved.get("availability") or {"status": "unknown"},
        "representations": [],
    }
    for field in ("title", "summary", "creator", "language"):
        if resolved.get(field) not in (None, ""):
            resource[field] = resolved[field]

    metadata = resolved.get("metadata")
    if isinstance(metadata, dict):
        creator_id = metadata.get("creator_sec_uid") or metadata.get("creator_id")
        if creator_id not in (None, ""):
            resource["creator_id"] = str(creator_id)

    for raw in resolved.get("representations") or []:
        if not isinstance(raw, dict):
            continue
        representation = {
            key: raw[key]
            for key in (
                "representation_id",
                "scope",
                "kind",
                "container",
                "mime_type",
                "role",
                "language",
                "estimated_size_bytes",
                "materializable",
                "requires_auth",
                "technical_availability",
            )
            if raw.get(key) is not None
        }
        resource["representations"].append(representation)

    inspection = value.get("inspection")
    if not isinstance(inspection, dict):
        inspection = {}
    result: dict[str, Any] = {
        "flow_id": value["flow_id"],
        "resource_id": value["resource_id"],
        "resolution_status": value.get("resolution_status") or "unresolved",
        "resource": resource,
        "failures": list(value.get("failures") or []),
        "warnings": list(inspection.get("warnings") or []),
    }
    if inspection.get("inspected_at"):
        result["inspected_at"] = inspection["inspected_at"]
    return result


def _compact_presentation_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_id": value["flow_id"],
        "stage": value.get("stage") or "presented",
        "items": list(value.get("items") or []),
        "empty": bool(value.get("empty", False)),
    }


def _compact_selection_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_id": value["flow_id"],
        "stage": value.get("stage") or ("cancelled" if value.get("cancelled") else "selected"),
        "selected_positions": list(value.get("selected_positions") or []),
        "selected_resource_ids": list(value.get("selected_resource_ids") or []),
        "cancelled": bool(value.get("cancelled", False)),
    }


def _compact_prepare_result(value: dict[str, Any]) -> dict[str, Any]:
    items = []
    for raw in value.get("items") or []:
        if not isinstance(raw, dict):
            continue
        item = {
            key: raw[key]
            for key in (
                "resource_id",
                "selected_position",
                "platform",
                "planned_scope",
                "planned_container",
                "estimated_size_bytes",
                "risks",
            )
            if key in raw
        }
        items.append(item)
    return {
        "flow_id": value["flow_id"],
        "stage": value.get("stage") or "prepared",
        "plan_id": value["plan_id"],
        "expires_at": value["expires_at"],
        "confirmation_required": bool(value.get("confirmation_required", True)),
        "confirmation_token": value["confirmation_token"],
        "items": items,
    }


def _compact_start_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_id": value["flow_id"],
        "job_id": value["job_id"],
        "status": value.get("status") or "queued",
        "queued_at": value["queued_at"],
    }


def _compact_flow_status(value: dict[str, Any]) -> dict[str, Any]:
    """Return a recovery summary rather than replaying the complete Flow state."""

    current_result_set = value.get("current_result_set")
    current_presentation = value.get("current_presentation")
    current_selection = value.get("current_selection")
    current_plan = value.get("current_plan")
    current_job = value.get("current_job")

    title_by_id: dict[str, str] = {}
    candidate_refs: list[dict[str, Any]] = []
    result_set_summary = None
    if isinstance(current_result_set, dict):
        candidates = [
            item for item in current_result_set.get("candidates") or [] if isinstance(item, dict)
        ]
        title_by_id = {
            str(item.get("resource_id")): str(item.get("title") or "")
            for item in candidates
            if item.get("resource_id")
        }
        for item in candidates[:PUBLIC_RECOVERY_CANDIDATE_LIMIT]:
            ref = {
                key: item[key]
                for key in ("resource_id", "platform", "title", "resource_type")
                if item.get(key) is not None
            }
            candidate_refs.append(ref)
        result_set_summary = {
            "status": current_result_set.get("status") or "ready",
            "round": int(current_result_set.get("round") or 1),
            "candidate_count": len(candidates),
            "candidate_refs": candidate_refs,
            "candidate_refs_complete": len(candidates) <= len(candidate_refs),
        }

    presentation_summary = None
    if isinstance(current_presentation, dict):
        items = []
        for raw in current_presentation.get("items") or []:
            if not isinstance(raw, dict):
                continue
            resource_id = str(raw.get("resource_id") or "")
            item = {
                "display_position": int(raw.get("display_position") or 0),
                "resource_id": resource_id,
            }
            if title_by_id.get(resource_id):
                item["title"] = title_by_id[resource_id]
            items.append(item)
        presentation_summary = {
            "items": items,
            "empty": bool(current_presentation.get("empty", not items)),
        }

    selection_summary = None
    if isinstance(current_selection, dict):
        selection_summary = {
            "stage": current_selection.get("stage") or "selected",
            "selected_positions": list(current_selection.get("selected_positions") or []),
            "selected_resource_ids": list(
                current_selection.get("selected_resource_ids") or []
            ),
        }

    plan_summary = None
    if isinstance(current_plan, dict):
        plan_summary = {
            "plan_id": current_plan.get("plan_id"),
            "status": current_plan.get("status"),
            "expires_at": current_plan.get("expires_at"),
            "confirmation_required": bool(
                current_plan.get("confirmation_required", False)
            ),
        }

    job_summary = None
    if isinstance(current_job, dict):
        job_summary = {
            "job_id": current_job.get("job_id"),
            "status": current_job.get("status"),
            "progress_percent": int(current_job.get("progress_percent") or 0),
            "asset_ids": list(current_job.get("asset_ids") or []),
            "failures": list(current_job.get("failures") or []),
        }
        if current_job.get("completion"):
            job_summary["completion"] = current_job["completion"]

    inspected_resource_ids = []
    for resolution in value.get("current_resolutions") or []:
        if isinstance(resolution, dict) and resolution.get("resource_id"):
            inspected_resource_ids.append(str(resolution["resource_id"]))

    return {
        "flow_id": value["flow_id"],
        "stage": value["stage"],
        "task": value["task"],
        "current_result_set": result_set_summary,
        "current_presentation": presentation_summary,
        "current_selection": selection_summary,
        "current_plan": plan_summary,
        "current_job": job_summary,
        "inspected_resource_ids": inspected_resource_ids,
        "allowed_next_actions": list(value.get("allowed_next_actions") or []),
    }


def _compact_job_status(value: dict[str, Any]) -> dict[str, Any]:
    """Expose job progress, ready assets and failures without binding internals."""

    assets = []
    for raw in value.get("assets") or []:
        if not isinstance(raw, dict):
            continue
        asset = {
            key: raw[key]
            for key in (
                "asset_id",
                "resource_id",
                "media_type",
                "size_bytes",
                "bundle_id",
                "role",
                "order",
                "bundle_completion",
            )
            if raw.get(key) is not None
        }
        assets.append(asset)
    result: dict[str, Any] = {
        "flow_id": value["flow_id"],
        "job_id": value["job_id"],
        "status": value["status"],
        "progress": value.get("progress")
        or {"completed_items": 0, "total_items": 0, "percent": 0},
        "assets": assets,
        "failures": list(value.get("failures") or []),
    }
    if value.get("completion"):
        result["completion"] = value["completion"]
    if value.get("updated_at"):
        result["updated_at"] = value["updated_at"]
    return result


def _current_result_set_id(resource_service: ResourceService, flow_id: str) -> str:
    status = resource_service.flow_status(flow_id)
    result_set = status.get("current_result_set")
    if not isinstance(result_set, dict) or not result_set.get("result_set_id"):
        raise DomainError("RESULT_SET_NOT_FOUND", "当前 Flow 没有可用的搜索结果")
    return str(result_set["result_set_id"])


def _save_current_selection(
    resource_service: ResourceService,
    flow_id: str,
    idempotency_key: str,
    selected_positions: list[int],
) -> dict[str, Any]:
    status = resource_service.flow_status(flow_id)
    presentation = status.get("current_presentation")
    if not isinstance(presentation, dict):
        raise DomainError("PRESENTATION_NOT_FOUND", "当前 Flow 没有可选择的展示记录")
    return resource_service.selection_save(
        flow_id,
        idempotency_key,
        str(presentation["presentation_id"]),
        int(presentation["presented_version"]),
        selected_positions,
    )


def _prepare_current_selection(
    resource_service: ResourceService,
    flow_id: str,
    idempotency_key: str,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    status = resource_service.flow_status(flow_id)
    selection = status.get("current_selection")
    if not isinstance(selection, dict) or selection.get("stage") != "selected":
        raise DomainError("RESOURCE_NOT_SELECTED", "下载前必须存在非空的明确选择")
    return resource_service.download_prepare(
        flow_id,
        idempotency_key,
        int(selection["selection_version"]),
        presentation_id=str(selection["presentation_id"]),
        presented_version=int(selection["presented_version"]),
        selection_digest=str(selection["selection_digest"]),
        options=options,
    )


def create_server(service: ResourceService | None = None) -> MCPServer:
    resource_service = service or ResourceService()
    server = MCPServer(
        name="education-resources",
        title="Education Resources",
        description="Search, present, select, confirm, download, inspect, and archive education resources",
        version="0.2.0",
        instructions=(
            "Use contract 1.0.0. The server owns durable ResultSet, Presentation, Selection, "
            "Resolution, Plan and Job bindings. The Agent should carry only flow/resource/plan/"
            "job/asset handles exposed by the current tool call. Save exactly the resources shown, "
            "save the user's display positions, then prepare. Downloads still require explicit "
            "user confirmation before start. Use resource_flow_status only as a compact recovery "
            "summary. Never invent IDs, positions, paths, commands, Providers, or download URLs."
        ),
    )

    @server.tool(structured_output=True)
    def resource_flow_start(
        contract_version: Literal["1.0.0"],
        idempotency_key: str,
        task: FlowTask,
    ) -> dict[str, Any]:
        """Start a durable education-resource FlowTask."""
        return _invoke(
            lambda: resource_service.flow_start(idempotency_key, task.model_dump())
        )

    @server.tool(structured_output=True)
    def resource_search(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        search_tasks: list[SearchTask],
        mode: Literal["replace", "extend"] = "replace",
        filters: SearchFilters | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Search and return compact candidates without ResultSet internals.

        For ``extend`` the server binds the search to the current ResultSet;
        the Agent never needs to carry ``task_version`` or ``result_set_id``.
        The default adapter budget is intentionally small; raise ``limit`` only
        when broader enumeration is part of the user's goal.
        """

        def execute() -> dict[str, Any]:
            base_result_set_id = (
                _current_result_set_id(resource_service, flow_id)
                if mode == "extend"
                else None
            )
            value = resource_service.search(
                flow_id,
                idempotency_key,
                [t.model_dump() for t in search_tasks],
                mode=mode,
                base_result_set_id=base_result_set_id,
                filters=filters.model_dump(exclude_none=True) if filters else None,
                limit=limit,
            )
            return _compact_search_result(value)

        return _invoke(execute, flow_id=flow_id)

    @server.tool(structured_output=True)
    def resource_browse_creator(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        platform: str,
        creator_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Browse a creator's content list without verbose per-item summaries.

        ``creator_id`` is the platform-native creator handle, not a display
        name. When an inspect result exposes ``resource.creator_id``, use it
        directly; never infer a creator handle from a nickname.
        """
        return _invoke(
            lambda: _compact_search_result(
                resource_service.browse_creator(
                    flow_id,
                    idempotency_key,
                    platform,
                    creator_id,
                    limit=limit,
                ),
                summary_limit=0,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_inspect(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        resource_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Inspect one resource and return only decision-relevant facts."""
        return _invoke(
            lambda: _compact_inspect_result(
                resource_service.inspect(
                    flow_id,
                    idempotency_key,
                    resource_id,
                )
            ),
            flow_id=flow_id,
            resource_id=resource_id,
        )

    @server.tool(structured_output=True)
    def resource_presentation_save(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        displayed_resource_ids: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Persist the exact current-search resources and order shown to the user.

        The current ResultSet is resolved server-side; the Agent does not carry
        ``result_set_id`` between Search and Presentation.
        """
        return _invoke(
            lambda: _compact_presentation_result(
                resource_service.presentation_save(
                    flow_id,
                    _current_result_set_id(resource_service, flow_id),
                    displayed_resource_ids,
                    idempotency_key,
                )
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_selection_save(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        selected_positions: list[int],
    ) -> dict[str, Any]:
        """Save explicit choices from the current Presentation by display position.

        Presentation identity/version are resolved from durable Flow state and
        are not echoed back as Agent state.
        """
        return _invoke(
            lambda: _compact_selection_result(
                _save_current_selection(
                    resource_service,
                    flow_id,
                    idempotency_key,
                    selected_positions,
                )
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_flow_status(
        contract_version: Literal["1.0.0"],
        flow_id: str,
    ) -> dict[str, Any]:
        """Recover a compact summary of current Flow state and next actions."""
        return _invoke(
            lambda: _compact_flow_status(resource_service.flow_status(flow_id)),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_flow_list(
        contract_version: Literal["1.0.0"],
        limit: int = 20,
    ) -> dict[str, Any]:
        """List recent flows to discover or recover a flow after context loss."""
        return _invoke(lambda: resource_service.flow_list(limit=limit))

    @server.tool(structured_output=True)
    def resource_download_prepare(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        options: DownloadOptions | None = None,
    ) -> dict[str, Any]:
        """Prepare the current Selection without making the Agent carry bindings."""
        return _invoke(
            lambda: _compact_prepare_result(
                _prepare_current_selection(
                    resource_service,
                    flow_id,
                    idempotency_key,
                    options.model_dump(exclude_none=True) if options else None,
                )
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_download_start(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        plan_id: str,
        confirmation_token: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Start an asynchronous Job after explicit user confirmation.

        All presentation/selection binding values are read from the stored Plan;
        only the new Job handle is returned to the Agent.
        """
        return _invoke(
            lambda: _compact_start_result(
                resource_service.download_start(
                    flow_id,
                    plan_id,
                    confirmation_token,
                    idempotency_key,
                )
            ),
            flow_id=flow_id,
            plan_id=plan_id,
        )

    @server.tool(structured_output=True)
    def resource_job_status(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        """Return compact durable progress, ready assets and failures for a Job."""
        return _invoke(
            lambda: _compact_job_status(resource_service.job_status(flow_id, job_id)),
            flow_id=flow_id,
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_job_cancel(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        job_id: str,
        idempotency_key: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Request cancellation; cancelled assets are quarantined."""
        return _invoke(
            lambda: resource_service.job_cancel(
                flow_id, job_id, idempotency_key, reason
            ),
            flow_id=flow_id,
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_archive(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        job_id: str,
        asset_id: str,
        idempotency_key: str,
        metadata: ArchiveMetadata | None = None,
    ) -> dict[str, Any]:
        """Archive a ready Asset by asset_id; local paths are never accepted."""
        return _invoke(
            lambda: resource_service.archive(
                flow_id,
                job_id,
                asset_id,
                idempotency_key=idempotency_key,
                metadata=metadata.model_dump(exclude_none=True) if metadata else None,
            ),
            flow_id=flow_id,
            job_id=job_id,
            asset_id=asset_id,
        )

    @server.tool(structured_output=True)
    def resource_library_search(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        filters: LibraryFilters | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search archived Assets by bounded metadata filters."""
        return _invoke(
            lambda: resource_service.library_search(
                flow_id,
                filters=filters.model_dump(exclude_none=True) if filters else None,
                cursor=cursor,
                limit=limit,
            ),
            flow_id=flow_id,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
