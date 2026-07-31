#!/usr/bin/env python3
"""Downloader-owned entrypoint for the existing Douyin engine."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[3] / "resource-platforms/scripts/douyin/douyin_dl.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="下载单个抖音资源")
    subparsers = parser.add_subparsers(dest="command")
    command = subparsers.add_parser("download")
    command.add_argument("source_url")
    command.add_argument("-o", "--output", required=True)
    command.add_argument("--cookie")
    command.add_argument("--cdp")
    args = parser.parse_args()
    if args.command != "download":
        parser.print_help(sys.stderr)
        return 2
    if not ENGINE.is_file():
        print("抖音下载引擎不存在", file=sys.stderr)
        return 1
    child = [sys.executable, str(ENGINE)]
    if args.cdp:
        child.extend(["--cdp", args.cdp])
    child.extend(["download", args.source_url, "-o", args.output])
    if args.cookie:
        child.extend(["--cookie", args.cookie])
    return subprocess.run(child, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
