#!/usr/bin/env python3
"""Print a one-line status for every platform session in the data dir."""
from __future__ import annotations

import sys
from pathlib import Path

from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionStore


def main() -> int:
    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1]).expanduser().resolve()
    else:
        data_dir = Settings.from_env().data_dir
    for status in SessionStore(data_dir).get_status():
        print(
            f"  {status.platform:12s}  {status.status:12s}"
            f"  captured={status.captured_at or '-'}"
            f"  expires={status.expires_at or '-'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
