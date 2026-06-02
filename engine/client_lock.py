"""
Track which WebSocket clients have unlocked full controls.

All clients start locked. The first client to unlock does so without a
warning; additional unlocks are flagged so the UI can confirm first.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_unlocked: set[str] = set()


def other_unlocked_count(channel_name: str) -> int:
    """Return how many *other* clients are currently unlocked."""
    with _lock:
        return len(_unlocked - {channel_name})


def unlock_requires_warning(channel_name: str) -> bool:
    return other_unlocked_count(channel_name) > 0


def is_unlocked(channel_name: str) -> bool:
    with _lock:
        return channel_name in _unlocked


def unlock(channel_name: str) -> None:
    with _lock:
        _unlocked.add(channel_name)


def lock(channel_name: str) -> None:
    with _lock:
        _unlocked.discard(channel_name)


def disconnect(channel_name: str) -> None:
    lock(channel_name)
