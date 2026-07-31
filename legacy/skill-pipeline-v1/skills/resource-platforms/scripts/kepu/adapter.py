#!/usr/bin/env python3
"""Kepu China search-only adapter."""

from __future__ import annotations

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class KepuSearchAdapter(CLISearchAdapter):
    """Search public science popularization resources."""

    platform_name = "kepu"
    search_script = SCRIPTS_DIR / "kepu" / "kepu_search.py"
    timeout_seconds = 45


ADAPTER = KepuSearchAdapter()
