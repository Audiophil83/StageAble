"""
Runtime Loop — the core engine that polls Ableton at ~20 Hz, resolves
active timeline events, detects STOP crossings, and broadcasts state
to all connected WebSocket clients.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .config import get_app_settings
from .project_cache import (
    apply_cache_payload_to_state,
    apply_cache_to_state,
    clear_project_state,
    get_or_create_project_record,
    load_last_active_project_cache,
    load_project_cache,
    project_to_state_dict,
    save_project_cache,
    set_last_active_project,
)
from .osc_client import AbletonOSCClient
from .scanner import (
    scan_arrangement,
    scan_meter_map,
    scan_mixer_tracks,
    scan_tracks,
)
from .timeline import Timeline
from .setlist_loader import load_active_setlist
from .state import ConnectionStatus, EngineState, _event_to_dict, engine_state

logger = logging.getLogger(__name__)

WS_GROUP = "engine"
AUTO_CUE_MIN_PLAY_DELAY = 0.05  # seconds between cue jump and play
# AbletonOSC uses fixed ports: 11000 (send) and 11001 (recv).
ABLETON_OSC_SEND_PORT = 11000
ABLETON_OSC_RECV_PORT = 11001
ENGINE_POLL_HZ = 20
# Max beats advanced in one poll tick while playing (~4 beats at 20 Hz / 300 BPM).
MAX_PLAY_STEP_BEATS = 4.0
MAX_SCAN_LOG = 40


class RuntimeEngine:
    """Main engine loop that bridges Ableton ↔ backend ↔ WebSocket clients."""

    def __init__(
        self,
        state: EngineState | None = None,
        osc: AbletonOSCClient | None = None,
    ):
        self.state = state or engine_state
        cfg = get_app_settings()
        self.osc = osc or AbletonOSCClient(
            host=cfg.ableton_osc_host,
            send_port=ABLETON_OSC_SEND_PORT,
            recv_port=ABLETON_OSC_RECV_PORT,
        )
        self._poll_interval = 1.0 / ENGINE_POLL_HZ
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._slow_poll_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._prev_position: float = 0.0
        self._prev_snapshot: dict | None = None
        self._pending_position: float | None = None
        self._pending_cue_name: str | None = None
        self._auto_advance_deadline: float | None = None
        self._auto_advance_cue_name: str | None = None
        self._scan_in_progress = False
        self._scan_messages: list[str] = []
        self._scan_lock = threading.Lock()
        self._current_project_identity: str | None = None

    # ── scan progress (WebSocket clients) ─────────────────────────────

    def get_scan_status(self) -> tuple[bool, list[str]]:
        with self._lock:
            return self._scan_in_progress, list(self._scan_messages)

    def _scan_log(self, message: str) -> None:
        with self._lock:
            self._scan_messages.append(message)
            if len(self._scan_messages) > MAX_SCAN_LOG:
                self._scan_messages = self._scan_messages[-MAX_SCAN_LOG:]
        logger.info(message)
        self._broadcast_scan_progress()

    def _set_scan_in_progress(self, active: bool, *, done: bool = False) -> None:
        with self._lock:
            self._scan_in_progress = active
        self._broadcast_scan_progress(done=done)

    def _broadcast_scan_progress(self, *, done: bool = False) -> None:
        with self._lock:
            messages = list(self._scan_messages)
            in_progress = self._scan_in_progress and not done
        try:
            channel_layer = get_channel_layer()
            if channel_layer is not None:
                async_to_sync(channel_layer.group_send)(
                    WS_GROUP,
                    {
                        "type": "engine.scan_progress",
                        "in_progress": in_progress,
                        "done": done,
                        "messages": messages,
                    },
                )
        except Exception:
            logger.debug("Could not broadcast scan progress")

    @staticmethod
    def _timeline_summary(tl: Timeline) -> str:
        return (
            f"Timeline built: {len(tl.songs)} songs, {len(tl.sections)} sections, "
            f"{len(tl.lyrics)} lyrics, {len(tl.chords)} chords, {len(tl.stops)} stops"
        )

    def _run_arrangement_scan(self, *, broadcast: bool) -> None:
        """Scan arrangement; emit progress for WebSocket clients."""
        with self._scan_lock:
            with self._lock:
                self._scan_messages = []
            self._set_scan_in_progress(True)
            try:
                self._initial_scan(broadcast=broadcast)
            finally:
                self._set_scan_in_progress(False, done=True)

    def _schedule_arrangement_scan(self, *, broadcast: bool = True) -> None:
        """Run a scan in a background thread (startup, rescan, settings)."""

        def work() -> None:
            self._run_arrangement_scan(broadcast=broadcast)

        threading.Thread(target=work, daemon=True, name="arrangement-scan").start()

    def _bootstrap_load(self) -> None:
        """Load cached arrangement and connect to Ableton without scanning."""
        try:
            loaded = False
            if self.osc.is_connected():
                loaded = self._apply_project_from_osc(broadcast=False)
            if not loaded:
                payload = load_last_active_project_cache()
                if payload is not None:
                    apply_cache_payload_to_state(self.state, payload)
                    self._current_project_identity = payload["project"]["identity"]
                    self._scan_log(
                        f"Loaded cached project: {payload['project']['display_name']}"
                    )
                    loaded = True
                elif apply_cache_to_state(self.state):
                    project = self.state.active_project
                    if project:
                        self._current_project_identity = project["identity"]
                    self._scan_log("Loaded cached project from database")
                    loaded = True

            if loaded:
                self.reload_active_setlist(broadcast=False)
            else:
                self._scan_log(
                    "No cached project — use Rescan in the client when Ableton is ready"
                )

            if self.osc.is_connected():
                self.state.update(connection_status=ConnectionStatus.CONNECTED)
                self._scan_log("Connected to Ableton Live")
                tempo = self.osc.get_tempo()
                if tempo:
                    self.state.update(tempo=tempo)
            else:
                self.state.update(connection_status=ConnectionStatus.DISCONNECTED)
                logger.warning("Ableton not reachable — will retry in poll loop")
                self._scan_log(
                    "Ableton not reachable — transport will work when Live is available"
                )

            self._scan_log(f"Runtime engine started ({ENGINE_POLL_HZ} Hz)")
            self._broadcast()
        except Exception:
            logger.exception("Bootstrap load failed")
            self._scan_log("Failed to load engine state")

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start OSC + poll loops; scan the arrangement in the background."""
        if self._running:
            logger.warning("Engine already running")
            return

        self.state.update(connection_status=ConnectionStatus.CONNECTING)
        self.osc.start()

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="engine-loop"
        )
        self._thread.start()

        self._slow_poll_thread = threading.Thread(
            target=self._slow_poll_loop, daemon=True, name="slow-poll"
        )
        self._slow_poll_thread.start()

        threading.Thread(
            target=self._bootstrap_load, daemon=True, name="engine-bootstrap"
        ).start()

        logger.info(
            "Runtime engine poll loop started (%d Hz); project loaded from cache",
            ENGINE_POLL_HZ,
        )

    def stop(self) -> None:
        """Stop the engine and OSC client."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._slow_poll_thread:
            self._slow_poll_thread.join(timeout=3)
        self.osc.stop()
        self.state.update(connection_status=ConnectionStatus.DISCONNECTED)
        logger.info("Runtime engine stopped")

    # ── commands (called from REST / WebSocket) ───────────────────────

    def cmd_play(self) -> None:
        with self._lock:
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
        with self._lock:
            self._cancel_auto_advance()
            if self.state.rehearsal:
                self._exit_rehearsal_mode_locked(stop_transport=False)
            self.osc.transport_stop()

    def _clear_rehearsal_state_locked(self) -> None:
        """Clear rehearsal metadata only (lock held)."""
        self.state.update(rehearsal=None)

    def _exit_rehearsal_mode_locked(self, *, stop_transport: bool = False) -> None:
        """Disable loop, reset bracket to full arrangement, clear state (lock held)."""
        if stop_transport:
            self.osc.transport_stop()
        self.osc.set_loop(False)
        song_length = self.osc.get_song_length()
        if song_length is not None and song_length > 0:
            self.osc.set_loop_start(0.0)
            self.osc.set_loop_length(float(song_length))
        self._clear_rehearsal_state_locked()
        logger.info("Exited rehearsal mode (loop off, bracket reset)")

    def _rehearse_seek_and_play_locked(self, target: float) -> None:
        """Seek to an absolute beat and start or continue transport (lock held)."""
        target = max(0.0, float(target))
        self._pending_cue_name = None
        self._pending_position = None
        self.osc.set_song_time_absolute(target)
        self._sync_prev_playhead(target)
        if not self._is_transport_playing():
            # When stopped, seek may not stick until re-applied right before play.
            self.osc.set_song_time_absolute(target)
            self.osc.transport_play()

    def cmd_rehearse_stop(self) -> None:
        """Stop transport and exit rehearsal loop setup."""
        with self._lock:
            self._cancel_auto_advance()
            self._exit_rehearsal_mode_locked(stop_transport=True)
        self._broadcast()

    def cmd_rehearse_exit(self) -> None:
        """Leave rehearsal: disable loop and reset bracket to full arrangement."""
        with self._lock:
            self._exit_rehearsal_mode_locked(stop_transport=False)
        self._broadcast()

    def cmd_rehearse_play(self, start_beat: float) -> None:
        """Seek to a section start and play without looping."""
        with self._lock:
            self._cancel_auto_advance()
            self._clear_rehearsal_state_locked()
            self.osc.set_loop(False)
            self._rehearse_seek_and_play_locked(start_beat)
        logger.info("Rehearse play from beat %.2f", start_beat)
        self._broadcast()

    def _resolve_contiguous_sections(
        self, start_beats: list[float]
    ) -> list:
        """Return timeline section events for contiguous start_beats."""
        if not start_beats:
            raise ValueError("No sections selected")

        tl = self.state.timeline
        if tl is None:
            raise ValueError("No timeline loaded")

        all_sections = tl.all_sections()
        if not all_sections:
            raise ValueError("No sections in arrangement")

        beat_to_idx: dict[float, int] = {}
        for i, sec in enumerate(all_sections):
            key = round(sec.start_beat, 4)
            beat_to_idx[key] = i

        indices: list[int] = []
        for beat in start_beats:
            key = round(float(beat), 4)
            if key not in beat_to_idx:
                raise ValueError(f"Unknown section at beat {beat}")
            indices.append(beat_to_idx[key])

        indices.sort()
        for i in range(len(indices) - 1):
            if indices[i + 1] != indices[i] + 1:
                raise ValueError("Selected sections must be contiguous")

        return [all_sections[i] for i in indices]

    def cmd_rehearse_loop(self, start_beats: list[float]) -> None:
        """Loop one or more contiguous sections via Ableton loop locators."""
        with self._lock:
            self._cancel_auto_advance()
            self._pending_cue_name = None
            sections = self._resolve_contiguous_sections(start_beats)

            loop_start = sections[0].start_beat
            loop_end = sections[-1].end_beat
            if loop_end is None:
                raise ValueError(
                    f"Section '{sections[-1].name}' has no end beat"
                )
            loop_length = loop_end - loop_start
            if loop_length <= 0:
                raise ValueError("Invalid loop length")

            self.osc.set_loop_start(loop_start)
            self.osc.set_loop_length(loop_length)
            self.osc.set_loop(True)
            self._rehearse_seek_and_play_locked(loop_start)

            rehearsal = {
                "active": True,
                "loop_enabled": True,
                "loop_start": round(loop_start, 4),
                "loop_end": round(loop_end, 4),
                "sections": [
                    {
                        "name": sec.name,
                        "start_beat": round(sec.start_beat, 4),
                        "end_beat": (
                            round(sec.end_beat, 4) if sec.end_beat else None
                        ),
                    }
                    for sec in sections
                ],
            }
            self.state.update(rehearsal=rehearsal)

        names = ", ".join(sec.name for sec in sections)
        logger.info(
            "Rehearse loop: %s (%.2f–%.2f beats)", names, loop_start, loop_end
        )
        self._broadcast()

    def _sync_prev_playhead(self, beat: float | None = None) -> None:
        """Reset poll baseline after a seek/cue so STOP detection does not fire."""
        if beat is None:
            beat = self.osc.get_current_song_time()
        if beat is not None:
            self._prev_position = beat

    def cmd_seek(self, beat: float) -> None:
        """Seek to a specific beat position."""
        with self._lock:
            self._cancel_auto_advance()
            self._pending_cue_name = None
            self.osc.set_current_song_time(beat)
            self._sync_prev_playhead(beat)
            if not self._is_transport_playing():
                self._pending_position = beat

    def cmd_jump_to_song(self, song_index: int) -> None:
        """Jump to a song by timeline index via a matching cue point."""
        with self._lock:
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
        with self._lock:
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
        self._sync_prev_playhead()
        if not self._is_transport_playing():
            self._pending_cue_name = cue_name
        logger.info("Jump to song '%s' via cue point", cue_name)

    def cmd_jump_to_section(self, start_beat: float) -> None:
        """Jump to a section by its start beat."""
        with self._lock:
            self._cancel_auto_advance()
            self._pending_cue_name = None
            target = max(0.0, start_beat)
            self.osc.set_current_song_time(target)
            self._sync_prev_playhead(target)
            if not self._is_transport_playing():
                self._pending_position = target

    def cmd_rescan(self) -> None:
        """Re-scan the arrangement and rebuild the timeline."""
        with self._lock:
            self._cancel_auto_advance()
        self._schedule_arrangement_scan(broadcast=True)

    def refresh_mixer_tracks_mute(self, *, broadcast: bool = True) -> bool:
        """Re-query mute from Ableton for all cached [MIX] tracks.

        Returns True if any mute state changed. Used by the 1 Hz slow-poll loop
        and when opening the mixer tab (``get_mixer_tracks(live=True)``).
        """
        with self._lock:
            cached = list(self.state.mixer_tracks)
        if not cached:
            return False

        updated: list[dict] = []
        changed = False
        for track in cached:
            live = self.osc.get_track_mute(track["index"])
            muted = live if live is not None else track.get("muted", False)
            if muted != track.get("muted"):
                changed = True
            updated.append({**track, "muted": muted})

        if changed:
            with self._lock:
                self.state.update(mixer_tracks=updated)
            if broadcast:
                self._broadcast()
        return changed

    def get_mixer_tracks(self, *, live: bool = True) -> list[dict]:
        """Return mixer tracks.

        With ``live=True`` (default), refresh mute from Ableton first — use when
        opening the mixer tab. With ``live=False``, return the engine cache
        (authoritative immediately after ``cmd_set_track_mute``).
        """
        if live:
            self.refresh_mixer_tracks_mute(broadcast=False)
        return self.state.get_mixer_tracks()

    def cmd_set_track_mute(self, track_index: int, muted: bool) -> None:
        """Mute or unmute a [MIX] track by Ableton track index."""
        with self._lock:
            mixer_indices = {t["index"] for t in self.state.mixer_tracks}
        if track_index not in mixer_indices:
            raise ValueError(f"Track {track_index} is not a mixer track")

        self.osc.set_track_mute(track_index, muted)

        with self._lock:
            updated = [
                {**t, "muted": muted} if t["index"] == track_index else t
                for t in self.state.mixer_tracks
            ]
            self.state.update(mixer_tracks=updated)
        self._broadcast()

    def cmd_apply_mixer_preset(self, preset_tracks: list[dict]) -> list[dict]:
        """Apply mute states from a saved preset to all [MIX] tracks in Ableton."""
        preset_by_index = {
            t["index"]: bool(t["muted"])
            for t in preset_tracks
            if "index" in t and "muted" in t
        }
        preset_by_name = {
            t["name"]: bool(t["muted"])
            for t in preset_tracks
            if "name" in t and "muted" in t
        }

        with self._lock:
            cached = list(self.state.mixer_tracks)

        if not cached:
            return []

        updated: list[dict] = []
        for track in cached:
            idx = track["index"]
            name = track.get("name", "")
            if idx in preset_by_index:
                muted = preset_by_index[idx]
            elif name in preset_by_name:
                muted = preset_by_name[name]
            else:
                muted = track.get("muted", False)

            if muted != track.get("muted"):
                self.osc.set_track_mute(idx, muted)
            updated.append({**track, "muted": muted})

        with self._lock:
            self.state.update(mixer_tracks=updated)
        self._broadcast()
        return updated

    def reload_active_setlist(self, *, broadcast: bool = True) -> None:
        """Reload the active setlist from the database."""
        with self._lock:
            self._cancel_auto_advance()
            project_id = (
                self.state.active_project.get("id")
                if self.state.active_project
                else None
            )
            active = load_active_setlist(self.state.timeline, project_id=project_id)
            self.state.update(active_setlist=active, active_setlist_index=None)
        if broadcast:
            self._broadcast()

    def apply_settings(self) -> None:
        """Apply updated configuration from the database."""
        cfg = get_app_settings()

        if self.osc.host == cfg.ableton_osc_host:
            logger.info("Engine settings applied (host=%s)", cfg.ableton_osc_host)
            return

        was_running = self._running
        if was_running:
            self.osc.stop()

        self.osc = AbletonOSCClient(
            host=cfg.ableton_osc_host,
            send_port=ABLETON_OSC_SEND_PORT,
            recv_port=ABLETON_OSC_RECV_PORT,
        )

        if was_running:
            self.state.update(connection_status=ConnectionStatus.CONNECTING)
            self.osc.start()
            if self.osc.is_connected():
                self.state.update(connection_status=ConnectionStatus.CONNECTED)
                self._schedule_arrangement_scan(broadcast=True)
            else:
                self.state.update(connection_status=ConnectionStatus.DISCONNECTED)

        logger.info("Engine OSC host updated to %s", cfg.ableton_osc_host)

    # ── internal ──────────────────────────────────────────────────────

    def _is_transport_playing(self) -> bool:
        is_playing = self.osc.get_is_playing()
        return False if is_playing is None else is_playing

    def _sync_time_signature_from_playhead(self) -> None:
        """Refresh meter from Ableton at the current playhead (follows TS markers)."""
        num, den = self.osc.get_time_signature()
        if num is None and den is None:
            return
        updates: dict[str, int] = {}
        if num is not None and num != self.state.signature_numerator:
            updates["signature_numerator"] = num
        if den is not None and den != self.state.signature_denominator:
            updates["signature_denominator"] = den
        if updates:
            self.state.update(**updates)

    def _has_cue_point(self, name: str) -> bool:
        return any(cp["name"] == name for cp in self.state.cue_points)

    def _cancel_auto_advance(self) -> None:
        self._auto_advance_deadline = None
        self._auto_advance_cue_name = None

    def _auto_resume_playback(self, cue_name: str) -> None:
        """Resume transport after auto-cue (re-apply cue then play)."""
        self.osc.cue_point_jump(cue_name)
        self.osc.transport_play()
        self._pending_cue_name = None
        self._pending_position = None
        logger.info("Auto-play: playing '%s'", cue_name)

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
            logger.info("Setlist advance skipped — no active setlist")
            return
        entries = active.get("entries") or []
        if setlist_index < 0 or setlist_index >= len(entries):
            logger.warning(
                "Setlist advance skipped — setlist index %d out of range",
                setlist_index,
            )
            return
        entry = entries[setlist_index]
        next_index = setlist_index + 1
        if next_index >= len(entries):
            logger.info(
                "Setlist advance skipped — '%s' is the last song in the setlist",
                entry.get("song_name"),
            )
            return
        next_entry = entries[next_index]
        if next_entry.get("missing"):
            logger.warning(
                "Cannot cue next song — missing from arrangement '%s'",
                next_entry.get("song_name"),
            )
            return
        next_name = next_entry.get("song_name")
        if not self._has_cue_point(next_name):
            logger.warning(
                "Cannot cue next song — no cue point named '%s'",
                next_name,
            )
            return

        self._jump_to_setlist_index_no_cancel(next_index)

        if entry.get("auto_cue_next"):
            gap = float(entry.get("gap_seconds") or 0.0)
            play_delay = max(gap, AUTO_CUE_MIN_PLAY_DELAY)
            self._auto_advance_cue_name = next_name
            self._auto_advance_deadline = time.time() + play_delay
            logger.info(
                "Setlist advance: cued '%s', auto-play in %.2fs",
                next_name,
                play_delay,
            )
        else:
            logger.info(
                "Setlist advance: cued '%s' — press Play when ready",
                next_name,
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

    def _initial_scan(self, *, broadcast: bool = False) -> None:
        """Read arrangement data and build the timeline."""
        try:
            project_info = self.osc.get_project_identity()
            if project_info:
                identity, name, file_path = project_info
                project = get_or_create_project_record(
                    identity=identity,
                    name=name,
                    file_path=file_path,
                )
                self._current_project_identity = identity
                self.state.update(active_project=project_to_state_dict(project))
                set_last_active_project(project)

            # Song metadata before the heavy track/clip scan. A long scan can
            # back up AbletonOSC so later /live/song/get/* queries time out.
            self._scan_log("Reading tempo from Ableton…")
            tempo = self.osc.get_tempo()
            if tempo:
                self.state.update(tempo=tempo)
                self._scan_log(f"Tempo: {tempo:.1f} BPM")

            tl = scan_arrangement(self.osc)
            if tl.errors:
                self._scan_log("Timeline errors: " + "; ".join(tl.errors))

            self._scan_log("Scanning mixer tracks…")
            tracks = scan_tracks(self.osc)
            mixer_tracks = scan_mixer_tracks(self.osc, tracks)
            self.state.update(mixer_tracks=mixer_tracks)
            if mixer_tracks:
                self._scan_log(f"Mixer: {len(mixer_tracks)} [MIX] track(s)")
            else:
                self._scan_log("Mixer: no [MIX] tracks found")

            # Publish the timeline before the meter scan so a meter-map failure
            # cannot discard a successful arrangement read (sections/lyrics/etc.).
            self.state.update(
                timeline=tl,
                timeline_errors=tl.errors,
            )

            # Build meter map: time-sig + tempo at every song/section start.
            # Stored in the timeline so poll-tick lookups are free.
            try:
                tl.meter_map = scan_meter_map(
                    self.osc, tl, progress=self._scan_log
                )
                entries = len(tl.meter_map) if tl.meter_map else 0
                self._scan_log(f"Meter map: {entries} entries")
                self.state.update(timeline=tl)
            except Exception:
                logger.exception("Meter map scan failed")
                self._scan_log("Meter map scan failed — continuing without it")

            # Read cue points (song jumps use cue markers, not SONGS clip positions)
            self._scan_log("Reading cue points…")
            cue_raw = self.osc.get_cue_points()
            cue_points: list[dict] = []
            if cue_raw is not None:
                cue_points = [
                    {"name": name, "time": round(time, 4)}
                    for name, time in cue_raw
                ]
                self.state.update(cue_points=cue_points)
                self._scan_log(f"Cue points: {len(cue_points)}")

            self._scan_log("Loading active setlist…")
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

            self.reload_active_setlist(broadcast=False)

            # Initial time-sig sync from the meter map (no OSC round-trip)
            if tl.meter_map:
                pos = self.osc.get_current_song_time() or 0.0
                meter = tl.meter_map.at(pos)
                self.state.update(
                    signature_numerator=meter.numerator,
                    signature_denominator=meter.denominator,
                )
            else:
                self._sync_time_signature_from_playhead()

            if not tl.is_valid:
                self.state.update(connection_status=ConnectionStatus.ERROR)
                self._scan_log("Scan finished with timeline errors")
            elif self.osc.is_connected():
                self.state.update(connection_status=ConnectionStatus.CONNECTED)
                self._scan_log("Scan complete")

            with self._lock:
                tempo = self.state.tempo
                cue_points = list(self.state.cue_points)
                mixer_tracks = list(self.state.mixer_tracks)
                timeline_errors = list(self.state.timeline_errors)
                active_project = self.state.active_project

            identity = active_project["identity"] if active_project else None
            name = active_project.get("name", "") if active_project else ""
            file_path = active_project.get("file_path", "") if active_project else ""

            if identity is None:
                project_info = self.osc.get_project_identity()
                if project_info:
                    identity, name, file_path = project_info
                    project = get_or_create_project_record(
                        identity=identity,
                        name=name,
                        file_path=file_path,
                    )
                    self.state.update(active_project=project_to_state_dict(project))
                    self._current_project_identity = identity

            if identity:
                project = save_project_cache(
                    identity=identity,
                    name=name,
                    file_path=file_path,
                    timeline=tl,
                    timeline_errors=timeline_errors,
                    tempo=tempo,
                    cue_points=cue_points,
                    mixer_tracks=mixer_tracks,
                )
                if project:
                    self.state.update(active_project=project_to_state_dict(project))
                    self._current_project_identity = identity
            self.state.update(project_scanned_at=time.time())

            if broadcast:
                self._broadcast()
        except Exception:
            logger.exception("Error during arrangement scan")
            self._scan_log("Failed to scan arrangement")
            self.state.update(
                connection_status=ConnectionStatus.ERROR,
                timeline_errors=["Failed to scan arrangement"],
            )
            if broadcast:
                self._broadcast()

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
                            tempo = self.osc.get_tempo()
                            if tempo:
                                self.state.update(tempo=tempo)
                            self._apply_project_from_osc(broadcast=True)
                            logger.info("Reconnected to Ableton Live")
                else:
                    self._poll_tick()

            except Exception:
                logger.exception("Error in engine loop tick")
                if not self.osc.is_connected():
                    self.state.update(connection_status=ConnectionStatus.DISCONNECTED)

            # Sleep to maintain target Hz
            elapsed = time.monotonic() - loop_start
            sleep_time = self._poll_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ── slow poll (1 Hz) ────────────────────────────────────────────

    def _slow_poll_loop(self) -> None:
        """Background loop for low-frequency queries (1/s): tempo, time sig, mixer mute."""
        while self._running:
            try:
                if self.state.connection_status in (
                    ConnectionStatus.CONNECTED,
                    ConnectionStatus.ERROR,
                ):
                    self._slow_poll_tick()
            except Exception:
                logger.exception("Error in slow poll tick")
            time.sleep(1.0)

    def _slow_poll_tick(self) -> None:
        """Query tempo, time signature, mixer mute, and project identity from Ableton."""
        tempo = self.osc.get_tempo()
        if tempo is not None and abs(tempo - self.state.tempo) > 0.01:
            self.state.update(tempo=tempo)
        self._sync_time_signature_from_playhead()
        self.refresh_mixer_tracks_mute()
        self._check_project_switch()

    def _apply_project_from_osc(self, *, broadcast: bool = True) -> bool:
        """Detect the open Live set and load its cached scan data."""
        project_info = self.osc.get_project_identity()
        if project_info is None:
            return False
        identity, name, file_path = project_info

        if identity == self._current_project_identity and self.state.timeline is not None:
            return True

        switched = identity != self._current_project_identity
        self._current_project_identity = identity
        project = get_or_create_project_record(
            identity=identity,
            name=name,
            file_path=file_path,
        )
        set_last_active_project(project)
        project_dict = project_to_state_dict(project)

        payload = load_project_cache(identity)
        if payload is not None:
            apply_cache_payload_to_state(self.state, payload)
            if switched:
                self._scan_log(f"Switched to project: {project.display_name}")
        else:
            clear_project_state(self.state, project=project_dict)
            if switched:
                self._scan_log(
                    f"Opened project: {project.display_name} — use Rescan to load arrangement"
                )

        self.reload_active_setlist(broadcast=False)
        if broadcast and switched:
            self._broadcast()
        return payload is not None

    def _check_project_switch(self) -> None:
        """Detect when Ableton opens a different Live set."""
        if self._scan_in_progress:
            return
        self._apply_project_from_osc(broadcast=True)

    # ── fast poll tick ────────────────────────────────────────────

    def _poll_tick(self) -> None:
        """Single tick of the poll loop.

        Only two OSC queries per tick: position + is_playing.
        Tempo and time signature are handled by the 1/s slow-poll thread.
        """
        # 1. Read transport state (2 OSC queries)
        position = self.osc.get_current_song_time()
        if position is None:
            if not self.osc.is_connected():
                self.state.update(connection_status=ConnectionStatus.DISCONNECTED)
            return

        is_playing = self._is_transport_playing()

        # 2. Resolve active events (timeline reads are lock-free)
        tl = self.state.timeline
        active_song = None
        active_song_index = None
        active_setlist_index = None
        active_section = None
        active_chord = None
        active_lyrics: list[dict] = []
        next_stop = None

        if tl is not None and tl.is_valid:
            song_evt = tl.active_song(position)
            if song_evt:
                active_song = _event_to_dict(song_evt)
                active_song_index = tl.song_index(position)

            section_evt = tl.active_section(position)
            if section_evt:
                active_section = _event_to_dict(section_evt)

            chord_evt = tl.active_chord(position)
            if chord_evt:
                active_chord = _event_to_dict(chord_evt)

            lyric_evts = tl.active_lyrics(position)
            active_lyrics = [_event_to_dict(l) for l in lyric_evts]

            stop_evt = tl.next_stop_after(position)
            if stop_evt:
                next_stop = stop_evt.start_beat

        active_setlist = self.state.active_setlist
        if active_setlist and active_song:
            active_setlist_index = self._setlist_index_for_song(
                active_song.get("name")
            )

        with self._lock:
            prev_pos = self._prev_position
            self._prev_position = position

            # Clear pending seek/cue once Ableton is actually playing
            if is_playing:
                had_pending = (
                    self._pending_position is not None
                    or self._pending_cue_name is not None
                )
                self._pending_position = None
                self._pending_cue_name = None
                if had_pending:
                    self._sync_prev_playhead(position)
                    prev_pos = position

            stop_crossed = False
            stop_setlist_index: int | None = None

            if tl is not None and tl.is_valid:
                # STOP crossing — playhead entered a CONTROL STOP clip while playing
                delta = position - prev_pos
                if is_playing and 0 < delta <= MAX_PLAY_STEP_BEATS:
                    stop_evt = tl.stop_entered(prev_pos, position)
                    if stop_evt:
                        logger.info(
                            "STOP crossing detected at beat %.2f (prev=%.2f cur=%.2f)",
                            stop_evt.start_beat,
                            prev_pos,
                            position,
                        )
                        self.osc.transport_stop()
                        is_playing = False
                        stop_crossed = True
                        song_at_stop = tl.active_song(prev_pos) or tl.active_song(
                            stop_evt.start_beat - 0.001
                        )
                        if song_at_stop:
                            stop_setlist_index = self._setlist_index_for_song(
                                song_at_stop.name
                            )
                elif is_playing and delta > MAX_PLAY_STEP_BEATS:
                    logger.debug(
                        "Playhead discontinuity (prev=%.2f cur=%.2f) — skipping STOP check",
                        prev_pos,
                        position,
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
            active_chord=active_chord,
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
