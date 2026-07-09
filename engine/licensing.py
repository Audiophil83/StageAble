"""License activation and trial mode for paid distribution.

License keys use the format ``RA-XXXX-XXXX-XXXX`` where the payload is an
HMAC-SHA256 signature truncated to base32. Set ``REMOTEABLE_LICENSE_SECRET`` at
build time for production keys; a dev default is used for local testing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from engine.paths import app_data_dir

LICENSE_FILE = "license.json"
KEY_PATTERN = re.compile(r"^RA-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$")
TRIAL_SESSION_SECONDS = 15 * 60
_DEV_SECRET = b"remoteable-dev-license-secret-change-in-production"


class LicenseMode(str, Enum):
    LICENSED = "licensed"
    TRIAL = "trial"
    TRIAL_EXPIRED = "trial_expired"


@dataclass(frozen=True)
class LicenseStatus:
    mode: LicenseMode
    trial_seconds_remaining: int | None = None
    license_key_masked: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"mode": self.mode.value}
        if self.trial_seconds_remaining is not None:
            data["trial_seconds_remaining"] = self.trial_seconds_remaining
        if self.license_key_masked is not None:
            data["license_key_masked"] = self.license_key_masked
        return data


def _secret() -> bytes:
    value = os.environ.get("REMOTEABLE_LICENSE_SECRET", "").strip()
    if value:
        return value.encode("utf-8")
    return _DEV_SECRET


def _license_path():
    return app_data_dir() / LICENSE_FILE


def _normalize_key(key: str) -> str:
    cleaned = key.strip().upper().replace(" ", "")
    if cleaned.startswith("RA") and not cleaned.startswith("RA-"):
        cleaned = "RA-" + cleaned[2:]
    return cleaned


def _base32_crockford(data: bytes, length: int = 12) -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    num = int.from_bytes(data, "big")
    chars: list[str] = []
    for _ in range(length):
        chars.append(alphabet[num & 31])
        num >>= 5
    return "".join(reversed(chars))


def _sign_edition(edition: str) -> str:
    digest = hmac.new(_secret(), edition.encode("utf-8"), hashlib.sha256).digest()
    return _base32_crockford(digest, 12)


def generate_license_key(*, edition: str = "standard") -> str:
    """Generate a signed license key (for storefront scripts / tests)."""
    body = _sign_edition(edition)
    return f"RA-{body[0:4]}-{body[4:8]}-{body[8:12]}"


def validate_license_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if not KEY_PATTERN.match(normalized):
        return False
    body = normalized.replace("RA-", "").replace("-", "")
    return any(_sign_edition(edition) == body for edition in ("standard", "intro", "pro", "beta"))


def _load_store() -> dict[str, Any]:
    path = _license_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_store(data: dict[str, Any]) -> None:
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _license_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _mask_key(key: str) -> str:
    normalized = _normalize_key(key)
    parts = normalized.split("-")
    if len(parts) != 4:
        return "RA-****-****-****"
    return f"{parts[0]}-{parts[1]}-****-{parts[3]}"


def activate_license(key: str) -> LicenseStatus:
    normalized = _normalize_key(key)
    if not validate_license_key(normalized):
        raise ValueError("Invalid license key.")
    store = _load_store()
    store["license_key"] = normalized
    store.pop("trial_started_at", None)
    _save_store(store)
    return get_status()


def clear_license() -> LicenseStatus:
    """Remove stored license (dev / support tooling)."""
    path = _license_path()
    if path.is_file():
        path.unlink()
    return get_status()


def _trial_started_at(store: dict[str, Any]) -> float:
    value = store.get("trial_started_at")
    if isinstance(value, (int, float)):
        return float(value)
    started = time.time()
    store["trial_started_at"] = started
    _save_store(store)
    return started


def get_status(*, now: float | None = None) -> LicenseStatus:
    store = _load_store()
    license_key = store.get("license_key")
    if isinstance(license_key, str) and validate_license_key(license_key):
        return LicenseStatus(
            mode=LicenseMode.LICENSED,
            license_key_masked=_mask_key(license_key),
        )

    current = now if now is not None else time.time()
    started = _trial_started_at(store)
    elapsed = max(0.0, current - started)
    remaining = max(0, int(TRIAL_SESSION_SECONDS - elapsed))
    if remaining <= 0:
        return LicenseStatus(mode=LicenseMode.TRIAL_EXPIRED, trial_seconds_remaining=0)
    return LicenseStatus(mode=LicenseMode.TRIAL, trial_seconds_remaining=remaining)


def is_entitled() -> bool:
    mode = get_status().mode
    return mode in (LicenseMode.LICENSED, LicenseMode.TRIAL)


_BLOCKED_COMMANDS = frozenset(
    {
        "play",
        "stop",
        "seek",
        "jump_to_song",
        "jump_to_section",
        "rehearse_play",
        "rehearse_loop",
        "rehearse_stop",
    }
)


def blocked_command_message(command: str) -> str | None:
    if command in _BLOCKED_COMMANDS and not is_entitled():
        return (
            "Your RemoteAble trial session has ended. "
            "Activate a license key from the desktop app to continue."
        )
    return None


def entitlement_message() -> str | None:
    status = get_status()
    if status.mode == LicenseMode.TRIAL_EXPIRED:
        return (
            "Your RemoteAble trial session has ended. "
            "Activate a license key from the menu bar to continue."
        )
    if status.mode == LicenseMode.TRIAL and status.trial_seconds_remaining is not None:
        minutes = max(1, (status.trial_seconds_remaining + 59) // 60)
        return f"Trial mode — {minutes} minute(s) remaining in this session."
    return None
