"""Stable domain errors returned by MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retriable": self.retryable,
            "context": [
                {"key": str(key)[:64], "value": str(value)[:512]}
                for key, value in sorted(self.details.items())
            ],
        }


def ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"contract_version": "1.0.0", "ok": True, **data}


def failure(error: DomainError, **identifiers: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": "1.0.0",
        "ok": False,
        "error": error.to_dict(),
    }
    result.update({key: value for key, value in identifiers.items() if value})
    return result
