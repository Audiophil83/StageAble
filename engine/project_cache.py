"""
Persist and restore Ableton arrangement scans keyed by project identity.

Each Ableton Live set gets its own ProjectCache row. The runtime loads the
matching cache when the open project changes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import close_old_connections
from django.utils import timezone

from .models import AppSettings, ProjectCache
from .timeline import EventType, MeterEntry, MeterMap, Timeline, TimelineEvent

if TYPE_CHECKING:
    from .state import EngineState

logger = logging.getLogger(__name__)

LEGACY_IDENTITY = "legacy:imported"


def compute_project_identity(file_path: str, name: str) -> str:
    """Return a stable lookup key for an Ableton Live set."""
    if file_path:
        return file_path
    if name:
        return f"unsaved:{name}"
    return "unsaved:unknown"


def project_to_state_dict(project: ProjectCache) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "file_path": project.file_path,
        "identity": project.identity,
        "display_name": project.display_name,
    }


def _event_row(evt: TimelineEvent) -> dict[str, Any]:
    return {
        "type": evt.type.value,
        "name": evt.name,
        "start_beat": evt.start_beat,
        "end_beat": evt.end_beat,
    }


def _meter_row(entry: MeterEntry) -> dict[str, Any]:
    return {
        "beat": entry.beat,
        "numerator": entry.numerator,
        "denominator": entry.denominator,
        "tempo": entry.tempo,
    }


def timeline_to_data(timeline: Timeline) -> dict[str, Any]:
    """Serialize a Timeline for JSON storage."""
    meter_entries = list(timeline.meter_map._entries) if timeline.meter_map else []
    return {
        "is_valid": timeline.is_valid,
        "errors": list(timeline.errors),
        "songs": [_event_row(e) for e in timeline.songs],
        "sections": [_event_row(e) for e in timeline.sections],
        "lyrics": [_event_row(e) for e in timeline.lyrics],
        "chords": [_event_row(e) for e in timeline.chords],
        "stops": [_event_row(e) for e in timeline.stops],
        "meter_map": [_meter_row(e) for e in meter_entries],
    }


def _events_from_rows(rows: list[dict[str, Any]], event_type: EventType) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for row in rows:
        events.append(
            TimelineEvent(
                start_beat=float(row["start_beat"]),
                end_beat=row.get("end_beat"),
                type=event_type,
                name=row.get("name", ""),
            )
        )
    return events


def timeline_from_data(data: dict[str, Any]) -> Timeline:
    """Rebuild a Timeline from stored JSON."""
    tl = Timeline()
    tl.is_valid = bool(data.get("is_valid", True))
    tl.errors = list(data.get("errors") or [])

    for evt in _events_from_rows(data.get("songs") or [], EventType.SONG):
        tl.songs.add(evt)
    for evt in _events_from_rows(data.get("sections") or [], EventType.SECTION):
        tl.sections.add(evt)
    for evt in _events_from_rows(data.get("lyrics") or [], EventType.LYRIC):
        tl.lyrics.add(evt)
    for evt in _events_from_rows(data.get("chords") or [], EventType.CHORD):
        tl.chords.add(evt)
    for evt in _events_from_rows(data.get("stops") or [], EventType.STOP):
        tl.stops.add(evt)

    meter_rows = data.get("meter_map") or []
    if meter_rows:
        entries = [
            MeterEntry(
                beat=float(row["beat"]),
                numerator=int(row.get("numerator", 4)),
                denominator=int(row.get("denominator", 4)),
                tempo=float(row.get("tempo", 120.0)),
            )
            for row in meter_rows
        ]
        tl.meter_map = MeterMap(entries)

    return tl


def _cache_payload_from_row(cache: ProjectCache) -> dict[str, Any]:
    timeline = timeline_from_data(cache.timeline_data)
    scanned_at = cache.scanned_at.timestamp() if cache.scanned_at else None
    return {
        "project": project_to_state_dict(cache),
        "timeline": timeline,
        "timeline_errors": list(cache.timeline_errors or []),
        "tempo": cache.tempo,
        "cue_points": list(cache.cue_points or []),
        "mixer_tracks": list(cache.mixer_tracks or []),
        "project_scanned_at": scanned_at,
    }


def get_or_create_project_record(
    *,
    identity: str,
    name: str = "",
    file_path: str = "",
) -> ProjectCache:
    close_old_connections()
    try:
        project, created = ProjectCache.objects.get_or_create(
            identity=identity,
            defaults={"name": name, "file_path": file_path},
        )
        if not created and (name or file_path):
            updates: list[str] = []
            if name and project.name != name:
                project.name = name
                updates.append("name")
            if file_path and project.file_path != file_path:
                project.file_path = file_path
                updates.append("file_path")
            if updates:
                project.save(update_fields=updates)
        return project
    finally:
        close_old_connections()


def set_last_active_project(project: ProjectCache) -> None:
    close_old_connections()
    try:
        settings, _ = AppSettings.objects.get_or_create(pk=1)
        if settings.last_active_project_id != project.id:
            settings.last_active_project = project
            settings.save(update_fields=["last_active_project", "updated_at"])
    finally:
        close_old_connections()


def resolve_project_identity_from_settings() -> str | None:
    """Best-effort project identity when the engine has no active project."""
    close_old_connections()
    try:
        settings = AppSettings.objects.filter(pk=1).select_related(
            "last_active_project"
        ).first()
        if settings and settings.last_active_project:
            return settings.last_active_project.identity
        legacy = ProjectCache.objects.filter(identity=LEGACY_IDENTITY).first()
        return legacy.identity if legacy else None
    finally:
        close_old_connections()


def save_project_cache(
    *,
    identity: str,
    name: str = "",
    file_path: str = "",
    timeline: Timeline,
    timeline_errors: list[str],
    tempo: float,
    cue_points: list[dict],
    mixer_tracks: list[dict],
) -> ProjectCache | None:
    """Persist a scan result for *identity* (safe to call from a worker thread)."""
    close_old_connections()
    try:
        project = get_or_create_project_record(
            identity=identity,
            name=name,
            file_path=file_path,
        )
        project.scanned_at = timezone.now()
        project.tempo = tempo
        project.is_valid = timeline.is_valid
        project.timeline_errors = list(timeline_errors)
        project.timeline_data = timeline_to_data(timeline)
        project.cue_points = list(cue_points)
        project.mixer_tracks = list(mixer_tracks)
        project.save()
        set_last_active_project(project)
        logger.info(
            "Saved project cache %r (%d songs, %d sections)",
            project.display_name,
            len(timeline.songs),
            len(timeline.sections),
        )
        return project
    except Exception:
        logger.exception("Failed to save project cache")
        return None
    finally:
        close_old_connections()


def load_project_cache(identity: str | None = None) -> dict[str, Any] | None:
    """Load cached scan data for *identity*, or None if empty."""
    close_old_connections()
    try:
        if identity is None:
            identity = resolve_project_identity_from_settings()
        if identity is None:
            return None

        try:
            cache = ProjectCache.objects.get(identity=identity)
        except ProjectCache.DoesNotExist:
            return None
        if cache.scanned_at is None or not cache.timeline_data:
            return None
        return _cache_payload_from_row(cache)
    finally:
        close_old_connections()


def load_last_active_project_cache() -> dict[str, Any] | None:
    """Load the last active project from AppSettings."""
    close_old_connections()
    try:
        settings = AppSettings.objects.filter(pk=1).select_related(
            "last_active_project"
        ).first()
        if not settings or not settings.last_active_project:
            return None
        cache = settings.last_active_project
        if cache.scanned_at is None or not cache.timeline_data:
            return None
        return _cache_payload_from_row(cache)
    finally:
        close_old_connections()


def apply_cache_payload_to_state(state: EngineState, payload: dict[str, Any]) -> None:
    state.update(
        active_project=payload["project"],
        timeline=payload["timeline"],
        timeline_errors=payload["timeline_errors"],
        tempo=payload["tempo"],
        cue_points=payload["cue_points"],
        mixer_tracks=payload["mixer_tracks"],
        project_scanned_at=payload["project_scanned_at"],
    )


def clear_project_state(state: EngineState, *, project: dict[str, Any] | None = None) -> None:
    state.update(
        active_project=project,
        timeline=None,
        timeline_errors=[],
        cue_points=[],
        mixer_tracks=[],
        project_scanned_at=None,
        active_setlist=None,
        active_setlist_index=None,
    )


def apply_cache_to_state(
    state: EngineState,
    identity: str | None = None,
) -> bool:
    """Load cached project data into engine state. Returns True if data was loaded."""
    payload = load_project_cache(identity)
    if payload is None:
        return False
    apply_cache_payload_to_state(state, payload)
    return True
