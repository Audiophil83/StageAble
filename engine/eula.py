"""End User License Agreement helpers for the macOS menu bar app.

Resolves the bundled ``EULA.md`` / ``THIRD-PARTY-LICENSES.txt`` whether running
from the repo or a frozen PyInstaller ``.app`` and tracks first-launch
acceptance under Application Support.
"""

from __future__ import annotations

import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

from engine.paths import app_data_dir
from engine.version import get_version

APP_NAME = "StageAble"

# Shown in the acceptance dialog; the full text lives in EULA.md.
SUMMARY = (
    "StageAble is proprietary software. Copyright \u00a9 2026 Philipp "
    "Schleicher. All rights reserved.\n\n"
    "By clicking Accept you agree to the End User License Agreement (EULA). "
    "The Software is licensed, not sold, for your own personal or internal "
    "business use. You may not redistribute, resell, reverse engineer, or "
    "modify it. It is provided \u201cas is\u201d without warranty, and "
    "liability is limited as set out in the agreement.\n\n"
    "StageAble is not affiliated with or endorsed by Ableton AG. It bundles "
    "third-party open-source components under their own licenses.\n\n"
    "Choose \u201cView Full Agreement\u201d to read the complete EULA."
)


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def eula_path() -> Path:
    return _resource_root() / "EULA.md"


def third_party_licenses_path() -> Path:
    return _resource_root() / "THIRD-PARTY-LICENSES.txt"


def data_dir() -> Path:
    return app_data_dir()


def _marker_path() -> Path:
    return data_dir() / ".eula-accepted"


def is_accepted() -> bool:
    return _marker_path().exists()


def mark_accepted() -> None:
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _marker_path().write_text(
        f"accepted_at={stamp}\nversion={get_version()}\n",
        encoding="utf-8",
    )


def open_document(path: Path) -> bool:
    """Open a bundled document in the user's default application."""
    if not path.is_file():
        return False
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        return False
    return True
