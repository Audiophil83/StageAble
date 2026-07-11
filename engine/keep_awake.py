"""
macOS system keep-awake via ``caffeinate``.

Browsers cannot suppress the macOS screen saver reliably — the Wake Lock API
only prevents display *sleep* in many cases, not the idle screen saver.  When
StageAble runs locally (typical .app usage), this module starts ``caffeinate
-dims -w <pid>`` on the server Mac so the screen saver and display sleep are
both suppressed while the user has "Keep Screen Awake" enabled in the UI.
Caffeinate exits automatically when StageAble exits, including on crash.
"""

from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_proc: subprocess.Popen[bytes] | None = None


def is_supported() -> bool:
    return sys.platform == "darwin"


def status() -> dict:
    with _lock:
        active = _proc is not None and _proc.poll() is None
    return {
        "active": active,
        "supported": is_supported(),
        "platform": sys.platform,
        "native": is_supported(),
    }


def enable() -> dict:
    """Start ``caffeinate -dims -w <pid>`` (display, idle, and screen-saver suppression).

    The ``-w`` flag ties caffeinate to this process: when StageAble exits or
    crashes, macOS releases the keep-awake assertion automatically.
    """
    global _proc

    if not is_supported():
        return {**status(), "message": "Native keep-awake is only available on macOS"}

    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {**status(), "message": "Already active"}

        try:
            proc = subprocess.Popen(
                ["caffeinate", "-dims", "-w", str(os.getpid())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.warning("Failed to start caffeinate: %s", exc)
            return {**status(), "error": str(exc)}

        _proc = proc
        logger.info("caffeinate started (pid %s)", proc.pid)

    return {**status(), "message": "macOS system keep-awake enabled"}


def disable() -> dict:
    """Stop the running ``caffeinate`` process, if any."""
    global _proc

    with _lock:
        _stop_unlocked()
    return status()


def _stop_unlocked() -> None:
    global _proc
    if _proc is None:
        return
    if _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _proc.kill()
            _proc.wait(timeout=3)
        logger.info("caffeinate stopped")
    _proc = None


@atexit.register
def _cleanup() -> None:
    with _lock:
        _stop_unlocked()
