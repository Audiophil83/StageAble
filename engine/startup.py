"""
Auto-start the engine when imported.

Called from the ASGI application or the management command.
Ensures only one engine instance runs per process.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def auto_start_engine() -> None:
    """Start the runtime engine if not already running.

    Safe to call multiple times — only the first call has effect.
    Skipped during migrations and other non-server commands.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True

    # Skip auto-start in management commands (migrate, makemigrations, etc.)
    if os.environ.get("SHOWABLE_NO_ENGINE"):
        logger.info("Engine auto-start disabled (SHOWABLE_NO_ENGINE set)")
        return

    def _start() -> None:
        try:
            from .runtime import get_engine

            get_engine().start()
            logger.info("Engine auto-started")
        except Exception:
            logger.exception("Failed to auto-start engine")

    # Do not block ASGI import — serve the client while the scan runs.
    threading.Thread(target=_start, daemon=True, name="engine-start").start()
