"""Load and resolve the active setlist against the current timeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import Setlist

if TYPE_CHECKING:
    from .timeline import Timeline


def _timeline_index_for_song(timeline: Timeline | None, song_name: str) -> int | None:
    if timeline is None or not timeline.is_valid:
        return None
    for i, song in enumerate(timeline.all_songs()):
        if song.name == song_name:
            return i
    return None


def load_active_setlist(
    timeline: Timeline | None,
    *,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    """Return the active setlist with entries resolved against *timeline*."""
    qs = Setlist.objects.filter(is_active=True)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    setlist = qs.prefetch_related("entries").first()
    if setlist is None:
        return None

    entries = []
    for entry in setlist.entries.all():
        timeline_index = _timeline_index_for_song(timeline, entry.song_name)
        entries.append(
            {
                "id": entry.id,
                "song_name": entry.song_name,
                "order": entry.order,
                "auto_cue_next": entry.auto_cue_next,
                "gap_seconds": entry.gap_seconds,
                "notes": entry.notes,
                "timeline_index": timeline_index,
                "missing": timeline_index is None,
            }
        )

    return {
        "id": setlist.id,
        "name": setlist.name,
        "entries": entries,
    }


def reload_engine_active_setlist() -> None:
    """Refresh cached active setlist in the runtime engine."""
    from .runtime import get_engine

    get_engine().reload_active_setlist()
