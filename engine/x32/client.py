"""Small bidirectional OSC client for the X32's same-socket UDP protocol."""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from queue import Empty, Queue
from typing import Any

from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_packet import OscPacket

logger = logging.getLogger(__name__)


class X32OSCClient:
    port = 10023

    def __init__(self, host: str, on_update: Callable[[str, Any], None] | None = None):
        self.host = host
        self.on_update = on_update
        self._socket: socket.socket | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._pending: dict[str, list[Queue]] = defaultdict(list)
        self._pending_lock = threading.Lock()
        self.last_received_at = 0.0

    def start(self) -> None:
        if self._running:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 0))
        sock.settimeout(0.25)
        self._socket = sock
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True, name="x32-osc")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        sock, self._socket = self._socket, None
        if sock:
            sock.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def send(self, address: str, *args: Any) -> None:
        if not self._socket:
            raise ConnectionError("X32 OSC client is not running")
        builder = OscMessageBuilder(address=address)
        for arg in args:
            builder.add_arg(arg)
        self._socket.sendto(builder.build().dgram, (self.host, self.port))

    def query(self, address: str, timeout: float = 0.8) -> Any | None:
        queue: Queue = Queue(maxsize=1)
        with self._pending_lock:
            self._pending[address].append(queue)
        try:
            self.send(address)
            try:
                return queue.get(timeout=timeout)
            except Empty:
                return None
        finally:
            with self._pending_lock:
                if queue in self._pending.get(address, []):
                    self._pending[address].remove(queue)

    def query_many(
        self,
        addresses: Iterable[str],
        *,
        timeout: float = 1.2,
        chunk_size: int = 24,
    ) -> dict[str, Any]:
        addresses = list(dict.fromkeys(addresses))
        result: dict[str, Any] = {}
        for offset in range(0, len(addresses), chunk_size):
            chunk = addresses[offset : offset + chunk_size]
            queues: dict[str, Queue] = {}
            with self._pending_lock:
                for address in chunk:
                    queue: Queue = Queue(maxsize=1)
                    queues[address] = queue
                    self._pending[address].append(queue)
            try:
                for address in chunk:
                    self.send(address)
                    time.sleep(0.002)
                deadline = time.monotonic() + timeout
                pending = set(queues)
                while pending and time.monotonic() < deadline:
                    for address in list(pending):
                        try:
                            result[address] = queues[address].get_nowait()
                            pending.remove(address)
                        except Empty:
                            continue
                    if pending:
                        time.sleep(0.005)
            finally:
                with self._pending_lock:
                    for address, queue in queues.items():
                        if queue in self._pending.get(address, []):
                            self._pending[address].remove(queue)
        return result

    def _receive_loop(self) -> None:
        while self._running and self._socket:
            try:
                data, _ = self._socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                packet = OscPacket(data)
                for timed in packet.messages:
                    message = timed.message
                    value: Any
                    if len(message.params) == 0:
                        value = None
                    elif len(message.params) == 1:
                        value = message.params[0]
                    else:
                        value = list(message.params)
                    self.last_received_at = time.monotonic()
                    self._deliver(message.address, value)
            except Exception:
                logger.debug("Ignoring malformed X32 OSC packet", exc_info=True)

    def _deliver(self, address: str, value: Any) -> None:
        with self._pending_lock:
            waiters = list(self._pending.get(address, []))
        for queue in waiters:
            try:
                queue.put_nowait(value)
            except Exception:
                pass
        if self.on_update:
            self.on_update(address, value)
