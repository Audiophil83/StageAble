"""
Persist and restore the last Ableton arrangement scan.

The runtime uses this cache on startup so clients can load songs, sections,
lyrics, and chords before a live scan is triggered.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import close_old_connections
from django.utils import timezone

from .models import ProjectCache
from .timeline import EventType, MeterEntry, MeterMap, Timeline, TimelineEvent

if TYPE_CHECKING:
    from .state import EngineState

logger = logging.getLogger(__name__)


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


def save_project_cache(
    *,
    timeline: Timeline,
    timeline_errors: list[str],
    tempo: float,
    cue_points: list[dict],
    mixer_tracks: list[dict],
) -> None:
    """Persist the current scan result (safe to call from a worker thread)."""
    close_old_connections()
    try:
        cache, _ = ProjectCache.objects.get_or_create(pk=1)
        cache.scanned_at = timezone.now()
        cache.tempo = tempo
        cache.is_valid = timeline.is_valid
        cache.timeline_errors = list(timeline_errors)
        cache.timeline_data = timeline_to_data(timeline)
        cache.cue_points = list(cue_points)
        cache.mixer_tracks = list(mixer_tracks)
        cache.save()
        logger.info(
            "Saved project cache (%d songs, %d sections)",
            len(timeline.songs),
            len(timeline.sections),
        )
    except Exception:
        logger.exception("Failed to save project cache")
    finally:
        close_old_connections()


def load_project_cache() -> dict[str, Any] | None:
    """Load cached scan data from the database, or None if empty."""
    close_old_connections()
    try:
        try:
            cache = ProjectCache.objects.get(pk=1)
        except ProjectCache.DoesNotExist:
            return None
        if cache.scanned_at is None or not cache.timeline_data:
            return None
        timeline = timeline_from_data(cache.timeline_data)
        scanned_at = cache.scanned_at.timestamp()
        return {
            "timeline": timeline,
            "timeline_errors": list(cache.timeline_errors or []),
            "tempo": cache.tempo,
            "cue_points": list(cache.cue_points or []),
            "mixer_tracks": list(cache.mixer_tracks or []),
            "project_scanned_at": scanned_at,
        }
    finally:
        close_old_connections()


def apply_cache_to_state(state: EngineState) -> bool:
    """Load cached project data into engine state. Returns True if data was loaded."""
    payload = load_project_cache()
    if payload is None:
        return False

    state.update(
        timeline=payload["timeline"],
        timeline_errors=payload["timeline_errors"],
        tempo=payload["tempo"],
        cue_points=payload["cue_points"],
        mixer_tracks=payload["mixer_tracks"],
        project_scanned_at=payload["project_scanned_at"],
    )
    return True
