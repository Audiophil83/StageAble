"""
Shared runtime state — single source of truth for the backend.

This module holds the global ``EngineState`` singleton that the runtime loop
updates and WebSocket consumers read from.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .timeline import Timeline, TimelineEvent


class ConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class EngineState:
    """Mutable snapshot of the engine's current state.

    Updated by the runtime loop, read by WebSocket consumers and REST views.
    All access must go through the lock.
    """

    # Connection
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED

    # Timeline
    timeline: Optional[Timeline] = None
    timeline_errors: list[str] = field(default_factory=list)

    # Transport
    is_playing: bool = False
    transport_position: float = 0.0  # beats
    tempo: float = 120.0
    signature_numerator: int = 4
    signature_denominator: int = 4

    # Cue points (name -> index mapping for song jumps)
    cue_points: list[dict] = field(default_factory=list)

    # Resolved state
    active_song: Optional[dict] = None
    active_song_index: Optional[int] = None
    active_section: Optional[dict] = None
    active_lyrics: list[dict] = field(default_factory=list)
    next_stop: Optional[float] = None

    # Timestamps
    last_update: float = 0.0

    # Lock for thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def update(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            self.last_update = time.time()

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of the current state."""
        with self._lock:
            return {
                "connection_status": self.connection_status.value,
                "is_playing": self.is_playing,
                "transport_position": round(self.transport_position, 4),
                "tempo": round(self.tempo, 2),
                "signature_numerator": self.signature_numerator,
                "signature_denominator": self.signature_denominator,
                "active_song": self.active_song,
                "active_song_index": self.active_song_index,
                "active_section": self.active_section,
                "active_lyrics": self.active_lyrics,
                "next_stop": round(self.next_stop, 4) if self.next_stop else None,
                "cue_points": self.cue_points,
                "timeline_valid": (
                    self.timeline.is_valid if self.timeline else False
                ),
                "timeline_errors": self.timeline_errors,
                "last_update": self.last_update,
            }

    def get_setlist(self) -> list[dict]:
        """Return the full song list from the timeline."""
        with self._lock:
            if self.timeline is None:
                return []
            return [
                {
                    "index": i,
                    "name": evt.name,
                    "start_beat": round(evt.start_beat, 4),
                    "end_beat": round(evt.end_beat, 4) if evt.end_beat else None,
                    "duration_beats": round(evt.duration, 4) if evt.duration else None,
                }
                for i, evt in enumerate(self.timeline.all_songs())
            ]

    def get_sections(self) -> list[dict]:
        """Return all sections."""
        with self._lock:
            if self.timeline is None:
                return []
            return [
                {
                    "name": evt.name,
                    "start_beat": round(evt.start_beat, 4),
                    "end_beat": round(evt.end_beat, 4) if evt.end_beat else None,
                }
                for evt in self.timeline.all_sections()
            ]


def _event_to_dict(evt: TimelineEvent | None) -> dict | None:
    if evt is None:
        return None
    return {
        "name": evt.name,
        "type": evt.type.value,
        "start_beat": round(evt.start_beat, 4),
        "end_beat": round(evt.end_beat, 4) if evt.end_beat else None,
    }


# ── Global singleton ──────────────────────────────────────────────────
engine_state = EngineState()
