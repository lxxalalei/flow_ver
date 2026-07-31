#!/usr/bin/env python3
"""Zhihu search-only adapter."""

from __future__ import annotations

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class ZhihuSearchAdapter(CLISearchAdapter):
    """知乎平台 Skill。"""

    platform_name = "zhihu"
    search_script = SCRIPTS_DIR / "zhihu" / "zhihu_search.py"


ADAPTER = ZhihuSearchAdapter()
