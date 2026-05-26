#!/usr/bin/env python3
"""
Build RemoteAble.app using PyInstaller (macOS only).

Usage:
    pip install -r requirements.txt pyinstaller pillow
    python scripts/build_mac_app.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "RemoteAble.spec"
DIST_APP = ROOT / "dist" / "RemoteAble.app"


def main() -> int:
    if sys.platform != "darwin":
        print("RemoteAble.app can only be built on macOS.", file=sys.stderr)
        return 1

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        cwd=ROOT,
        check=True,
    )

    if not DIST_APP.is_dir():
        print(f"Expected app bundle not found: {DIST_APP}", file=sys.stderr)
        return 1

    print(f"Built {DIST_APP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
