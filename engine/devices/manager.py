from __future__ import annotations

import logging
import os
import threading
import time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import close_old_connections

from engine.actions import ACTIONS, ActionDispatcher
from engine.models import ControlDevice, ControlMapping

from .base import InputAdapter, InputEvent, trigger_key
from .macos_hid import MacBluetoothHidAdapter
from .midi import MidiInputAdapter

logger = logging.getLogger(__name__)
LEARN_TIMEOUT = 15.0
REPEAT_GUARD_SECONDS = 0.15


class DeviceManager:
    def __init__(self, engine, adapters: list[InputAdapter] | None = None):
        self.engine = engine
        self.dispatcher = ActionDispatcher(engine)
        self._lock = threading.RLock()
        self._learn: dict | None = None
        self._learn_timer: threading.Timer | None = None
        self._pressed: set[tuple[str, str, str]] = set()
        self._last_fired: dict[tuple[str, str, str], float] = {}
        self._last_input: dict[tuple[str, str], dict] = {}
        self._discovered: dict[tuple[str, str], object] = {}
        self._external_discovered: dict[tuple[str, str], object] = {}
        self._external_status: dict[str, dict] = {}
        self._running = False
        self._monitor_thread = None
        self._monitor_stop = threading.Event()
        self._last_signature = None
        if adapters is not None:
            self.adapters = adapters
        else:
            self.adapters = [MidiInputAdapter(self.handle_input)]
            if os.environ.get("STAGEABLE_DEVICE_BROKER") != "1":
                self.adapters.append(MacBluetoothHidAdapter(self.handle_input))

    def start(self):
        if self._running:
            return
        self._running = True
        for adapter in self.adapters:
            try:
                adapter.start()
            except Exception:
                logger.exception("Device adapter %s failed to start", adapter.kind)
        self.refresh()
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True, name="device-monitor")
        self._monitor_thread.start()

    def stop(self):
        self.cancel_learn("cancelled")
        self._running = False
        self._monitor_stop.set()
        if self._monitor_thread and self._monitor_thread is not threading.current_thread():
            self._monitor_thread.join(timeout=2)
        self._monitor_thread = None
        for adapter in self.adapters:
            try:
                adapter.stop()
            except Exception:
                logger.exception("Device adapter %s failed to stop", adapter.kind)

    def refresh(self):
        discovered = {}
        for adapter in self.adapters:
            try:
                adapter.refresh()
                for item in adapter.discover():
                    discovered[(item.adapter, item.identifier)] = item
            except Exception:
                logger.exception("Device adapter %s refresh failed", adapter.kind)
        with self._lock:
            discovered.update(self._external_discovered)
        with self._lock:
            self._discovered = discovered
        close_old_connections()
        for item in discovered.values():
            device, created = ControlDevice.objects.get_or_create(
                adapter=item.adapter,
                identifier=item.identifier,
                defaults={"name": item.name},
            )
            if not created and device.name != item.name:
                device.name = item.name
                device.save(update_fields=["name", "updated_at"])
        connected_hid = {
            item.identifier
            for item in discovered.values()
            if item.adapter == "bluetooth_hid" and item.connected
        }
        capture_media = ControlDevice.objects.filter(
            adapter="bluetooth_hid", enabled=True, identifier__in=connected_hid
        ).exists()
        for adapter in self.adapters:
            configure = getattr(adapter, "set_capture_media", None)
            if configure:
                configure(capture_media)
        status_signature = tuple(
            sorted(
                [(adapter.kind, str(adapter.status())) for adapter in self.adapters]
                + [(kind, str(value)) for kind, value in self._external_status.items()]
            )
        )
        signature = (
            tuple(sorted((key, item.connected, item.error, item.name) for key, item in discovered.items())),
            status_signature,
        )
        if signature != self._last_signature:
            self._last_signature = signature
            self.broadcast("devices_changed", {"devices": self.snapshot()})
        return self.snapshot()

    def _monitor(self):
        while not self._monitor_stop.wait(3.0):
            try:
                self.refresh()
            except Exception:
                logger.exception("Device hot-plug refresh failed")

    def snapshot(self):
        found = self._discovered.copy()
        adapter_status = {a.kind: a.status() for a in self.adapters}
        adapter_status.update(self._external_status)
        result = []
        for device in ControlDevice.objects.prefetch_related("mappings").all():
            item = found.get((device.adapter, device.identifier))
            runtime_status = adapter_status.get(device.adapter, {})
            details = dict(item.details) if item else {}
            for field in ("input_monitoring", "accessibility"):
                if field in runtime_status:
                    details[field] = runtime_status[field]
            result.append({
                "id": device.id,
                "adapter": device.adapter,
                "identifier": device.identifier,
                "name": device.name,
                "enabled": device.enabled,
                "connected": bool(item and item.connected),
                "error": ((item.error or runtime_status.get("error", "")) if item else runtime_status.get("error", "Device not connected")),
                "details": details,
                "last_input": self._last_input.get((device.adapter, device.identifier)),
                "mappings": [{
                    "id": mapping.id,
                    "trigger": mapping.trigger,
                    "action": mapping.action,
                    "action_label": ACTIONS.get(mapping.action, mapping.action),
                    "enabled": mapping.enabled,
                } for mapping in device.mappings.all()],
            })
        return result

    def update_external(self, devices: list[dict], status: dict):
        from .base import DiscoveredDevice

        external = {}
        for item in devices:
            device = DiscoveredDevice(
                adapter=item["adapter"], identifier=item["identifier"],
                name=item["name"], connected=item.get("connected", True),
                error=item.get("error", ""), details=item.get("details", {}),
            )
            external[(device.adapter, device.identifier)] = device
        with self._lock:
            self._external_discovered = external
            self._external_status["bluetooth_hid"] = status
        return self.refresh()

    def start_learn(self, device_id: int, action: str):
        if action not in ACTIONS:
            raise ValueError("Unknown action")
        device = ControlDevice.objects.get(pk=device_id)
        if not device.enabled:
            raise ValueError("Enable the device before learning")
        with self._lock:
            self.cancel_learn("replaced", broadcast=False)
            self._learn = {"device_id": device.id, "adapter": device.adapter, "identifier": device.identifier, "action": action, "expires_at": time.time() + LEARN_TIMEOUT}
            self._learn_timer = threading.Timer(LEARN_TIMEOUT, lambda: self.cancel_learn("timeout"))
            self._learn_timer.daemon = True
            self._learn_timer.start()
        self.broadcast("device_learn", {"status": "listening", "device_id": device.id, "action": action, "timeout": LEARN_TIMEOUT})
        return dict(self._learn)

    def cancel_learn(self, reason="cancelled", *, broadcast=True):
        with self._lock:
            active = self._learn
            self._learn = None
            if self._learn_timer:
                self._learn_timer.cancel()
                self._learn_timer = None
        if active and broadcast:
            self.broadcast("device_learn", {"status": reason, "device_id": active["device_id"]})

    def handle_input(self, event: InputEvent):
        key = (event.adapter, event.identifier, trigger_key(event.trigger))
        self._last_input[(event.adapter, event.identifier)] = {
            "trigger": event.trigger,
            "pressed": event.pressed,
            "value": event.value,
            "timestamp": time.time(),
        }
        with self._lock:
            learn = self._learn
        if learn and event.pressed and learn["adapter"] == event.adapter and learn["identifier"] == event.identifier:
            self._complete_learn(learn, event)
            return

        is_program = event.trigger.get("type") == "program"
        if not event.pressed:
            self._pressed.discard(key)
            return
        if not is_program and key in self._pressed:
            return
        if not is_program:
            self._pressed.add(key)
        now = time.monotonic()
        if now - self._last_fired.get(key, 0) < REPEAT_GUARD_SECONDS:
            return
        self._last_fired[key] = now
        close_old_connections()
        try:
            mapping = ControlMapping.objects.select_related("device").get(
                device__adapter=event.adapter,
                device__identifier=event.identifier,
                device__enabled=True,
                enabled=True,
                trigger_key=key[2],
            )
        except ControlMapping.DoesNotExist:
            return
        self.dispatcher.dispatch(mapping.action)

    def _complete_learn(self, learn, event):
        close_old_connections()
        device = ControlDevice.objects.get(pk=learn["device_id"])
        key = trigger_key(event.trigger)
        existing = ControlMapping.objects.filter(device=device, trigger_key=key).first()
        if existing and existing.action != learn["action"]:
            self.cancel_learn("conflict", broadcast=False)
            self.broadcast("device_learn", {"status": "conflict", "device_id": device.id, "mapping_id": existing.id, "trigger": event.trigger, "existing_action": existing.action, "requested_action": learn["action"]})
            return
        mapping, _ = ControlMapping.objects.update_or_create(
            device=device,
            trigger_key=key,
            defaults={"trigger": event.trigger, "action": learn["action"], "enabled": True},
        )
        self.cancel_learn("learned", broadcast=False)
        self.broadcast("device_learn", {"status": "learned", "device_id": device.id, "mapping_id": mapping.id, "trigger": event.trigger, "action": mapping.action})
        self.broadcast("devices_changed", {"devices": self.snapshot()})

    @staticmethod
    def broadcast(event_type, data):
        try:
            layer = get_channel_layer()
            if layer:
                async_to_sync(layer.group_send)("engine", {"type": "engine.device_event", "event": event_type, "data": data})
        except Exception:
            logger.debug("Could not broadcast device event", exc_info=True)
