from __future__ import annotations

import logging
import threading

from .base import DiscoveredDevice, InputAdapter, InputEvent

logger = logging.getLogger(__name__)


def normalize_midi(message) -> tuple[dict, bool, int | None] | None:
    kind = getattr(message, "type", "")
    channel = int(getattr(message, "channel", 0))
    if kind in ("note_on", "note_off"):
        velocity = int(getattr(message, "velocity", 0))
        pressed = kind == "note_on" and velocity > 0
        return ({"type": "note", "channel": channel, "note": int(message.note)}, pressed, velocity)
    if kind == "control_change":
        value = int(message.value)
        return ({"type": "cc", "channel": channel, "control": int(message.control)}, value >= 64, value)
    if kind == "program_change":
        return ({"type": "program", "channel": channel, "program": int(message.program)}, True, int(message.program))
    return None


class MidiInputAdapter(InputAdapter):
    kind = "midi"

    def __init__(self, callback):
        super().__init__(callback)
        self._lock = threading.RLock()
        self._ports: dict[str, object] = {}
        self._error = ""
        try:
            import mido

            self._mido = mido
        except Exception as exc:
            self._mido = None
            self._error = f"MIDI support unavailable: {exc}"

    @staticmethod
    def _identifier(name: str, occurrence: int) -> str:
        return f"{name}#{occurrence}"

    def _names(self) -> list[tuple[str, str]]:
        if self._mido is None:
            return []
        counts: dict[str, int] = {}
        result = []
        try:
            for name in self._mido.get_input_names():
                counts[name] = counts.get(name, 0) + 1
                result.append((self._identifier(name, counts[name]), name))
            self._error = ""
        except Exception as exc:
            self._error = str(exc)
            logger.exception("Could not enumerate MIDI inputs")
        return result

    def discover(self):
        return [DiscoveredDevice(self.kind, ident, name) for ident, name in self._names()]

    def start(self):
        self.refresh()

    def refresh(self):
        if self._mido is None:
            return
        available = dict(self._names())
        with self._lock:
            for ident in list(self._ports):
                if ident not in available:
                    try:
                        self._ports.pop(ident).close()
                    except Exception:
                        pass
            for ident, name in available.items():
                if ident in self._ports:
                    continue
                try:
                    self._ports[ident] = self._mido.open_input(
                        name, callback=lambda msg, i=ident: self._message(i, msg)
                    )
                except Exception as exc:
                    self._error = f"Could not open {name}: {exc}"
                    logger.exception("Could not open MIDI input %s", name)

    def _message(self, identifier, message):
        normalized = normalize_midi(message)
        if normalized:
            trigger, pressed, value = normalized
            self.callback(InputEvent(self.kind, identifier, trigger, pressed, value))

    def stop(self):
        with self._lock:
            for port in self._ports.values():
                try:
                    port.close()
                except Exception:
                    pass
            self._ports.clear()

    def status(self):
        return {"available": self._mido is not None, "error": self._error}
