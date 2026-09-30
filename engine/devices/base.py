from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class DiscoveredDevice:
    adapter: str
    identifier: str
    name: str
    connected: bool = True
    error: str = ""
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class InputEvent:
    adapter: str
    identifier: str
    trigger: dict
    pressed: bool = True
    value: int | float | None = None


def trigger_key(trigger: dict) -> str:
    return json.dumps(trigger, sort_keys=True, separators=(",", ":"))


class InputAdapter:
    kind = "base"

    def __init__(self, callback: Callable[[InputEvent], None]):
        self.callback = callback

    def discover(self) -> list[DiscoveredDevice]:
        return []

    def start(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def status(self) -> dict:
        return {"available": True, "error": ""}
