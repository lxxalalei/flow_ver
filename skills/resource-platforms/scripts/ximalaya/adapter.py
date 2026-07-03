#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class XimalayaSearchAdapter(CLISearchAdapter):
    platform_name = "ximalaya"
    search_script = SCRIPTS_DIR / "ximalaya" / "ximalaya_search.py"

    def _build_search_cmd(self, query: str, max_results: int, params: dict[str, Any], output_file: Path) -> list[str] | None:
        cmd = [sys.executable, str(self.search_script), "search", query, "--max", str(max_results)]
        if params.get("core"):
            cmd.extend(["--core", str(params["core"])])
        if params.get("free_only"):
            cmd.append("--free-only")
        if params.get("sort"):
            cmd.extend(["--sort", str(params["sort"])])
        cmd.extend(["-o", str(output_file)])
        return cmd


ADAPTER = XimalayaSearchAdapter()
