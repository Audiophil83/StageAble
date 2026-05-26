"""
Load engine configuration from the database.

Environment variables in ``remoteable/settings.py`` are used only as defaults
when the settings row is first created (e.g. during migration).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings as django_settings

if TYPE_CHECKING:
    from .models import AppSettings


@dataclass(frozen=True)
class AppSettingsData:
    ableton_osc_host: str
    ableton_osc_send_port: int
    ableton_osc_recv_port: int
    engine_poll_hz: int
    default_preroll_bars: int


def _env_defaults() -> dict:
    return {
        "ableton_osc_host": django_settings.ABLETON_OSC_HOST,
        "ableton_osc_send_port": django_settings.ABLETON_OSC_SEND_PORT,
        "ableton_osc_recv_port": django_settings.ABLETON_OSC_RECV_PORT,
        "engine_poll_hz": django_settings.ENGINE_POLL_HZ,
        "default_preroll_bars": django_settings.DEFAULT_PREROLL_BARS,
    }


def _to_data(obj: AppSettings | AppSettingsData) -> AppSettingsData:
    return AppSettingsData(
        ableton_osc_host=obj.ableton_osc_host,
        ableton_osc_send_port=obj.ableton_osc_send_port,
        ableton_osc_recv_port=obj.ableton_osc_recv_port,
        engine_poll_hz=obj.engine_poll_hz,
        default_preroll_bars=obj.default_preroll_bars,
    )


def get_app_settings() -> AppSettingsData:
    """Return current app settings, falling back to env defaults if DB unavailable."""
    from django.db import OperationalError, ProgrammingError

    from .models import AppSettings

    try:
        obj, _ = AppSettings.objects.get_or_create(pk=1, defaults=_env_defaults())
        return _to_data(obj)
    except (OperationalError, ProgrammingError):
        return AppSettingsData(**_env_defaults())


def get_app_settings_model() -> AppSettings:
    """Return the singleton AppSettings model instance."""
    from .models import AppSettings

    obj, _ = AppSettings.objects.get_or_create(pk=1, defaults=_env_defaults())
    return obj
