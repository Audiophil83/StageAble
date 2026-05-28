"""
AbletonOSC client — thin wrapper around python-osc for communicating with
Ableton Live via the AbletonOSC remote script.

AbletonOSC listens on UDP port 11000 and replies on port 11001.
"""

from __future__ import annotations

import logging
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
            "(older Remote Script). Using 4/4 for pre-roll. Update AbletonOSC from "
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

        timeout = self._signature_query_timeout()
        r = self.query(
            "/live/song/get/signature_numerator",
            timeout=timeout,
            warn_timeout=False,
        )
        if r is None or len(r) == 0:
            if self._signature_osc_supported is None:
                self._log_signature_unavailable()
            self._signature_osc_supported = False
            return None, None

        self._signature_osc_supported = True
        num = int(r[0])

        den_r = self.query(
            "/live/song/get/signature_denominator",
            timeout=timeout,
            warn_timeout=False,
        )
        if den_r is None or len(den_r) == 0:
            return num, None
        return num, int(den_r[0])

    def get_time_signature_at(self, beats: float) -> tuple[int | None, int | None]:
        """Return time signature at an arrangement position (seeks temporarily)."""
        saved = self.get_current_song_time()
        if saved is not None and abs(saved - beats) > 1e-6:
            self.set_current_song_time(beats)
        try:
            return self.get_time_signature()
        finally:
            if saved is not None and abs(saved - beats) > 1e-6:
                self.set_current_song_time(saved)

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

    # Arrangement clips --------------------------------------------------

    def get_arrangement_clip_names(self, track_id: int) -> list[str] | None:
        r = self.query("/live/track/get/arrangement_clips/name", track_id)
        if r is not None and len(r) > 1:
            return [str(v) for v in r[1:]]
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

        # Deliver to one-shot query queue
        with self._lock:
            q = self._reply_queues.get(address)
        if q is not None:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

        # Deliver to persistent listeners
        with self._lock:
            callbacks = list(self._listeners.get(address, []))
        for cb in callbacks:
            try:
                cb(address, data)
            except Exception:
                logger.exception("Listener callback error for %s", address)
