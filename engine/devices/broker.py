"""macOS input broker running in the user-authorized StageAble UI process."""

from __future__ import annotations

import json
import logging
import threading
import urllib.request

from .base import InputEvent
from .macos_hid import MacBluetoothHidAdapter

logger = logging.getLogger(__name__)


class MacDeviceBroker:
    def __init__(self, port: int):
        self.base_url = f"http://127.0.0.1:{port}/api/devices"
        self.adapter = MacBluetoothHidAdapter(self._input)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._request_permissions()
        self.adapter.start()
        self._thread = threading.Thread(target=self._monitor, daemon=True, name="device-broker")
        self._thread.start()

    @staticmethod
    def _request_permissions():
        try:
            import Quartz

            if not Quartz.CGPreflightListenEventAccess():
                Quartz.CGRequestListenEventAccess()
            if not Quartz.CGPreflightPostEventAccess():
                Quartz.CGRequestPostEventAccess()
        except Exception:
            logger.debug("Could not request controller permissions", exc_info=True)

    def stop(self):
        self._stop.set()
        self.adapter.stop()
        if self._thread:
            self._thread.join(timeout=2)

    def _post(self, endpoint: str, payload: dict):
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint}/",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2):
                pass
        except Exception:
            logger.debug("Device broker could not reach server", exc_info=True)

    def _input(self, event: InputEvent):
        self._post("broker-input", {
            "adapter": event.adapter,
            "identifier": event.identifier,
            "trigger": event.trigger,
            "pressed": event.pressed,
            "value": event.value,
        })

    def _monitor(self):
        while not self._stop.is_set():
            try:
                self.adapter.refresh()
                devices = self.adapter.discover()
                self.adapter.set_capture_media(bool(devices))
                self._post("broker-state", {
                    "devices": [{
                        "adapter": item.adapter,
                        "identifier": item.identifier,
                        "name": item.name,
                        "connected": item.connected,
                        "error": item.error,
                        "details": item.details,
                    } for item in devices],
                    "status": self.adapter.status(),
                })
            except Exception:
                logger.exception("Device broker refresh failed")
            self._stop.wait(3.0)
