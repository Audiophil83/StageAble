"""X32 connection, state capture, differences, operations, and keyword execution."""

from __future__ import annotations

import logging
import struct
import threading
import time
from typing import Any

from django.db import close_old_connections, transaction

from .client import X32OSCClient
from .parameters import (
    BY_ADDRESS,
    BY_KEY,
    CHANNEL_NAME_ADDRESSES,
    PARAMETERS,
    coverage,
    display_value,
    normalize_value,
    raw_from_display,
    user_value,
    values_equal,
)

logger = logging.getLogger(__name__)


class X32Error(RuntimeError):
    pass


class X32Service:
    def __init__(self):
        self._lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._client: X32OSCClient | None = None
        self._host = ""
        self._enabled = False
        self._online = False
        self._model = ""
        self._firmware = ""
        self._live: dict[str, int | float | str] = {}
        self._headamps = {}
        self._phantom = {}
        self._meters = [0.0] * 32
        self._names = [f"CH {channel:02d}" for channel in range(1, 33)]
        self._thread: threading.Thread | None = None
        self._running = False

    def configure(self, enabled: bool, host: str) -> None:
        enabled = bool(enabled and host.strip())
        host = host.strip()
        with self._lock:
            unchanged = enabled == self._enabled and host == self._host
        if unchanged:
            return
        self.stop()
        with self._lock:
            self._enabled = enabled
            self._host = host
        if enabled:
            self.start()

    def configure_from_settings(self) -> None:
        from ..config import get_app_settings_model

        settings = get_app_settings_model()
        self.configure(settings.x32_enabled, settings.x32_host)

    def start(self) -> None:
        with self._lock:
            if self._running or not self._enabled or not self._host:
                return
            self._client = X32OSCClient(self._host, self._on_update)
            self._client.start()
            self._running = True
            self._thread = threading.Thread(
                target=self._maintenance_loop, daemon=True, name="x32-maintenance"
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            client, self._client = self._client, None
            self._online = False
            self._live = {}
            self._headamps = {}
            self._phantom = {}
            self._meters = [0.0] * 32
            self._names = [f"CH {channel:02d}" for channel in range(1, 33)]
        if client:
            client.stop()
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "host": self._host,
                "online": self._online,
                "model": self._model,
                "firmware": self._firmware,
                "coverage": coverage(),
            }

    def test_connection(self) -> dict[str, Any]:
        self._require_enabled()
        client = self._require_client()
        reply = client.query("/info", timeout=1.5)
        if not isinstance(reply, list) or len(reply) < 4:
            raise X32Error("No valid /info response from the X32")
        with self._lock:
            self._online = True
            self._model = str(reply[2])
            self._firmware = str(reply[3])
        return self.status()

    def capture_all(self) -> dict[str, int | float | str]:
        self._require_online()
        client = self._require_client()
        with self._io_lock:
            replies = client.query_many(
                [parameter.address for parameter in PARAMETERS]
                + list(CHANNEL_NAME_ADDRESSES)
            )
        captured: dict[str, int | float | str] = {}
        for parameter in PARAMETERS:
            if parameter.address in replies:
                captured[parameter.key] = normalize_value(
                    parameter, replies[parameter.address]
                )
        missing = [parameter.key for parameter in PARAMETERS if parameter.key not in captured]
        if missing:
            preview = ", ".join(missing[:8])
            suffix = "…" if len(missing) > 8 else ""
            raise X32Error(
                f"Incomplete X32 capture: {len(missing)} supported settings did not reply "
                f"({preview}{suffix})"
            )
        with self._lock:
            self._live.update(captured)
            for address, channel in CHANNEL_NAME_ADDRESSES.items():
                name = replies.get(address)
                if isinstance(name, str):
                    self._names[channel - 1] = name or f"CH {channel:02d}"
        self.refresh_headamps()
        return captured

    def initialize_baseline(self, project_id: int) -> dict[str, Any]:
        values = self.capture_all()
        self._replace_baseline(project_id, values)
        return self.control_state(project_id)

    def control_state(self, project_id: int) -> dict[str, Any]:
        from ..models import X32CaptureState, X32Operation, X32Snapshot

        close_old_connections()
        try:
            capture = X32CaptureState.objects.filter(project_id=project_id).first()
            baseline = capture.baseline if capture else {}
            with self._lock:
                live = dict(self._live)
            changes = []
            for key, before in baseline.items():
                if key not in live or key not in BY_KEY:
                    continue
                after = live[key]
                if values_equal(before, after):
                    continue
                parameter = BY_KEY[key]
                changes.append(self._change_row(parameter, before, after))
            operations = [self._operation_row(obj) for obj in X32Operation.objects.filter(project_id=project_id)]
            snapshots = [self._snapshot_row(obj) for obj in X32Snapshot.objects.filter(project_id=project_id)]
            return {
                "baseline_ready": bool(baseline),
                "baseline_at": capture.captured_at.isoformat() if capture else None,
                "changes": changes,
                "operations": operations,
                "snapshots": snapshots,
            }
        finally:
            close_old_connections()

    def mixer_state(self) -> dict[str, Any]:
        with self._lock:
            live = dict(self._live)
            meters = list(self._meters)
            names = list(self._names)
        channels = []
        for channel in range(1, 33):
            values: dict[str, Any] = {}
            for key in ("level", "solo", "mute", "pan", "gain", "polarity"):
                parameter = BY_KEY[f"ch.{channel}.{key}"]
                raw = live.get(parameter.key)
                values[key] = user_value(parameter, raw) if raw is not None else None
            pair = channel if channel % 2 else channel - 1
            values["link"] = bool(live[f"link.{pair}"]) if f"link.{pair}" in live else None
            with self._lock:
                headamp = self._headamps.get(channel)
                values["phantom"] = self._phantom.get(headamp)
                values["headamp"] = headamp
            values["sends"] = [
                user_value(BY_KEY[f"ch.{channel}.send.{bus}"], live[f"ch.{channel}.send.{bus}"])
                if f"ch.{channel}.send.{bus}" in live else None
                for bus in range(1, 17)
            ]
            channels.append({
                "channel": channel,
                "name": names[channel - 1],
                "meter": meters[channel - 1],
                **values,
            })
        returns = []
        for channel in range(1, 9):
            values = {p.key.split(".", 2)[2]: user_value(p, live[p.key]) if p.key in live else None
                      for p in PARAMETERS if p.key.startswith(f"fxrtn.{channel}.")}
            returns.append({"channel": channel, **values})
        return {"status": self.status(), "channels": channels, "fx_returns": returns}

    def refresh_headamps(self):
        client = self._require_client()
        addresses = {f"/-ha/{ch - 1:02d}/index": ch for ch in range(1, 33)}
        replies = client.query_many(addresses)
        mapping = {ch: replies.get(address) for address, ch in addresses.items()}
        mapping = {ch: index for ch, index in mapping.items() if type(index) is int and 0 <= index < 128}
        states = client.query_many([f"/headamp/{index:03d}/phantom" for index in set(mapping.values())])
        with self._lock:
            self._headamps = mapping
            self._phantom = {index: bool(states[f"/headamp/{index:03d}/phantom"])
                             for index in mapping.values() if f"/headamp/{index:03d}/phantom" in states}

    def set_phantom(self, channel, value):
        self._require_online()
        if type(channel) is not int or not 1 <= channel <= 32 or not isinstance(value, bool):
            raise X32Error("Invalid phantom power request")
        with self._io_lock:
            client = self._require_client()
            index = client.query(f"/-ha/{channel - 1:02d}/index")
            if type(index) is not int or not 0 <= index < 128:
                raise X32Error("This channel has no available physical headamp")
            client.send(f"/headamp/{index:03d}/phantom", int(value))
            with self._lock:
                self._headamps[channel] = index
                self._phantom[index] = value
        return {"channel": channel, "phantom": value}


    def set_parameter(self, key: str, value: Any) -> dict[str, Any]:
        self._require_online()
        parameter = BY_KEY.get(key)
        if not parameter:
            raise X32Error("Unsupported X32 parameter")
        try:
            raw = raw_from_display(parameter, value)
        except (TypeError, ValueError) as exc:
            raise X32Error(str(exc)) from exc
        self._require_client().send(parameter.address, raw)
        with self._lock:
            self._live[key] = normalize_value(parameter, raw)
            if parameter.group == "name":
                self._names[parameter.channel - 1] = raw or f"CH {parameter.channel:02d}"
        return {"key": key, "value": user_value(parameter, raw)}

    def save_snapshot(self, project_id: int, name: str, keyword: str) -> dict[str, Any]:
        from ..models import X32Snapshot

        name, keyword = self._clean_names(name, keyword)
        values = self.capture_all()
        self._validate_keywords(project_id, snapshot_keyword=keyword)
        with transaction.atomic():
            snapshot = X32Snapshot.objects.create(
                project_id=project_id,
                name=name,
                keyword=keyword,
                values=values,
                coverage=coverage(),
            )
            self._replace_baseline(project_id, values)
        return self._snapshot_row(snapshot)

    def save_operation(
        self,
        project_id: int,
        name: str,
        apply_keyword: str,
        rollback_keyword: str,
        selected_keys: list[str],
    ) -> dict[str, Any]:
        from ..models import X32CaptureState, X32Operation

        name = name.strip()
        apply_keyword = apply_keyword.strip()
        rollback_keyword = rollback_keyword.strip()
        if not name:
            raise X32Error("Operation name is required")
        if not selected_keys:
            raise X32Error("Select at least one change")
        self._validate_keywords(
            project_id,
            operation_keywords=[apply_keyword, rollback_keyword],
        )
        current = self.capture_all()
        capture = X32CaptureState.objects.filter(project_id=project_id).first()
        if not capture or not capture.baseline:
            raise X32Error("Create a recording baseline first")
        selected = list(dict.fromkeys(selected_keys))
        changes = []
        for key in selected:
            if key not in BY_KEY or key not in capture.baseline or key not in current:
                raise X32Error(f"Cannot save unavailable change: {key}")
            before, after = capture.baseline[key], current[key]
            if values_equal(before, after):
                raise X32Error(f"Selected setting has not changed: {key}")
            changes.append({"key": key, "before": before, "after": after})
        with transaction.atomic():
            operation = X32Operation.objects.create(
                project_id=project_id,
                name=name,
                apply_keyword=apply_keyword,
                rollback_keyword=rollback_keyword,
                changes=changes,
            )
            self._replace_baseline(project_id, current)
        return self._operation_row(operation)

    def execute_operation(self, operation, *, rollback: bool = False) -> dict[str, Any]:
        targets = {
            change["key"]: change["before" if rollback else "after"]
            for change in operation.changes
        }
        return self._execute_values(targets)

    def restore_snapshot(self, snapshot) -> dict[str, Any]:
        if (len(snapshot.values) != snapshot.coverage.get("parameters", len(PARAMETERS))
                or not snapshot.values or not set(snapshot.values).issubset(BY_KEY)):
            raise X32Error("Snapshot is incomplete for the current supported parameter set")
        return self._execute_values(snapshot.values)

    def execute_keyword(self, project_id: int, keyword: str) -> dict[str, Any]:
        from ..models import X32Operation, X32Snapshot

        keyword = keyword.strip()
        snapshot = X32Snapshot.objects.filter(project_id=project_id, keyword=keyword).first()
        if snapshot:
            return self.restore_snapshot(snapshot)
        operation = X32Operation.objects.filter(project_id=project_id, apply_keyword=keyword).first()
        if operation:
            return self.execute_operation(operation)
        operation = X32Operation.objects.filter(project_id=project_id, rollback_keyword=keyword).first()
        if operation:
            return self.execute_operation(operation, rollback=True)
        raise X32Error(f"No X32 snapshot or operation uses keyword '{keyword}'")

    def execute_operation_id(
        self, project_id: int, operation_id: int, *, rollback: bool = False
    ) -> dict[str, Any]:
        from ..models import X32Operation

        operation = X32Operation.objects.get(id=operation_id, project_id=project_id)
        return self.execute_operation(operation, rollback=rollback)

    def restore_snapshot_id(self, project_id: int, snapshot_id: int) -> dict[str, Any]:
        from ..models import X32Snapshot

        snapshot = X32Snapshot.objects.get(id=snapshot_id, project_id=project_id)
        return self.restore_snapshot(snapshot)

    def delete_item(self, project_id: int, kind: str, item_id: int) -> None:
        from ..models import X32Operation, X32Snapshot

        models = {"operation": X32Operation, "snapshot": X32Snapshot}
        model = models.get(kind)
        if model is None:
            raise X32Error("Unsupported X32 item type")
        deleted, _ = model.objects.filter(id=item_id, project_id=project_id).delete()
        if not deleted:
            raise X32Error(f"X32 {kind} was not found")

    def _execute_values(self, values: dict[str, Any]) -> dict[str, Any]:
        self._require_online()
        client = self._require_client()
        if not set(values).issubset(BY_KEY):
            raise X32Error("Unsupported saved settings")
        sent = 0
        with self._io_lock:
            # Establish links before restoring individual channel values.
            for key, raw in sorted(values.items(), key=lambda item: not item[0].startswith("link.")):
                parameter = BY_KEY.get(key)
                if not parameter:
                    raise X32Error(f"Unsupported saved setting: {key}")
                client.send(parameter.address, raw)
                with self._lock:
                    self._live[key] = normalize_value(parameter, raw)
                    if parameter.group == "name":
                        self._names[parameter.channel - 1] = raw or f"CH {parameter.channel:02d}"
                sent += 1
                time.sleep(0.002)
        return {"status": "ok", "sent": sent}

    def _maintenance_loop(self) -> None:
        next_probe = 0.0
        while self._running:
            client = self._client
            if not client:
                return
            now = time.monotonic()
            try:
                client.send("/xremote")
                client.send("/meters", "meters/1")
                if now >= next_probe:
                    reply = client.query("/info", timeout=0.8)
                    online = isinstance(reply, list) and len(reply) >= 4
                    with self._lock:
                        self._online = online
                        if online:
                            self._model = str(reply[2])
                            self._firmware = str(reply[3])
                    if online:
                        # Refresh names and controls after reconnect; /xremote carries edits between probes.
                        with self._io_lock:
                            client.query_many([p.address for p in PARAMETERS])
                        self.refresh_headamps()
                    next_probe = now + 5.0
            except Exception:
                with self._lock:
                    self._online = False
                logger.debug("X32 maintenance request failed", exc_info=True)
            time.sleep(4.0)

    def _on_update(self, address: str, value: Any) -> None:
        if address == "/meters/1" and isinstance(value, (bytes, bytearray)):
            self._decode_meters(value)
            return
        if address.startswith("/headamp/") and address.endswith("/phantom"):
            try:
                with self._lock:
                    self._phantom[int(address.split("/")[2])] = bool(value)
            except (ValueError, TypeError):
                pass
            return
        if address in CHANNEL_NAME_ADDRESSES and isinstance(value, str):
            with self._lock:
                self._names[CHANNEL_NAME_ADDRESSES[address] - 1] = value.strip() or f"CH {CHANNEL_NAME_ADDRESSES[address]:02d}"
        parameter = BY_ADDRESS.get(address)
        if parameter is None or isinstance(value, list):
            return
        try:
            normalized = normalize_value(parameter, value)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._live[parameter.key] = normalized
            self._online = True

    def _decode_meters(self, blob: bytes) -> None:
        # X32 meter blobs begin with a little-endian float count.
        if len(blob) < 4:
            return
        count = struct.unpack_from("<I", blob, 0)[0]
        count = min(count, (len(blob) - 4) // 4)
        if count < 32:
            return
        values = struct.unpack_from(f"<{count}f", blob, 4)
        with self._lock:
            self._meters = [max(0.0, min(1.0, float(v))) for v in values[:32]]

    def _replace_baseline(self, project_id: int, values: dict[str, Any]) -> None:
        from ..models import X32CaptureState

        X32CaptureState.objects.update_or_create(
            project_id=project_id,
            defaults={"baseline": values, "coverage": coverage()},
        )

    def _validate_keywords(
        self,
        project_id: int,
        *,
        snapshot_keyword: str = "",
        operation_keywords: list[str] | None = None,
    ) -> None:
        from ..models import X32Operation, X32Snapshot

        keywords = [value.strip() for value in ([snapshot_keyword] + (operation_keywords or [])) if value.strip()]
        if len({value.casefold() for value in keywords}) != len(keywords):
            raise X32Error("Keywords must be unique")
        existing = [value for value in X32Snapshot.objects.filter(project_id=project_id).values_list("keyword", flat=True) if value]
        for apply, rollback in X32Operation.objects.filter(project_id=project_id).values_list("apply_keyword", "rollback_keyword"):
            existing.extend(value for value in (apply, rollback) if value)
        folded = {value.casefold() for value in existing}
        duplicate = next((value for value in keywords if value.casefold() in folded), None)
        if duplicate:
            raise X32Error(f"Keyword is already in use: {duplicate}")

    @staticmethod
    def _clean_names(name: str, keyword: str) -> tuple[str, str]:
        name, keyword = name.strip(), keyword.strip()
        if not name:
            raise X32Error("Snapshot name is required")
        return name, keyword

    @staticmethod
    def _change_row(parameter, before, after) -> dict[str, Any]:
        return {
            "key": parameter.key,
            "label": f"{'FX return' if parameter.key.startswith('fxrtn.') else 'CH'} {parameter.channel:02d} · {parameter.label}",
            "channel": parameter.channel,
            "group": parameter.group,
            "bus": parameter.bus,
            "before": display_value(parameter, before),
            "after": display_value(parameter, after),
        }

    @staticmethod
    def _operation_row(obj) -> dict[str, Any]:
        return {
            "id": obj.id,
            "name": obj.name,
            "apply_keyword": obj.apply_keyword,
            "rollback_keyword": obj.rollback_keyword,
            "changes": obj.changes,
            "created_at": obj.created_at.isoformat(),
        }

    @staticmethod
    def _snapshot_row(obj) -> dict[str, Any]:
        return {
            "id": obj.id,
            "name": obj.name,
            "keyword": obj.keyword,
            "coverage": obj.coverage,
            "created_at": obj.created_at.isoformat(),
        }

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise X32Error("Configure and enable the X32 connection in Preferences")

    def _require_online(self) -> None:
        self._require_enabled()
        if not self._online:
            raise X32Error("X32 is offline")

    def _require_client(self) -> X32OSCClient:
        if not self._client:
            raise X32Error("X32 OSC client is not running")
        return self._client


_service = X32Service()


def get_x32_service() -> X32Service:
    return _service
