#!/usr/bin/env python3
"""Generic public-web search adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class GenericSearchAdapter(CLISearchAdapter):
    platform_name = "generic"
    search_script = SCRIPTS_DIR / "generic" / "generic_search.py"

    def _build_search_cmd(self, query: str, max_results: int, params: dict[str, Any], output_file: Path) -> list[str] | None:
        if self.search_script is None or not self.search_script.exists():
            return None
        engines = params.get("engines") or ["duckduckgo", "bing"]
        if not isinstance(engines, list):
            engines = ["duckduckgo", "bing"]
        return [
            sys.executable,
            str(self.search_script),
            "search",
            query,
            "--max",
            str(max_results),
            "--engines",
            ",".join(engines),
            "-o",
            str(output_file),
        ]


ADAPTER = GenericSearchAdapter()
