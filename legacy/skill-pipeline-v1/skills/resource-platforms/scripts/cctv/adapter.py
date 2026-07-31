#!/usr/bin/env python3
"""CCTV search adapter for resource-platforms."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class CCTVSearchAdapter(CLISearchAdapter):
    platform_name = "cctv"
    search_script = SCRIPTS_DIR / "cctv" / "cctv_search.py"
    timeout_seconds = 45

    def _build_search_cmd(self, query: str, max_results: int, params: dict[str, Any], output_file: Path) -> list[str] | None:
        if self.search_script is None or not self.search_script.exists():
            return None
        cmd = [
            sys.executable,
            str(self.search_script),
            "search",
            query,
            "--max",
            str(max_results),
            "-o",
            str(output_file),
        ]
        core = params.get("type") or params.get("core")
        if core:
            cmd.extend(["--type", str(core)])
        channel = params.get("channel")
        if channel:
            cmd.extend(["--channel", str(channel)])
        return cmd


ADAPTER = CCTVSearchAdapter()
