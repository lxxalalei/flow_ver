#!/usr/bin/env python3
"""Bilibili search-only adapter."""

from __future__ import annotations

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class BilibiliSearchAdapter(CLISearchAdapter):
    """Bilibili search-only entrypoint."""

    platform_name = "bilibili"

    search_script = SCRIPTS_DIR / "bilibili" / "bilibili_search.py"


ADAPTER = BilibiliSearchAdapter()
