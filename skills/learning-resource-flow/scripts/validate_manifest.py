#!/usr/bin/env python3
"""Validate a session-manifest/v1 document and its completed stage outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from session_state import ensure_current_manifest, validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 learning-resource-flow manifest")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--skip-outputs", action="store_true")
    args = parser.parse_args()
    try:
        session_dir = args.session_dir.resolve()
        manifest = ensure_current_manifest(session_dir)
        errors = validate_manifest(session_dir, manifest, check_outputs=not args.skip_outputs)
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
