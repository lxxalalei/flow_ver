#!/usr/bin/env python3
"""Anna's Archive adapter for resource-platforms."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class AnnasArchiveSearchAdapter(CLISearchAdapter):
    platform_name = "annas-archive"
    search_script = SCRIPTS_DIR / "annas-archive" / "annas_search.py"
    timeout_seconds = 45

    def _build_search_cmd(self, query: str, max_results: int, params: dict[str, Any], output_file: Path) -> list[str] | None:
        if self.search_script is None or not self.search_script.exists():
            return None
        core = params.get("core") or "book"
        cmd = [
            sys.executable,
            str(self.search_script),
            "search",
            query,
            "--max",
            str(max_results),
            "--core",
            str(core),
            "-o",
            str(output_file),
        ]
        return cmd


ADAPTER = AnnasArchiveSearchAdapter()
