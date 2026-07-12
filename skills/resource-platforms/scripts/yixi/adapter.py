#!/usr/bin/env python3
"""Yixi search adapter."""

from __future__ import annotations

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class YixiSearchAdapter(CLISearchAdapter):
    platform_name = "yixi"
    search_script = SCRIPTS_DIR / "yixi" / "yixi_search.py"
    timeout_seconds = 45


ADAPTER = YixiSearchAdapter()
