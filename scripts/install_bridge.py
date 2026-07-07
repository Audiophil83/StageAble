#!/usr/bin/env python3
"""Install the RemoteAble Bridge control surface into Ableton Live.

This copies the self-contained ``remoteable_bridge`` package into Live's User
Library as a Remote Script named ``RemoteAble``. Unlike the old patch flow, it
does NOT require AbletonOSC to be installed first — the bridge bundles its own
OSC stack.

Usage:
    python scripts/install_bridge.py            # install / reinstall
    python scripts/install_bridge.py --uninstall
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a standalone script (`python scripts/install_bridge.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.bridge_installer import (  # noqa: E402
    BridgeInstallError,
    install,
    uninstall,
)


def _install() -> int:
    try:
        dest = install()
    except BridgeInstallError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Installed RemoteAble Bridge -> {dest}")
    print(
        "\nNext steps:\n"
        "  1. Restart Ableton Live.\n"
        "  2. Preferences > Link / Tempo / MIDI > Control Surface: select "
        "'RemoteAble'.\n"
        "  3. Launch RemoteAble."
    )
    return 0


def _uninstall() -> int:
    removed = uninstall()
    if removed is None:
        print("RemoteAble Bridge is not installed (nothing to remove).")
    else:
        print(f"Removed {removed}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the installed RemoteAble control surface.",
    )
    args = parser.parse_args()
    return _uninstall() if args.uninstall else _install()


if __name__ == "__main__":
    raise SystemExit(main())
