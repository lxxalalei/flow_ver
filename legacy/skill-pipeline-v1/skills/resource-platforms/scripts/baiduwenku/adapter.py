#!/usr/bin/env python3
"""Baidu Wenku search-only adapter."""

from __future__ import annotations

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class BaiduWenkuSearchAdapter(CLISearchAdapter):
    """Search public Baidu Wenku result metadata."""

    platform_name = "baiduwenku"
    search_script = SCRIPTS_DIR / "baiduwenku" / "baiduwenku_search.py"
    timeout_seconds = 45


ADAPTER = BaiduWenkuSearchAdapter()
