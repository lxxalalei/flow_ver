#!/usr/bin/env python3
from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class Open163SearchAdapter(CLISearchAdapter):
    platform_name = "open163"
    search_script = SCRIPTS_DIR / "open163" / "open163_search.py"


ADAPTER = Open163SearchAdapter()
