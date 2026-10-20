"""Supported X32 parameters and user-facing value conversions."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any


@dataclass(frozen=True)
class Parameter:
    key: str
    address: str
    label: str
    channel: int
    group: str
    value_type: str = "float"
    bus: int | None = None


def _channel_parameters(channel: int) -> list[Parameter]:
    prefix = f"/ch/{channel:02d}"
    items = [
        Parameter(f"ch.{channel}.name", f"{prefix}/config/name", "Name", channel, "name", "string"),
        Parameter(f"ch.{channel}.polarity", f"{prefix}/preamp/invert", "Polarity invert", channel, "polarity", "bool"),
        Parameter(f"ch.{channel}.level", f"{prefix}/mix/fader", "Level", channel, "level"),
        Parameter(f"ch.{channel}.mute", f"{prefix}/mix/on", "Mute", channel, "mute", "on"),
        Parameter(f"ch.{channel}.pan", f"{prefix}/mix/pan", "Pan", channel, "pan"),
        Parameter(f"ch.{channel}.gain", f"{prefix}/preamp/trim", "Gain/trim", channel, "gain"),
        Parameter(f"ch.{channel}.solo", f"/-stat/solosw/{channel:02d}", "Solo", channel, "solo", "bool"),
    ]
    for bus in range(1, 17):
        items.append(
            Parameter(
                f"ch.{channel}.send.{bus}",
                f"{prefix}/mix/{bus:02d}/level",
                f"Send {bus}",
                channel,
                "send",
                bus=bus,
            )
        )
    return items


PARAMETERS = tuple(
    parameter for channel in range(1, 33) for parameter in _channel_parameters(channel)
)
# Pair links have one canonical key shared by both channel strips.
PARAMETERS += tuple(
    Parameter(f"link.{ch}", f"/config/chlink/{ch:02d}-{ch + 1:02d}",
              "Stereo link", ch, "link", "bool")
    for ch in range(1, 33, 2)
)
PARAMETERS += tuple(
    Parameter(f"fxrtn.{ch}.{key}", f"/fxrtn/{ch:02d}/{address}", label, ch, group, kind)
    for ch in range(1, 9)
    for key, address, label, group, kind in [
        ("level", "mix/fader", "FX return level", "level", "float"),
        ("pan", "mix/pan", "FX return pan", "pan", "float"),
        ("mute", "mix/on", "FX return mute", "mute", "on"),
        *[(f"send.{bus}", f"mix/{bus:02d}/level", f"FX send {bus}", "send", "float") for bus in range(1, 17)],
    ]
)
BY_KEY = {parameter.key: parameter for parameter in PARAMETERS}
BY_ADDRESS = {parameter.address: parameter for parameter in PARAMETERS}
CHANNEL_NAME_ADDRESSES = {
    f"/ch/{channel:02d}/config/name": channel for channel in range(1, 33)
}


def fader_to_db(value: float) -> float | None:
    value = max(0.0, min(1.0, float(value)))
    if value < 0.0625:
        return None
    if value < 0.125:
        return 480.0 * value - 110.0
    if value < 0.25:
        return 160.0 * value - 70.0
    if value < 0.5:
        return 80.0 * value - 50.0
    return 40.0 * value - 30.0


def db_to_fader(db: float | None) -> float:
    if db is None or float(db) <= -90.0:
        return 0.0
    db = max(-90.0, min(10.0, float(db)))
    if db < -50.0:
        return (db + 110.0) / 480.0
    if db < -30.0:
        return (db + 70.0) / 160.0
    if db < -10.0:
        return (db + 50.0) / 80.0
    return (db + 30.0) / 40.0


def normalize_value(parameter: Parameter, raw: Any) -> int | float | str:
    if parameter.value_type == "string":
        return str(raw)
    if parameter.value_type in {"bool", "on"}:
        return 1 if bool(raw) else 0
    return round(float(raw), 6)


def display_value(parameter: Parameter, raw: Any) -> dict[str, Any]:
    raw = normalize_value(parameter, raw)
    if parameter.value_type == "string":
        return {"value": raw, "unit": "", "text": raw}
    if parameter.group in {"level", "send"}:
        db = fader_to_db(float(raw))
        return {"value": db, "unit": "dB", "text": "−∞" if db is None else f"{db:.1f} dB"}
    if parameter.group == "pan":
        pan = round((float(raw) - 0.5) * 200)
        text = "C" if pan == 0 else (f"L {abs(pan)}" if pan < 0 else f"R {pan}")
        return {"value": pan, "unit": "%", "text": text}
    if parameter.group == "gain":
        gain = round((float(raw) * 36.0) - 18.0, 1)
        return {"value": gain, "unit": "dB", "text": f"{gain:+.1f} dB"}
    enabled = bool(raw)
    return {"value": enabled, "unit": "", "text": "On" if enabled else "Off"}


def raw_from_display(parameter: Parameter, value: Any) -> int | float | str:
    if parameter.value_type == "string":
        if not isinstance(value, str) or len(value) > 12 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Channel names must contain at most 12 printable ASCII characters")
        return value
    if parameter.value_type in {"bool", "on"} and not isinstance(value, bool):
        raise ValueError("Toggle values must be boolean")
    if parameter.value_type == "float" and value is not None and not isfinite(float(value)):
        raise ValueError("Mixer values must be finite numbers")
    if parameter.group in {"level", "send"}:
        return round(db_to_fader(None if value is None else float(value)), 6)
    if parameter.group == "pan":
        return round((max(-100.0, min(100.0, float(value))) + 100.0) / 200.0, 6)
    if parameter.group == "gain":
        return round((max(-18.0, min(18.0, float(value))) + 18.0) / 36.0, 6)
    if parameter.value_type == "on":
        # X32 /mix/on is the inverse of the user-facing muted state.
        return 0 if bool(value) else 1
    return 1 if bool(value) else 0


def user_value(parameter: Parameter, raw: Any) -> Any:
    if parameter.value_type == "on":
        return not bool(raw)
    return display_value(parameter, raw)["value"]


def values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return isclose(float(a), float(b), abs_tol=0.0001)
    return a == b


def coverage() -> dict[str, Any]:
    return {
        "channels": 32,
        "parameters": len(PARAMETERS),
        "controls": ["level", "solo", "mute", "pan", "gain", "sends", "name", "polarity", "link", "fx_returns"],
        "sends_per_channel": 16,
    }
