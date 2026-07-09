"""Platform-specific desktop status UI dispatch."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from subprocess import Popen


def run_status_ui(
    url: str,
    display: str,
    process: Popen[str],
    bind_host: str,
    port: int,
) -> None:
    if sys.platform == "darwin":
        from engine.status_ui import run

        run(url, display, process, bind_host, port)
        return
    if sys.platform == "win32":
        from engine.tray_ui import run

        run(url, display, process, bind_host, port)
        return
    raise RuntimeError(f"No desktop status UI available on {sys.platform}")
