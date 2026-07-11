"""Install the ShowAble Bridge control surface into Ableton Live.

Shared logic used by both the CLI (``scripts/install_bridge.py``) and the
menu bar app. Resolves the bundled ``showable_bridge`` source whether running
from the repo or from a frozen PyInstaller ``.app``.

This module intentionally avoids importing Django so it can be used standalone.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Name of the control surface as it appears in Live's Control Surface menu.
INSTALL_NAME = "ShowAble"

# Files/dirs never copied into the installed control surface.
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "logs", ".DS_Store")


class BridgeInstallError(Exception):
    """Raised when the bridge cannot be installed (with a user-facing message)."""


def bridge_source_dir() -> Path:
    """Return the path to the ``showable_bridge`` package source.

    When frozen by PyInstaller the package is bundled under ``sys._MEIPASS``;
    otherwise it lives at the repo root (parent of the ``engine`` package).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "showable_bridge"
    return Path(__file__).resolve().parent.parent / "showable_bridge"


def _remote_scripts_roots() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = []
    if sys.platform == "win32":
        documents = home / "Documents"
        candidates.extend(
            [
                documents / "Ableton" / "User Library" / "Remote Scripts",
                home / "Music" / "Ableton" / "User Library" / "Remote Scripts",
            ]
        )
    else:
        candidates.extend(
            [
                home / "Music/Ableton/User Library/Remote Scripts",
                home / "Documents/Ableton/User Library/Remote Scripts",
                home / "Music/Ableton/Ableton User Library/Remote Scripts",
            ]
        )
    seen: set[Path] = set()
    roots: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            roots.append(path)
    return roots


def find_remote_scripts_dir() -> Path | None:
    """Return an existing 'Remote Scripts' dir, or one we can safely create."""
    roots = _remote_scripts_roots()

    # 1. Prefer a Remote Scripts folder that already exists.
    for root in roots:
        if root.is_dir():
            return root

    # 2. Otherwise, create Remote Scripts inside an existing User Library.
    for root in roots:
        if root.parent.is_dir():
            root.mkdir(parents=True, exist_ok=True)
            return root

    return None


def installed_path(remote_scripts: Path) -> Path:
    return remote_scripts / INSTALL_NAME


def install() -> Path:
    """Install (or reinstall) the bridge. Returns the destination path.

    Raises ``BridgeInstallError`` with a user-facing message on failure.
    """
    source = bridge_source_dir()
    if not (source / "__init__.py").is_file():
        raise BridgeInstallError(f"Bridge source not found at {source}")

    remote_scripts = find_remote_scripts_dir()
    if remote_scripts is None:
        locations = "\n".join(f"  {root.parent}" for root in _remote_scripts_roots())
        raise BridgeInstallError(
            "Could not locate Ableton's User Library. Open Live at least once, "
            "then check Preferences > Library for the User Library location. "
            "Expected one of:\n" + locations
        )

    dest = installed_path(remote_scripts)

    # Clean reinstall so removed files don't linger.
    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(source, dest, ignore=_IGNORE)
    return dest


def uninstall() -> Path | None:
    """Remove the installed control surface. Returns the removed path, or None."""
    remote_scripts = find_remote_scripts_dir()
    if remote_scripts is None:
        return None
    dest = installed_path(remote_scripts)
    if dest.exists():
        shutil.rmtree(dest)
        return dest
    return None
