"""
Persist and restore Ableton arrangement scans keyed by project identity.

Each Ableton Live set gets its own ProjectCache row. The runtime loads the
matching cache when the open project changes.
"""

from __future__ import annotations

import hashlib
import logging
import os
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


def compute_arrangement_fingerprint(timeline_data: dict[str, Any]) -> str:
    """Deterministic hash of song and section names with start beats."""
    parts: list[str] = []
    for song in timeline_data.get("songs") or []:
        parts.append(f"s:{song['name']}@{song['start_beat']}")
    for section in timeline_data.get("sections") or []:
        parts.append(f"sec:{section['name']}@{section['start_beat']}")
    if not parts:
        return ""
    parts.sort()
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return digest[:32]


def compute_cue_fingerprint(cue_points: list[tuple[str, float]]) -> str:
    """Hash cue marker names and times for lightweight live matching."""
    if not cue_points:
        return ""
    parts = [f"{name}@{round(time, 4)}" for name, time in sorted(cue_points)]
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return digest[:32]


def fingerprint_from_timeline(timeline: Timeline) -> str:
    """Return arrangement fingerprint for a live Timeline."""
    return compute_arrangement_fingerprint(timeline_to_data(timeline))


def _cue_points_from_cache(project: ProjectCache) -> frozenset[tuple[str, float]]:
    return frozenset(
        (str(cp["name"]), round(float(cp["time"]), 4))
        for cp in (project.cue_points or [])
    )


def _arrangement_matches(
    project: ProjectCache,
    *,
    in_memory_timeline: Timeline | None = None,
    cue_points: frozenset[tuple[str, float]] | None = None,
) -> bool:
    if in_memory_timeline is not None:
        fp = fingerprint_from_timeline(in_memory_timeline)
        if fp and project.arrangement_fingerprint and fp == project.arrangement_fingerprint:
            return True
        if fp and project.timeline_data and fp == compute_arrangement_fingerprint(
            project.timeline_data
        ):
            return True

    if cue_points and project.cue_points:
        if cue_points == _cue_points_from_cache(project):
            return True

    return False


def _save_as_path_match(
    previous_identity: str, new_file_path: str, new_name: str
) -> bool:
    if not previous_identity.startswith("unsaved:"):
        return False
    if not new_file_path:
        return False
    unsaved_name = previous_identity[len("unsaved:") :]
    if unsaved_name.lower().endswith(".als"):
        unsaved_name = unsaved_name[:-4]
    base = os.path.basename(new_file_path)
    if base.lower().endswith(".als"):
        base = base[:-4]
    if base == unsaved_name:
        return True
    if new_name:
        normalized = new_name
        if normalized.lower().endswith(".als"):
            normalized = normalized[:-4]
        return base == normalized
    return False



def find_relocation_candidate(
    *,
    new_identity: str,
    new_name: str = "",
    new_file_path: str = "",
    previous_identity: str | None = None,
    cue_points: frozenset[tuple[str, float]] | None = None,
    in_memory_timeline: Timeline | None = None,
) -> ProjectCache | None:
    """Return an existing project row to relocate when identity changed."""
    close_old_connections()
    try:
        if ProjectCache.objects.filter(identity=new_identity).exists():
            return None

        previous: ProjectCache | None = None
        if previous_identity and previous_identity != new_identity:
            previous = ProjectCache.objects.filter(identity=previous_identity).first()

        if previous is not None and _arrangement_matches(
            previous,
            in_memory_timeline=in_memory_timeline,
            cue_points=cue_points,
        ):
            return previous

        if (
            previous is not None
            and previous_identity
            and previous_identity.startswith("unsaved:")
            and _save_as_path_match(previous_identity, new_file_path, new_name)
            and _arrangement_matches(
                previous,
                in_memory_timeline=in_memory_timeline,
                cue_points=cue_points,
            )
        ):
            return previous

        probe_fp = (
            fingerprint_from_timeline(in_memory_timeline)
            if in_memory_timeline is not None
            else ""
        )
        if not probe_fp:
            return None

        matches = list(
            ProjectCache.objects.filter(arrangement_fingerprint=probe_fp).exclude(
                identity=new_identity
            )
        )
        if len(matches) != 1:
            return None

        candidate = matches[0]
        if not _arrangement_matches(
            candidate,
            in_memory_timeline=in_memory_timeline,
            cue_points=cue_points,
        ):
            return None

        return candidate
    finally:
        close_old_connections()


def relocate_project_record(
    project: ProjectCache,
    *,
    identity: str,
    name: str = "",
    file_path: str = "",
) -> ProjectCache:
    """Update identity/path on an existing row (setlists stay linked)."""
    close_old_connections()
    try:
        old_identity = project.identity
        project.identity = identity
        if name:
            project.name = name
        if file_path:
            project.file_path = file_path
        project.save(update_fields=["identity", "name", "file_path", "updated_at"])
        logger.info("Relocated project cache: %s -> %s", old_identity, identity)
        return project
    finally:
        close_old_connections()


def resolve_or_relocate_project_record(
    *,
    identity: str,
    name: str = "",
    file_path: str = "",
    previous_identity: str | None = None,
    cue_points: frozenset[tuple[str, float]] | None = None,
    in_memory_timeline: Timeline | None = None,
) -> tuple[ProjectCache, bool]:
    """Get or create a project, relocating an existing row when appropriate."""
    close_old_connections()
    try:
        if ProjectCache.objects.filter(identity=identity).exists():
            return get_or_create_project_record(
                identity=identity, name=name, file_path=file_path
            ), False

        candidate = find_relocation_candidate(
            new_identity=identity,
            new_name=name,
            new_file_path=file_path,
            previous_identity=previous_identity,
            cue_points=cue_points,
            in_memory_timeline=in_memory_timeline,
        )
        if candidate is not None:
            return (
                relocate_project_record(
                    candidate, identity=identity, name=name, file_path=file_path
                ),
                True,
            )

        return (
            get_or_create_project_record(
                identity=identity, name=name, file_path=file_path
            ),
            False,
        )
    finally:
        close_old_connections()


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
        "x32_events": [_event_row(e) for e in timeline.x32_events],
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
    for evt in _events_from_rows(data.get("x32_events") or [], EventType.X32):
        tl.x32_events.add(evt)

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
        project.arrangement_fingerprint = fingerprint_from_timeline(timeline)
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
