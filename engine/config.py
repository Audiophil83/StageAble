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
    default_preroll_bars: int
    scan_meter_map: bool


def _env_defaults() -> dict:
    return {
        "ableton_osc_host": django_settings.ABLETON_OSC_HOST,
        "default_preroll_bars": django_settings.DEFAULT_PREROLL_BARS,
        "scan_meter_map": django_settings.SCAN_METER_MAP,
    }


def _to_data(obj: AppSettings | AppSettingsData) -> AppSettingsData:
    return AppSettingsData(
        ableton_osc_host=obj.ableton_osc_host,
        default_preroll_bars=obj.default_preroll_bars,
        scan_meter_map=obj.scan_meter_map,
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
