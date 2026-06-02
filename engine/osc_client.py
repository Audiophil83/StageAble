"""
AbletonOSC client — thin wrapper around python-osc for communicating with
Ableton Live via the AbletonOSC remote script.

AbletonOSC listens on UDP port 11000 and replies on port 11001.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

logger = logging.getLogger(__name__)

# Default timeout when waiting for an OSC reply (seconds).
DEFAULT_TIMEOUT = 2.0

_ARRANGEMENT_CLIPS_NAME = "/live/track/get/arrangement_clips/name"
_ARRANGEMENT_CLIPS_NAME_CHUNK = "/live/track/get/arrangement_clips/name_chunk"
_METER_AT_BEATS = "/live/song/get/meter_at_beats"
# Keep chunks small — lyric clip names can be long sentences.
ARRANGEMENT_CLIP_NAME_CHUNK_SIZE = 40
ARRANGEMENT_CLIP_BULK_TIMEOUT = 2.0
ARRANGEMENT_CLIP_CHUNK_TIMEOUT = 5.0
METER_AT_BEATS_TIMEOUT = 10.0
METER_AT_BEATS_CHUNK_SIZE = 128


def _osc_debug_enabled() -> bool:
    return os.environ.get("OSC_DEBUG", "").lower() in ("1", "true", "yes")


def _string_args_utf8_bytes(args: list[Any]) -> int:
    total = 0
    for value in args:
        if isinstance(value, str):
            total += len(value.encode("utf-8"))
        elif isinstance(value, bytes):
            total += len(value)
    return total


@dataclass
class AbletonOSCClient:
    """Bidirectional OSC client for AbletonOSC.

    Sends commands on ``send_port`` (default 11000) and listens for replies
    on ``recv_port`` (default 11001).
    """

    host: str = "127.0.0.1"
    send_port: int = 11000
    recv_port: int = 11001

    # ── internal ──────────────────────────────────────────────────────
    _client: SimpleUDPClient | None = field(default=None, init=False, repr=False)
    _server: BlockingOSCUDPServer | None = field(default=None, init=False, repr=False)
    _server_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _reply_queues: dict[str, queue.Queue] = field(default_factory=dict, init=False, repr=False)
    _listeners: dict[str, list] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _query_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _signature_osc_supported: bool | None = field(default=None, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the OSC client and reply listener."""
        if self._running:
            return
        self._signature_osc_supported = None
        self._client = SimpleUDPClient(self.host, self.send_port)
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._handle_reply)
        self._server = BlockingOSCUDPServer(
            ("0.0.0.0", self.recv_port), dispatcher
        )
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="osc-recv"
        )
        self._server_thread.start()
        self._running = True
        logger.info(
            "AbletonOSC client started  send=%s:%s  recv=0.0.0.0:%s",
            self.host,
            self.send_port,
            self.recv_port,
        )

    def stop(self) -> None:
        """Shut down the OSC listener."""
        if not self._running:
            return
        self._running = False
        if self._server:
            self._server.shutdown()
        if self._server_thread:
            self._server_thread.join(timeout=2)
        logger.info("AbletonOSC client stopped")

    # ── public API ────────────────────────────────────────────────────

    def send(self, address: str, *args: Any) -> None:
        """Fire-and-forget: send an OSC message without waiting for reply."""
        if self._client is None:
            raise RuntimeError("OSC client not started — call .start() first")
        self._client.send_message(address, list(args))

    def query(
        self,
        address: str,
        *args: Any,
        timeout: float = DEFAULT_TIMEOUT,
        warn_timeout: bool = True,
    ) -> list[Any] | None:
        """Send an OSC message and wait for the reply.

        Returns the reply arguments as a list, or ``None`` on timeout.

        Queries are serialized so the poll loop and scan/rescan paths cannot
        steal each other's replies for the same OSC address.
        """
        with self._query_lock:
            reply_q: queue.Queue = queue.Queue(maxsize=1)
            with self._lock:
                self._reply_queues[address] = reply_q

            self.send(address, *args)

            try:
                return reply_q.get(timeout=timeout)
            except queue.Empty:
                if warn_timeout:
                    logger.warning("OSC query timed out: %s %s", address, args)
                return None
            finally:
                with self._lock:
                    self._reply_queues.pop(address, None)

    def subscribe(self, address: str, callback) -> None:
        """Register a callback for a specific OSC address (listener mode)."""
        with self._lock:
            self._listeners.setdefault(address, []).append(callback)

    def unsubscribe(self, address: str, callback=None) -> None:
        """Remove listener(s) for an address."""
        with self._lock:
            if callback is None:
                self._listeners.pop(address, None)
            else:
                cbs = self._listeners.get(address, [])
                self._listeners[address] = [c for c in cbs if c is not callback]

    # ── convenience methods ───────────────────────────────────────────

    def is_connected(self) -> bool:
        """Quick connectivity test — query Ableton tempo."""
        try:
            result = self.query("/live/song/get/tempo", timeout=1.0)
            return result is not None
        except Exception:
            return False

    # Transport ----------------------------------------------------------

    def transport_play(self) -> None:
        self.send("/live/song/start_playing")

    def transport_stop(self) -> None:
        self.send("/live/song/stop_playing")

    def get_is_playing(self) -> bool | None:
        r = self.query("/live/song/get/is_playing")
        if r is not None and len(r) > 0:
            return bool(r[0])
        return None

    def get_current_song_time(self) -> float | None:
        r = self.query("/live/song/get/current_song_time")
        if r is not None and len(r) > 0:
            return float(r[0])
        return None

    def set_current_song_time(self, beats: float) -> None:
        current = self.get_current_song_time()
        if current is not None:
            delta = float(beats) - current
            self.jump_by(delta)
        else:
            self.send("/live/song/set/current_song_time", float(beats))

    def jump_by(self, beats: float) -> None:
        self.send("/live/song/jump_by", float(beats))

    # Cue points ---------------------------------------------------------

    def get_cue_points(self) -> list[tuple[str, float]] | None:
        """Query all cue points. Returns list of (name, time) pairs."""
        r = self.query("/live/song/get/cue_points")
        if r is None:
            return None
        # Response is a flat alternating list: [name1, time1, name2, time2, ...]
        result: list[tuple[str, float]] = []
        for i in range(0, len(r), 2):
            if i + 1 < len(r):
                result.append((str(r[i]), float(r[i + 1])))
        return result

    def cue_point_jump(self, name_or_index: str | int) -> None:
        """Jump to a cue point by name (str) or index (int)."""
        self.send("/live/song/cue_point/jump", name_or_index)

    def get_tempo(self) -> float | None:
        r = self.query("/live/song/get/tempo")
        if r is not None and len(r) > 0:
            return float(r[0])
        return None

    def _log_signature_unavailable(self) -> None:
        logger.info(
            "AbletonOSC does not expose /live/song/get/signature_* on this install "
            "(older Remote Script). Defaulting to 4/4. Update AbletonOSC from "
            "https://github.com/ideoforms/AbletonOSC"
        )

    def _signature_query_timeout(self) -> float:
        """Fast probe while detecting support; full timeout once confirmed."""
        return 0.5 if self._signature_osc_supported is None else DEFAULT_TIMEOUT

    def get_time_signature(self) -> tuple[int | None, int | None]:
        """Return (numerator, denominator) at the current playhead.

        Live's ``signature_*`` properties follow the playhead — not a single
        project-wide value when the arrangement has meter changes.

        Older AbletonOSC builds do not register these endpoints; we detect that
        once and fall back to engine defaults (4/4) without repeated warnings.
        """
        if self._signature_osc_supported is False:
            return None, None

        r = self.query("/live/song/get/signature_numerator")
        if r is None or len(r) == 0:
            if self._signature_osc_supported is None:
                self._log_signature_unavailable()
            self._signature_osc_supported = False
            return None, None

        self._signature_osc_supported = True
        num = int(r[0])

        den_r = self.query("/live/song/get/signature_denominator")
        if den_r is None or len(den_r) == 0:
            return num, None
        return num, int(den_r[0])

    def _parse_meter_at_beats_reply(
        self, r: list[Any], *, expected_count: int
    ) -> list[tuple[float, int, int, float]] | None:
        """Parse one ``meter_at_beats`` OSC reply."""
        if len(r) < 2:
            return None

        try:
            saved_ok = int(r[0])
            count = int(r[1])
        except (TypeError, ValueError):
            logger.warning("meter_at_beats reply has invalid header: %r", r[:2])
            return None

        if saved_ok == 0:
            return None
        if count == 0:
            return None if expected_count > 0 else []
        if count != expected_count:
            logger.warning(
                "meter_at_beats count mismatch: expected %d, got %d",
                expected_count,
                count,
            )
            return None

        expected_len = 2 + count * 4
        if len(r) < expected_len:
            logger.warning(
                "meter_at_beats reply truncated: expected %d args, got %d",
                expected_len,
                len(r),
            )
            return None

        samples: list[tuple[float, int, int, float]] = []
        idx = 2
        for _ in range(count):
            try:
                beat = float(r[idx])
                num = int(r[idx + 1])
                den = int(r[idx + 2])
                tempo = float(r[idx + 3])
            except (IndexError, TypeError, ValueError):
                logger.warning(
                    "meter_at_beats reply malformed at sample %d",
                    len(samples),
                )
                return None
            samples.append((beat, num, den, tempo))
            idx += 4
        return samples

    def get_meter_at_beats(
        self, beats: list[float]
    ) -> list[tuple[float, int, int, float]] | None:
        """Sample tempo and time signature at many beats in one OSC round trip.

        Requires Remoteable's AbletonOSC ``song.py`` patch. Returns ``None`` if
        the endpoint is missing or the reply is malformed.
        """
        if not beats:
            return []

        saved_pos = self.get_current_song_time()
        try:
            samples: list[tuple[float, int, int, float]] = []
            for offset in range(0, len(beats), METER_AT_BEATS_CHUNK_SIZE):
                chunk = beats[offset : offset + METER_AT_BEATS_CHUNK_SIZE]
                r = self.query(
                    _METER_AT_BEATS,
                    *[float(b) for b in chunk],
                    timeout=METER_AT_BEATS_TIMEOUT,
                    warn_timeout=False,
                )
                parsed = self._parse_meter_at_beats_reply(
                    r or [], expected_count=len(chunk)
                )
                if parsed is None:
                    return None
                samples.extend(parsed)
            return samples
        finally:
            if saved_pos is not None:
                self.set_current_song_time(saved_pos)

    def get_beat_time(self) -> float | None:
        """Alias for get_current_song_time (position in beats)."""
        return self.get_current_song_time()

    # Tracks -------------------------------------------------------------

    def get_num_tracks(self) -> int | None:
        r = self.query("/live/song/get/num_tracks")
        if r is not None and len(r) > 0:
            return int(r[0])
        return None

    def get_track_name(self, track_id: int) -> str | None:
        r = self.query("/live/track/get/name", track_id)
        if r is not None and len(r) >= 2:
            return str(r[1])
        return None

    def get_track_mute(self, track_id: int) -> bool | None:
        r = self.query("/live/track/get/mute", track_id)
        if r is not None and len(r) >= 2:
            return bool(int(r[1]))
        return None

    def set_track_mute(self, track_id: int, muted: bool) -> None:
        self.send("/live/track/set/mute", track_id, 1 if muted else 0)

    # Arrangement clips --------------------------------------------------

    def _get_arrangement_clip_names_chunked(self, track_id: int) -> list[str] | None:
        """Read arrangement clip names in slices via Remoteable's AbletonOSC patch."""
        names: list[str] = []
        offset = 0
        total: int | None = None

        while total is None or offset < total:
            r = self.query(
                _ARRANGEMENT_CLIPS_NAME_CHUNK,
                track_id,
                offset,
                ARRANGEMENT_CLIP_NAME_CHUNK_SIZE,
                timeout=ARRANGEMENT_CLIP_CHUNK_TIMEOUT,
                warn_timeout=False,
            )
            if r is None or len(r) < 3:
                if offset == 0:
                    return None
                logger.warning(
                    "Chunked arrangement clip name read failed at offset %d "
                    "for track %d",
                    offset,
                    track_id,
                )
                return None

            if int(r[0]) != track_id:
                logger.warning(
                    "Chunk reply track_id mismatch: expected %d got %s",
                    track_id,
                    r[0],
                )
                return None

            reply_offset = int(r[1])
            reply_total = int(r[2])
            if total is None:
                total = reply_total
            elif reply_total != total:
                logger.warning(
                    "Chunk reply total_count mismatch on track %d", track_id
                )
                return None
            if reply_offset != offset:
                logger.warning(
                    "Chunk reply offset mismatch on track %d: expected %d got %d",
                    track_id,
                    offset,
                    reply_offset,
                )
                return None

            chunk = [str(v) for v in r[3:]]
            names.extend(chunk)
            offset += len(chunk)
            if not chunk:
                break

        if total is not None and len(names) != total:
            logger.warning(
                "Chunked name count mismatch on track %d: got %d expected %d",
                track_id,
                len(names),
                total,
            )
            return None
        return names

    def get_arrangement_clip_names(self, track_id: int) -> list[str] | None:
        r = self.query(
            _ARRANGEMENT_CLIPS_NAME,
            track_id,
            timeout=ARRANGEMENT_CLIP_BULK_TIMEOUT,
            warn_timeout=False,
        )
        if r is not None and len(r) > 1:
            return [str(v) for v in r[1:]]

        names = self._get_arrangement_clip_names_chunked(track_id)
        if names is not None:
            if names:
                logger.info(
                    "Read %d arrangement clip names via chunked API for track %d",
                    len(names),
                    track_id,
                )
            return names

        logger.warning(
            "Could not read arrangement clip names for track %d "
            "(bulk timed out; install Remoteable AbletonOSC patch — "
            "python scripts/install_abletonosc_patch.py)",
            track_id,
        )
        return None

    def get_arrangement_clip_start_times(self, track_id: int) -> list[float] | None:
        r = self.query("/live/track/get/arrangement_clips/start_time", track_id)
        if r is not None and len(r) > 1:
            return [float(v) for v in r[1:]]
        return None

    def get_arrangement_clip_lengths(self, track_id: int) -> list[float] | None:
        r = self.query("/live/track/get/arrangement_clips/length", track_id)
        if r is not None and len(r) > 1:
            return [float(v) for v in r[1:]]
        return None

    # ── internal ──────────────────────────────────────────────────────

    def _handle_reply(self, address: str, *args: Any) -> None:
        """Dispatch incoming OSC messages to queues or listener callbacks."""
        data = list(args)

        if address == _ARRANGEMENT_CLIPS_NAME and (
            _osc_debug_enabled() or logger.isEnabledFor(logging.DEBUG)
        ):
            track_id = data[0] if data else "?"
            logger.debug(
                "OSC recv %s track_id=%s args=%d string_utf8_bytes=%d",
                address,
                track_id,
                len(data),
                _string_args_utf8_bytes(data),
            )

        # Deliver to one-shot query queue
        with self._lock:
            q = self._reply_queues.get(address)
        if q is not None:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass
        elif address == _ARRANGEMENT_CLIPS_NAME:
            track_id = data[0] if data else "?"
            logger.warning(
                "Late OSC reply (no active query): %s track_id=%s args=%d",
                address,
                track_id,
                len(data),
            )

        # Deliver to persistent listeners
        with self._lock:
            callbacks = list(self._listeners.get(address, []))
        for cb in callbacks:
            try:
                cb(address, data)
            except Exception:
                logger.exception("Listener callback error for %s", address)
