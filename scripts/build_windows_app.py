#!/usr/bin/env python3
"""
Build ShowAble for Windows using PyInstaller.

Usage:
    pip install -r requirements.txt pyinstaller pillow pystray
    python scripts/build_windows_app.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "ShowAble-windows.spec"
DIST_DIR = ROOT / "dist" / "ShowAble"
VERSION_FILE = ROOT / "VERSION"


def read_version() -> str:
    if VERSION_FILE.is_file():
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        if version:
            return version
    return "0.0.0-dev"


def main() -> int:
    if sys.platform != "win32":
        print("ShowAble Windows build must run on Windows.", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.setdefault("SHOWABLE_VERSION", read_version())

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        cwd=ROOT,
        check=True,
        env=env,
    )

    if not DIST_DIR.is_dir():
        print(f"Expected output directory not found: {DIST_DIR}", file=sys.stderr)
        return 1

    print(f"Built {DIST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
