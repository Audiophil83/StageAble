#!/usr/bin/env python3
"""
Build StageAble.app using PyInstaller (macOS only).

Usage:
    pip install -r requirements.txt pyinstaller pillow
    python scripts/build_mac_app.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "StageAble.spec"
DIST_APP = ROOT / "dist" / "StageAble.app"
VERSION_FILE = ROOT / "VERSION"


def read_version() -> str:
    if VERSION_FILE.is_file():
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        if version:
            return version
    return "0.0.0-dev"


def main() -> int:
    if sys.platform != "darwin":
        print("StageAble.app can only be built on macOS.", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.setdefault("STAGEABLE_VERSION", read_version())

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        cwd=ROOT,
        check=True,
        env=env,
    )

    if not DIST_APP.is_dir():
        print(f"Expected app bundle not found: {DIST_APP}", file=sys.stderr)
        return 1

    print(f"Built {DIST_APP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
