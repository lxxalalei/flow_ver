#!/usr/bin/env python3
"""Runoob search adapter."""

from __future__ import annotations

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class RunoobSearchAdapter(CLISearchAdapter):
    platform_name = "runoob"
    search_script = SCRIPTS_DIR / "runoob" / "runoob_search.py"
    timeout_seconds = 45


ADAPTER = RunoobSearchAdapter()
