#!/usr/bin/env python3
"""China National Library search adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class NLCSearchAdapter(CLISearchAdapter):
    platform_name = "nlc"
    search_script = SCRIPTS_DIR / "nlc" / "nlc_search.py"
    timeout_seconds = 45

    def _build_search_cmd(
        self, query: str, max_results: int, params: dict[str, Any], output_file: Path
    ) -> list[str] | None:
        if self.search_script is None or not self.search_script.is_file():
            return None
        return [
            sys.executable,
            str(self.search_script),
            "search",
            query,
            "--scope",
            str(params.get("scope") or "catalog"),
            "--max",
            str(max_results),
            "-o",
            str(output_file),
        ]


ADAPTER = NLCSearchAdapter()
