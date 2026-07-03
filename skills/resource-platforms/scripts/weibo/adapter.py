#!/usr/bin/env python3
"""Weibo search-only adapter."""

from __future__ import annotations

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class WeiboSearchAdapter(CLISearchAdapter):
    """微博平台 Skill。"""

    platform_name = "weibo"

    search_script = SCRIPTS_DIR / "weibo" / "weibo_search.py"


ADAPTER = WeiboSearchAdapter()
