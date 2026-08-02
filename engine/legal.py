"""Bundled legal document helpers for the desktop apps.

Resolves ``LICENSE`` and ``THIRD-PARTY-LICENSES.txt`` whether running from the
repo or a frozen PyInstaller bundle.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def license_path() -> Path:
    return _resource_root() / "LICENSE"


def third_party_licenses_path() -> Path:
    return _resource_root() / "THIRD-PARTY-LICENSES.txt"


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
