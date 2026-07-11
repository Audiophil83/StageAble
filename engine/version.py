"""Read the StageAble application version."""

from __future__ import annotations

import os
import plistlib
import sys
from functools import lru_cache
from pathlib import Path


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


_DEV_VERSION = "0.0.0-dev"


@lru_cache(maxsize=1)
def get_version() -> str:
    env_version = os.environ.get("STAGEABLE_VERSION", "").strip()
    if env_version:
        return env_version

    if getattr(sys, "frozen", False):
        plist_path = Path(sys.executable).resolve().parent.parent / "Info.plist"
        if plist_path.is_file():
            with plist_path.open("rb") as plist_file:
                plist = plistlib.load(plist_file)
            version = plist.get("CFBundleShortVersionString")
            if (
                isinstance(version, str)
                and version.strip()
                and version.strip() != _DEV_VERSION
            ):
                return version.strip()

    version_file = _project_root() / "VERSION"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version

    return _DEV_VERSION
