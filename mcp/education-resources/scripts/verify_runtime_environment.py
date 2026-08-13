#!/usr/bin/env python3
"""Verify that the active interpreter matches this MCP's runtime contract.

This check intentionally compares source ``pyproject.toml`` with installed
package metadata.  ``pip check`` alone cannot detect an old editable install
whose metadata no longer describes the current source dependencies.
"""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION_NAME = "education-resource-mcp"


def _load_project() -> dict[str, Any]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle).get("project")
    if not isinstance(project, dict):
        raise ValueError("[project] must be a TOML table")
    return project


def _run_pip_check() -> str | None:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return None
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    return output or f"pip check exited with status {completed.returncode}"


def _verify_crypto() -> None:
    """Exercise the lazy Crypto import used by download adapters."""
    from Crypto.Cipher import AES

    key = bytes(range(16))
    plaintext = bytes(range(16))
    encrypted = AES.new(key, AES.MODE_ECB).encrypt(plaintext)
    decrypted = AES.new(key, AES.MODE_ECB).decrypt(encrypted)
    if decrypted != plaintext:
        raise RuntimeError("AES round trip returned different bytes")


def main() -> int:
    errors: list[str] = []
    try:
        project = _load_project()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"ERROR: cannot load {PROJECT_ROOT / 'pyproject.toml'}: {exc}", file=sys.stderr)
        return 2

    expected_version = project.get("version")
    dependencies = project.get("dependencies", [])
    if not isinstance(expected_version, str):
        print("ERROR: project.version must be a string", file=sys.stderr)
        return 2
    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        print("ERROR: project.dependencies must be a list of strings", file=sys.stderr)
        return 2
    expected_requirements = sorted(dependencies)

    try:
        distribution = metadata.distribution(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        errors.append(f"{DISTRIBUTION_NAME} is not installed in {sys.executable}")
    else:
        if distribution.version != expected_version:
            errors.append(
                f"installed {DISTRIBUTION_NAME} version is {distribution.version}, "
                f"but pyproject declares {expected_version}"
            )
        installed_requirements = sorted(
            requirement
            for requirement in (distribution.requires or [])
            if "extra ==" not in requirement
        )
        if installed_requirements != expected_requirements:
            errors.append(
                "installed package metadata dependencies differ from pyproject: "
                f"installed={installed_requirements!r}; expected={expected_requirements!r}"
            )

    for module_name in (
        "education_resource_mcp",
        "mcp",
        "bs4",
        "lxml",
    ):
        try:
            imported = importlib.import_module(module_name)
        except Exception as exc:  # import failures are actionable environment failures.
            errors.append(f"cannot import {module_name}: {exc!r}")
        else:
            if module_name == "education_resource_mcp":
                source_version = getattr(imported, "__version__", None)
                if source_version != expected_version:
                    errors.append(
                        "education_resource_mcp.__version__ differs from pyproject: "
                        f"source={source_version!r}; expected={expected_version!r}"
                    )

    try:
        _verify_crypto()
    except Exception as exc:  # Crypto is imported lazily by production adapters.
        errors.append(f"pycryptodome Crypto AES check failed: {exc!r}")

    pip_check_error = _run_pip_check()
    if pip_check_error is not None:
        errors.append(f"pip check failed: {pip_check_error}")

    if errors:
        print(
            f"Runtime environment verification failed for {DISTRIBUTION_NAME} "
            f"using {sys.executable}:",
            file=sys.stderr,
        )
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        f"Runtime environment verified: {DISTRIBUTION_NAME} {expected_version} "
        f"via {sys.executable}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
