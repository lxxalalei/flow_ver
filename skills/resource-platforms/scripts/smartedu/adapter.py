#!/usr/bin/env python3
"""SmartEdu search-only adapter using the search-resources command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class SmartEduSearchAdapter(CLISearchAdapter):
    """SmartEdu search-only entrypoint."""

    platform_name = "smartedu"

    search_script = SCRIPTS_DIR / "smartedu" / "smartedu_resources.py"

    def _build_search_cmd(self, query: str, max_results: int, params: dict[str, Any], output_file: Path) -> list[str] | None:
        """SmartEdu 用 search-resources 子命令（非约定的 search）。"""
        if self.search_script is None or not self.search_script.exists():
            return None
        cmd: list[str] = [
            sys.executable, str(self.search_script),
            "search-resources",
            "--query", query,
            "--limit", str(max_results),
            "-o", str(output_file),
        ]
        return cmd


ADAPTER = SmartEduSearchAdapter()
