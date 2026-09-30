from __future__ import annotations

import logging
import subprocess
import sys
import threading
import ctypes

from .base import DiscoveredDevice, InputAdapter, InputEvent

logger = logging.getLogger(__name__)
BLUETOOTH_BUS = 2


def normalize_hid_report(data: list[int], active: set[tuple[int, int]]):
    """Decode common report-ID keyboard and consumer-control HID reports."""
    if not data:
        return [], active
    report_id = int(data[0])
    if report_id == 1:  # Keyboard/Keypad page; array of key usages.
        current = {(0x07, int(code)) for code in data[1:] if code}
    elif report_id == 2:  # Consumer page; array of 16-bit usages.
        payload = data[1:]
        current = {
            (0x0C, int.from_bytes(bytes(payload[i : i + 2]), "little"))
            for i in range(0, len(payload) - 1, 2)
            if any(payload[i : i + 2])
        }
    else:
        # Voice/battery/vendor reports are not controller buttons.
        current = set()
    events = [(page, usage, True) for page, usage in current - active]
    events += [(page, usage, False) for page, usage in active - current]
    return events, current


class MacBluetoothHidAdapter(InputAdapter):
    """Read Bluetooth HID reports using hidapi (IOKit on macOS)."""

    kind = "bluetooth_hid"

    def __init__(self, callback):
        super().__init__(callback)
        self._available = sys.platform == "darwin"
        self._discovery_error = "" if self._available else "Bluetooth HID is supported on macOS only"
        self._read_errors: dict[str, str] = {}
        self._suppression_error = ""
        self._hid = None
        self._workers: dict[str, tuple[threading.Event, threading.Thread]] = {}
        self._descriptions: dict[str, dict] = {}
        self._capture_media = False
        self._media_thread = None
        self._media_run_loop = None
        if self._available:
            try:
                import hid
                self._hid = hid
            except Exception as exc:
                self._discovery_error = f"Bluetooth HID support unavailable: {exc}"

    def _allow_shared_open(self):
        """Keyboard-class devices cannot be seized by an unprivileged macOS app."""
        try:
            library = ctypes.CDLL(self._hid.__file__)
            setter = library.hid_darwin_set_open_exclusive
            setter.argtypes = [ctypes.c_int]
            setter.restype = None
            setter(0)
        except Exception as exc:
            self._discovery_error = f"Could not configure shared HID access: {exc}"

    @staticmethod
    def _text(value):
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return str(value or "")

    def _enumerate(self):
        if self._hid is None:
            return {}
        found = {}
        try:
            # enumerate() initializes hidapi; configure subsequent opens as
            # non-exclusive so keyboard-class remotes do not require root.
            entries = self._hid.enumerate()
            self._allow_shared_open()
            for item in entries:
                path_text = self._text(item.get("path"))
                bus = item.get("bus_type")
                if bus != BLUETOOTH_BUS and "bluetooth" not in path_text.lower():
                    continue
                serial = self._text(item.get("serial_number"))
                identifier = serial or f"{int(item.get('vendor_id') or 0):04x}:{int(item.get('product_id') or 0):04x}:{self._text(item.get('product_string'))}"
                if not identifier:
                    continue
                description = {
                    "identifier": identifier,
                    "name": self._text(item.get("product_string")) or "Bluetooth HID",
                    "path": item.get("path"),
                    "usage_page": int(item.get("usage_page") or 0x0C),
                    "usage": int(item.get("usage") or 0),
                    "vendor_id": int(item.get("vendor_id") or 0),
                    "product_id": int(item.get("product_id") or 0),
                }
                # hidapi reports each top-level collection separately but uses
                # one macOS path. Open that path once and decode report IDs.
                found.setdefault(path_text, description)
            if not self._discovery_error.startswith("Could not configure"):
                self._discovery_error = ""
        except Exception as exc:
            self._discovery_error = f"Bluetooth HID discovery unavailable: {exc}"
        return found

    def discover(self):
        self._descriptions = self._enumerate()
        devices = {}
        for item in self._descriptions.values():
            devices[item["identifier"]] = DiscoveredDevice(self.kind, item["identifier"], item["name"], details={"vendor_id": item["vendor_id"], "product_id": item["product_id"]})
        return list(devices.values())

    def start(self):
        self.refresh()

    def refresh(self):
        descriptions = self._enumerate()
        for path in list(self._workers):
            if path not in descriptions:
                stop, thread = self._workers.pop(path)
                stop.set()
                thread.join(timeout=1)
        for path, item in descriptions.items():
            if path in self._workers:
                if self._workers[path][1].is_alive():
                    continue
                self._workers.pop(path)
            stop = threading.Event()
            thread = threading.Thread(target=self._read, args=(item, stop), daemon=True, name="bluetooth-hid-input")
            self._workers[path] = (stop, thread)
            thread.start()
        self._descriptions = descriptions

    def _read(self, item, stop):
        active: set[tuple[int, int]] = set()
        device = None
        try:
            device = self._hid.device()
            device.open_path(item["path"])
            device.set_nonblocking(True)
            self._read_errors.pop(item["identifier"], None)
            while not stop.wait(0.01):
                data = device.read(64)
                if not data:
                    continue
                events, active = normalize_hid_report(data, active)
                for page, usage, pressed in events:
                    self.callback(InputEvent(self.kind, item["identifier"], {"type": "hid", "usage_page": page, "usage": usage}, pressed, 1 if pressed else 0))
        except Exception as exc:
            self._read_errors[item["identifier"]] = (
                f"Cannot read {item['name']}. Allow StageAble in System Settings → "
                f"Privacy & Security → Input Monitoring, then restart StageAble. ({exc})"
            )
            logger.warning("Bluetooth HID read failed for %s: %s", item["name"], exc)
        finally:
            if device:
                try:
                    device.close()
                except Exception:
                    pass

    def stop(self):
        for stop, _thread in self._workers.values():
            stop.set()
        for _stop, thread in self._workers.values():
            thread.join(timeout=1)
        self._workers.clear()
        if self._media_run_loop is not None:
            try:
                import Quartz
                Quartz.CFRunLoopStop(self._media_run_loop)
            except Exception:
                pass
        self._media_thread = None

    def set_capture_media(self, enabled: bool):
        self._capture_media = bool(enabled)
        if self._media_thread is not None and not self._media_thread.is_alive():
            self._media_thread = None
        if enabled and self._media_thread is None and sys.platform == "darwin":
            self._media_thread = threading.Thread(target=self._run_media_suppression, daemon=True, name="media-key-capture")
            self._media_thread.start()

    def _run_media_suppression(self):
        try:
            import AppKit
            import Quartz

            media_usages = {
                16: 0xCD,  # play/pause
                17: 0xB5,  # next
                18: 0xB6,  # previous
                19: 0xB3,  # fast forward
                20: 0xB4,  # rewind
            }
            def receive(_proxy, event_type, event, _refcon):
                if not self._capture_media:
                    return event
                native = AppKit.NSEvent.eventWithCGEvent_(event)
                if native is not None and native.subtype() == 8:
                    key_code = (int(native.data1()) & 0xFFFF0000) >> 16
                    usage = media_usages.get(key_code)
                    if usage is not None:
                        return None
                return event

            event_type = getattr(Quartz, "kCGEventSystemDefined", 14)
            mask = Quartz.CGEventMaskBit(event_type)
            tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionDefault,
                mask,
                receive,
                None,
            )
            if tap is None:
                self._suppression_error = (
                    "Accessibility permission is required to prevent mapped media keys "
                    "from also controlling Apple Music."
                )
                return
            source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            self._media_run_loop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(self._media_run_loop, source, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(tap, True)
            self._suppression_error = ""
            Quartz.CFRunLoopRun()
        except Exception as exc:
            self._suppression_error = f"Media-key capture unavailable: {exc}"
            logger.warning("Media-key suppression failed: %s", exc)

    def status(self):
        errors = [self._discovery_error, *self._read_errors.values(), self._suppression_error]
        result = {"available": self._hid is not None, "error": " ".join(e for e in errors if e)}
        if sys.platform == "darwin":
            try:
                import Quartz

                result["input_monitoring"] = bool(Quartz.CGPreflightListenEventAccess())
                result["accessibility"] = bool(Quartz.CGPreflightPostEventAccess())
            except Exception:
                pass
        return result

    @staticmethod
    def open_pairing():
        if sys.platform != "darwin":
            raise RuntimeError("Bluetooth pairing is supported on macOS only")
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.Bluetooth-Settings.extension"])

    @staticmethod
    def open_permission(kind: str):
        panes = {
            "input": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
            "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        }
        if sys.platform != "darwin" or kind not in panes:
            raise RuntimeError("This permission is available on macOS only")
        # Register and request access from the actual Daphne worker process.
        # Merely opening System Settings does not reliably add a background
        # helper to the TCC permission lists.
        try:
            import Quartz

            if kind == "input":
                Quartz.CGRequestListenEventAccess()
            else:
                Quartz.CGRequestPostEventAccess()
        except Exception as exc:
            logger.warning("Could not request %s permission: %s", kind, exc)
        subprocess.Popen(["open", panes[kind]])
