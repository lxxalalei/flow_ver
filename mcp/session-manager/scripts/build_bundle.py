#!/usr/bin/env python3
"""Build a distributable bundle containing the MCP wheel and companion Skill."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


VERSION = "0.4.0"
BUNDLE_NAME = f"openclaw-session-manager-{VERSION}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{BUNDLE_NAME}.zip"

    with tempfile.TemporaryDirectory(prefix="session-manager-bundle-") as temp:
        temp_root = Path(temp)
        wheel_dir = temp_root / "wheel"
        wheel_dir.mkdir()
        build_source = temp_root / "source"
        build_source.mkdir()
        shutil.copy2(root / "pyproject.toml", build_source / "pyproject.toml")
        shutil.copy2(root / "README.md", build_source / "README.md")
        shutil.copytree(root / "src" / "session_manager", build_source / "src" / "session_manager")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(build_source),
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
            ],
            check=True,
        )
        wheels = list(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected one wheel, found {len(wheels)}")

        bundle_root = temp_root / BUNDLE_NAME
        bundle_root.mkdir()
        shutil.copy2(wheels[0], bundle_root / wheels[0].name)
        shutil.copy2(root / "README.md", bundle_root / "INSTALL.md")
        shutil.copytree(root / "contracts", bundle_root / "contracts")
        shutil.copytree(
            root / "distribution" / "skills" / "session-login-flow",
            bundle_root / "skill" / "session-login-flow",
        )

        archive_path.unlink(missing_ok=True)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sorted(bundle_root.rglob("*")):
                if source.is_file():
                    archive.write(source, source.relative_to(temp_root))

    print(archive_path)


if __name__ == "__main__":
    main()
