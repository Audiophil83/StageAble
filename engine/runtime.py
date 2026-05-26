"""
Runtime Loop — the core engine that polls Ableton at ~20 Hz, resolves
active timeline events, detects STOP crossings, and broadcasts state
to all connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .config import get_app_settings
from .osc_client import AbletonOSCClient
from .scanner import scan_arrangement
from .setlist_loader import load_active_setlist
from .state import ConnectionStatus, EngineState, _event_to_dict, engine_state
from .timeline import Timeline

logger = logging.getLogger(__name__)

WS_GROUP = "engine"
AUTO_CUE_MIN_PLAY_DELAY = 0.05  # seconds between cue jump and play


class RuntimeEngine:
    """Main engine loop that bridges Ableton ↔ backend ↔ WebSocket clients."""

    def __init__(
        self,
        state: EngineState | None = None,
        osc: AbletonOSCClient | None = None,
    ):
        self.state = state or engine_state
        self.cfg = get_app_settings()
        self.osc = osc or AbletonOSCClient(
            host=self.cfg.ableton_osc_host,
            send_port=self.cfg.ableton_osc_send_port,
            recv_port=self.cfg.ableton_osc_recv_port,
        )
        self._poll_interval = 1.0 / self.cfg.engine_poll_hz
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._prev_position: float = 0.0
        self._prev_snapshot: dict | None = None
        self._pending_position: float | None = None
        self._pending_cue_name: str | None = None
        self._auto_advance_deadline: float | None = None
        self._auto_advance_target_index: int | None = None
        self._auto_advance_cue_name: str | None = None

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the OSC client and the polling loop in a background thread."""
        if self._running:
            logger.warning("Engine already running")
            return

        self.state.update(connection_status=ConnectionStatus.CONNECTING)
        self.osc.start()

        # Test connection
        if self.osc.is_connected():
            self.state.update(connection_status=ConnectionStatus.CONNECTED)
            logger.info("Connected to Ableton Live")
            self._initial_scan()
        else:
            self.state.update(connection_status=ConnectionStatus.DISCONNECTED)
            logger.warning("Ableton not reachable — will retry in poll loop")

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="engine-loop"
        )
        self._thread.start()
        logger.info("Runtime engine started (%.0f Hz)", self.cfg.engine_poll_hz)

    def stop(self) -> None:
        """Stop the engine and OSC client."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        self.osc.stop()
        self.state.update(connection_status=ConnectionStatus.DISCONNECTED)
        logger.info("Runtime engine stopped")

    # ── commands (called from REST / WebSocket) ───────────────────────

    def cmd_play(self) -> None:
        self._cancel_auto_advance()
        # When Ableton is stopped, seek/cue jumps may not stick on
        # start_playing. Re-apply immediately before playing so the two OSC
        # messages arrive back-to-back and Ableton starts from the right spot.
        pending_cue = self._pending_cue_name
        if pending_cue is not None:
            self.osc.cue_point_jump(pending_cue)
            self._pending_cue_name = None
        pending = self._pending_position
        if pending is not None:
            self.osc.set_current_song_time(pending)
            self._pending_position = None
        self.osc.transport_play()

    def cmd_stop(self) -> None:
        self._cancel_auto_advance()
        self.osc.transport_stop()

    def cmd_seek(self, beat: float) -> None:
        """Seek to a specific beat position."""
        self._cancel_auto_advance()
        self._pending_cue_name = None
        self.osc.set_current_song_time(beat)
        if not self.state.is_playing:
            self._pending_position = beat

    def cmd_jump_to_song(self, song_index: int) -> None:
        """Jump to a song by timeline index via a matching cue point."""
        self._cancel_auto_advance()
        tl = self.state.timeline
        if tl is None:
            return
        song = tl.song_at_index(song_index)
        if song is None:
            logger.warning("Song index %d out of range", song_index)
            return
        self._jump_to_song_by_name(song.name)

    def cmd_jump_to_setlist_index(self, setlist_index: int) -> None:
        """Jump to a song by position in the active setlist."""
        self._cancel_auto_advance()
        self._jump_to_setlist_index_no_cancel(setlist_index)

    def _jump_to_setlist_index_no_cancel(self, setlist_index: int) -> None:
        active = self.state.active_setlist
        if not active:
            logger.warning("No active setlist — cannot jump by setlist index")
            return
        entries = active.get("entries") or []
        if setlist_index < 0 or setlist_index >= len(entries):
            logger.warning("Setlist index %d out of range", setlist_index)
            return
        entry = entries[setlist_index]
        if entry.get("missing"):
            logger.warning(
                "Setlist entry '%s' is not in the current arrangement scan",
                entry.get("song_name"),
            )
            return
        self._jump_to_song_by_name(entry["song_name"])

    def _jump_to_song_by_name(self, cue_name: str) -> None:
        if not self._has_cue_point(cue_name):
            logger.warning(
                "No cue point named '%s' — add a cue marker with the same name "
                "as the SONGS clip",
                cue_name,
            )
            return

        self._pending_position = None
        self.osc.cue_point_jump(cue_name)
        is_playing = self.osc.get_is_playing()
        if is_playing is None:
            is_playing = False
        if not is_playing:
            self._pending_cue_name = cue_name
        logger.info("Jump to song '%s' via cue point", cue_name)

    def cmd_jump_to_section(self, start_beat: float) -> None:
        """Jump to a section by its start beat, applying preroll."""
        self._cancel_auto_advance()
        self._pending_cue_name = None
        preroll_beats = self._preroll_beats()
        target = max(0.0, start_beat - preroll_beats)
        self.osc.set_current_song_time(target)
        if not self.state.is_playing:
            self._pending_position = target

    def cmd_rescan(self) -> None:
        """Re-scan the arrangement and rebuild the timeline."""
        self._cancel_auto_advance()
        self._initial_scan()
        self._broadcast()

    def reload_active_setlist(self) -> None:
        """Reload the active setlist from the database."""
        self._cancel_auto_advance()
        active = load_active_setlist(self.state.timeline)
        self.state.update(active_setlist=active, active_setlist_index=None)
        self._broadcast()

    def apply_settings(self) -> None:
        """Apply updated configuration from the database."""
        cfg = get_app_settings()
        self._poll_interval = 1.0 / cfg.engine_poll_hz

        osc_changed = (
            self.osc.host != cfg.ableton_osc_host
            or self.osc.send_port != cfg.ableton_osc_send_port
            or self.osc.recv_port != cfg.ableton_osc_recv_port
        )
        if not osc_changed:
            logger.info("Engine settings applied (poll=%d Hz)", cfg.engine_poll_hz)
            return

        was_running = self._running
        if was_running:
            self.osc.stop()

        self.osc = AbletonOSCClient(
            host=cfg.ableton_osc_host,
            send_port=cfg.ableton_osc_send_port,
            recv_port=cfg.ableton_osc_recv_port,
        )

        if was_running:
            self.state.update(connection_status=ConnectionStatus.CONNECTING)
            self.osc.start()
            if self.osc.is_connected():
                self.state.update(connection_status=ConnectionStatus.CONNECTED)
                self._initial_scan()
            else:
                self.state.update(connection_status=ConnectionStatus.DISCONNECTED)

        logger.info(
            "Engine OSC settings applied (%s:%d/%d, poll=%d Hz)",
            cfg.ableton_osc_host,
            cfg.ableton_osc_send_port,
            cfg.ableton_osc_recv_port,
            cfg.engine_poll_hz,
        )

    # ── internal ──────────────────────────────────────────────────────

    def _preroll_beats(self) -> float:
        """Preroll in beats (default = 1 bar = numerator beats)."""
        cfg = get_app_settings()
        return float(self.state.signature_numerator * cfg.default_preroll_bars)

    def _has_cue_point(self, name: str) -> bool:
        return any(cp["name"] == name for cp in self.state.cue_points)

    def _cancel_auto_advance(self) -> None:
        self._auto_advance_deadline = None
        self._auto_advance_target_index = None
        self._auto_advance_cue_name = None

    def _auto_resume_playback(self, cue_name: str) -> None:
        """Resume transport after auto-cue (re-apply cue then play)."""
        self.osc.cue_point_jump(cue_name)
        self.osc.transport_play()
        self._pending_cue_name = None
        self._pending_position = None
        logger.info("Auto-cue: playing '%s'", cue_name)

    def _setlist_index_for_song(self, song_name: str | None) -> int | None:
        if not song_name:
            return None
        active = self.state.active_setlist
        if not active:
            return None
        for i, entry in enumerate(active.get("entries") or []):
            if entry.get("song_name") == song_name and not entry.get("missing"):
                return i
        return None

    def _schedule_auto_advance(self, setlist_index: int) -> None:
        active = self.state.active_setlist
        if not active:
            logger.info("Auto-cue skipped — no active setlist")
            return
        entries = active.get("entries") or []
        if setlist_index < 0 or setlist_index >= len(entries):
            logger.warning(
                "Auto-cue skipped — setlist index %d out of range", setlist_index
            )
            return
        entry = entries[setlist_index]
        if not entry.get("auto_cue_next"):
            logger.info(
                "Auto-cue disabled for '%s' — enable 'Auto-cue next song' in setlist",
                entry.get("song_name"),
            )
            return
        next_index = setlist_index + 1
        if next_index >= len(entries):
            logger.info(
                "Auto-cue skipped — '%s' is the last song in the setlist",
                entry.get("song_name"),
            )
            return
        next_entry = entries[next_index]
        if next_entry.get("missing"):
            logger.warning(
                "Cannot auto-cue missing song '%s'",
                next_entry.get("song_name"),
            )
            return
        next_name = next_entry.get("song_name")
        if not self._has_cue_point(next_name):
            logger.warning(
                "Cannot auto-cue — no cue point named '%s'",
                next_name,
            )
            return
        gap = float(entry.get("gap_seconds") or 0.0)
        play_delay = max(gap, AUTO_CUE_MIN_PLAY_DELAY)
        self._auto_advance_target_index = next_index
        self._auto_advance_cue_name = next_name
        self._auto_advance_deadline = time.time() + play_delay

        self._jump_to_setlist_index_no_cancel(next_index)
        logger.info(
            "Auto-cue: jumped to '%s', play in %.2fs",
            next_name,
            play_delay,
        )

    def _process_auto_advance(self) -> dict | None:
        if self._auto_advance_deadline is None or self._auto_advance_cue_name is None:
            return None

        remaining = self._auto_advance_deadline - time.time()
        next_name = self._auto_advance_cue_name

        if remaining <= 0:
            cue_name = self._auto_advance_cue_name
            self._cancel_auto_advance()
            if cue_name:
                self._auto_resume_playback(cue_name)
            return None

        return {
            "active": True,
            "seconds_remaining": round(max(0.0, remaining), 1),
            "next_song_name": next_name,
        }

    def _initial_scan(self) -> None:
        """Read arrangement data and build the timeline."""
        try:
            tl = scan_arrangement(self.osc)
            self.state.update(
                timeline=tl,
                timeline_errors=tl.errors,
            )
            # Read tempo/time signature
            tempo = self.osc.get_tempo()
            if tempo:
                self.state.update(tempo=tempo)
            num = self.osc.get_signature_numerator()
            den = self.osc.get_signature_denominator()
            if num:
                self.state.update(signature_numerator=num)
            if den:
                self.state.update(signature_denominator=den)

            # Read cue points (song jumps use cue markers, not SONGS clip positions)
            cue_raw = self.osc.get_cue_points()
            cue_points: list[dict] = []
            if cue_raw is not None:
                cue_points = [
                    {"name": name, "time": round(time, 4)}
                    for name, time in cue_raw
                ]
                self.state.update(cue_points=cue_points)

            scan_errors = list(tl.errors)
            if tl.is_valid and cue_raw is not None:
                cue_names = {name for name, _ in cue_raw}
                for song in tl.all_songs():
                    if song.name not in cue_names:
                        scan_errors.append(
                            f"No cue point named '{song.name}' — add a cue marker "
                            "with the same name as the SONGS clip"
                        )
            self.state.update(timeline_errors=scan_errors)

            self.reload_active_setlist()

            if not tl.is_valid:
                self.state.update(connection_status=ConnectionStatus.ERROR)
        except Exception:
            logger.exception("Error during arrangement scan")
            self.state.update(
                connection_status=ConnectionStatus.ERROR,
                timeline_errors=["Failed to scan arrangement"],
            )

    def _run_loop(self) -> None:
        """Main polling loop — runs in a dedicated thread."""
        reconnect_interval = 5.0
        last_reconnect_attempt = 0.0

        while self._running:
            loop_start = time.monotonic()

            try:
                if self.state.connection_status == ConnectionStatus.DISCONNECTED:
                    # Attempt reconnect periodically
                    now = time.monotonic()
                    if now - last_reconnect_attempt > reconnect_interval:
                        last_reconnect_attempt = now
                        if self.osc.is_connected():
                            self.state.update(
                                connection_status=ConnectionStatus.CONNECTED
                            )
                            self._initial_scan()
                            logger.info("Reconnected to Ableton Live")
                else:
                    self._poll_tick()

            except Exception:
                logger.exception("Error in engine loop tick")
                self.state.update(connection_status=ConnectionStatus.ERROR)

            # Sleep to maintain target Hz
            elapsed = time.monotonic() - loop_start
            sleep_time = self._poll_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _poll_tick(self) -> None:
        """Single tick of the poll loop."""
        # 1. Read transport state
        position = self.osc.get_current_song_time()
        if position is None:
            # Connection lost?
            if not self.osc.is_connected():
                self.state.update(connection_status=ConnectionStatus.DISCONNECTED)
            return

        is_playing = self.osc.get_is_playing()
        if is_playing is None:
            is_playing = False

        prev_pos = self._prev_position
        self._prev_position = position

        # Clear pending seek/cue once Ableton is actually playing
        if is_playing:
            self._pending_position = None
            self._pending_cue_name = None

        # 2. Resolve active events
        tl = self.state.timeline
        active_song = None
        active_song_index = None
        active_setlist_index = None
        active_section = None
        active_lyrics: list[dict] = []
        next_stop = None
        stop_crossed = False
        stop_setlist_index: int | None = None

        if tl is not None and tl.is_valid:
            song_evt = tl.active_song(position)
            if song_evt:
                active_song = _event_to_dict(song_evt)
                active_song_index = tl.song_index(position)

            section_evt = tl.active_section(position)
            if section_evt:
                active_section = _event_to_dict(section_evt)

            lyric_evts = tl.active_lyrics(position)
            active_lyrics = [_event_to_dict(l) for l in lyric_evts]

            # 3. STOP crossing detection
            if is_playing and prev_pos < position:
                stops = tl.stops_in_range(prev_pos, position)
                if stops:
                    stop_beat = stops[0].start_beat
                    logger.info(
                        "STOP crossing detected at beat %.2f (prev=%.2f cur=%.2f)",
                        stop_beat,
                        prev_pos,
                        position,
                    )
                    self.osc.transport_stop()
                    is_playing = False
                    stop_crossed = True
                    # Playhead may already be past the song clip end at STOP;
                    # resolve the song from just before the crossing.
                    song_at_stop = tl.active_song(prev_pos) or tl.active_song(
                        stop_beat - 0.001
                    )
                    if song_at_stop:
                        stop_setlist_index = self._setlist_index_for_song(
                            song_at_stop.name
                        )

            # Next upcoming stop
            stop_evt = tl.next_stop_after(position)
            if stop_evt:
                next_stop = stop_evt.start_beat

        active_setlist = self.state.active_setlist
        if active_setlist and active_song:
            active_setlist_index = self._setlist_index_for_song(
                active_song.get("name")
            )

        if stop_crossed:
            if stop_setlist_index is not None:
                self._schedule_auto_advance(stop_setlist_index)
            elif self.state.active_setlist:
                logger.info(
                    "STOP crossed — current song not found in active setlist "
                    "(prev_pos=%.2f, cur=%.2f)",
                    prev_pos,
                    position,
                )
            else:
                logger.info("STOP crossed — no active setlist")

        auto_advance = self._process_auto_advance()

        # 4. Update state
        self.state.update(
            is_playing=is_playing,
            transport_position=position,
            active_song=active_song,
            active_song_index=active_song_index,
            active_setlist_index=active_setlist_index,
            active_section=active_section,
            active_lyrics=active_lyrics,
            next_stop=next_stop,
            auto_advance=auto_advance,
        )

        # 5. Broadcast to WebSocket clients (only if changed)
        self._broadcast()

    def _broadcast(self) -> None:
        """Send current state to all connected WebSocket clients."""
        snapshot = self.state.snapshot()

        # Only broadcast if something changed
        if snapshot == self._prev_snapshot:
            return
        self._prev_snapshot = snapshot

        try:
            channel_layer = get_channel_layer()
            if channel_layer is not None:
                async_to_sync(channel_layer.group_send)(
                    WS_GROUP,
                    {
                        "type": "engine.state",
                        "data": snapshot,
                    },
                )
        except Exception:
            logger.debug("Could not broadcast state (channel layer not ready)")


# ── Global singleton ──────────────────────────────────────────────────
_engine: RuntimeEngine | None = None


def get_engine() -> RuntimeEngine:
    global _engine
    if _engine is None:
        _engine = RuntimeEngine()
    return _engine
