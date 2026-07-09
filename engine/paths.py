"""Cross-platform application data paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "RemoteAble"


def app_data_dir() -> Path:
    """Return the per-user application data directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def daphne_log_path() -> Path:
    return app_data_dir() / "daphne.log"
