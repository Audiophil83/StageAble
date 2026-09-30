#!/usr/bin/env python3
"""
Build StageAble.app using PyInstaller (macOS only).

Usage:
    pip install -r requirements.txt pyinstaller
    python scripts/build_mac_app.py
    python scripts/build_mac_app.py --target-arch x86_64
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "StageAble.spec"
DIST_APP = ROOT / "dist" / "StageAble.app"
VERSION_FILE = ROOT / "VERSION"
TARGET_ARCHES = ("universal2", "x86_64", "arm64")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the StageAble macOS app",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--target-arch",
        choices=TARGET_ARCHES,
        default=os.environ.get("STAGEABLE_TARGET_ARCH", platform.machine()),
        help="macOS architecture to build",
    )
    return parser.parse_args()


def read_version() -> str:
    if VERSION_FILE.is_file():
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        if version:
            return version
    return "0.0.0-dev"


def architectures(path: Path) -> set[str]:
    result = subprocess.run(
        ["lipo", "-archs", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.split())


def main() -> int:
    args = parse_args()

    if sys.platform != "darwin":
        print("StageAble.app can only be built on macOS.", file=sys.stderr)
        return 1

    required_arches = (
        {"x86_64", "arm64"}
        if args.target_arch == "universal2"
        else {args.target_arch}
    )
    python_arches = architectures(Path(sys.executable))
    if not required_arches.issubset(python_arches):
        print(
            f"Cannot build {args.target_arch} with this Python. "
            f"Required {sorted(required_arches)}, but {sys.executable} contains "
            f"{sorted(python_arches)}. Install a python.org universal2 Python.",
            file=sys.stderr,
        )
        return 1

    env = os.environ.copy()
    env.setdefault("STAGEABLE_VERSION", read_version())
    env["STAGEABLE_TARGET_ARCH"] = args.target_arch

    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(SPEC),
        ],
        cwd=ROOT,
        check=True,
        env=env,
    )

    if not DIST_APP.is_dir():
        print(f"Expected app bundle not found: {DIST_APP}", file=sys.stderr)
        return 1

    executable = DIST_APP / "Contents" / "MacOS" / "StageAble"
    actual_arches = architectures(executable)
    if actual_arches != required_arches:
        print(
            f"Unexpected app architecture: expected {sorted(required_arches)}, "
            f"got {sorted(actual_arches)}",
            file=sys.stderr,
        )
        return 1

    print(f"Built {DIST_APP} ({args.target_arch})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
