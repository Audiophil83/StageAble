#!/usr/bin/env python3
"""Install Remoteable's AbletonOSC patches into Live's User Library."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_FILES = (
    REPO_ROOT / "vendor/abletonosc/abletonosc/track.py",
    REPO_ROOT / "vendor/abletonosc/abletonosc/song.py",
)


def _candidate_roots() -> list[Path]:
    home = Path.home()
    roots = [
        home / "Music/Ableton/User Library/Remote Scripts/AbletonOSC",
        home / "Documents/Ableton/User Library/Remote Scripts/AbletonOSC",
    ]
    # Common alternate User Library locations on macOS
    for name in ("User Library", "Ableton User Library"):
        roots.append(home / "Music/Ableton" / name / "Remote Scripts/AbletonOSC")
    return roots


def find_abletonosc_install() -> Path | None:
    for root in _candidate_roots():
        track_py = root / "abletonosc" / "track.py"
        if track_py.is_file():
            return root
    return None


def _install_patch(install_root: Path, patch_file: Path) -> None:
    rel = patch_file.relative_to(REPO_ROOT / "vendor/abletonosc")
    dest = install_root / rel
    backup = dest.with_suffix(".py.orig")
    if not backup.exists():
        shutil.copy2(dest, backup)
        print(f"Backed up original to {backup}")

    shutil.copy2(patch_file, dest)
    print(f"Installed patch: {dest}")


def main() -> int:
    missing = [p for p in PATCH_FILES if not p.is_file()]
    if missing:
        for path in missing:
            print(f"Patch file missing: {path}", file=sys.stderr)
        return 1

    install_root = find_abletonosc_install()
    if install_root is None:
        print(
            "AbletonOSC not found in the usual User Library locations.\n"
            "Install upstream AbletonOSC first, then re-run this script.\n"
            "Expected: .../Remote Scripts/AbletonOSC/abletonosc/track.py",
            file=sys.stderr,
        )
        return 1

    for patch_file in PATCH_FILES:
        _install_patch(install_root, patch_file)

    print("Restart Ableton Live and re-select the AbletonOSC control surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
