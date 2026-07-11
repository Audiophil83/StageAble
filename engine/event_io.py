"""
Shared export/import helpers for semantic arrangement track clip names.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from django.core.management.base import CommandError

from engine.project_cache import (
    load_project_cache,
    resolve_project_identity_from_settings,
    save_project_cache,
)
from engine.state import engine_state
from engine.scanner import (
    TRACK_CHORDS,
    TRACK_CONTROL,
    TRACK_LYRICS,
    TRACK_SECTIONS,
    TRACK_SONGS,
    ArrangementClip,
)
from engine.timeline import EventType, Timeline, TimelineEvent

BEAT_TOLERANCE = 0.01

EVENTS_FILE_HEADER = """# ShowAble arrangement events
# Format: start_beat|end_beat|clip name
# Edit only clip names (after the second |). Do not change beat numbers.
# Use \\n in the text for a line break within one clip name.
# Lines starting with # are ignored.
# Sections: [SONGS] [SECTIONS] [LYRICS] [CHORDS] [CONTROL]
#
"""

LYRICS_FILE_HEADER = """# ShowAble lyrics
# Format: start_beat|end_beat|lyric text
# Edit only the lyric text (after the second |). Do not change beat numbers.
# Use \\n in the text for a line break within one lyric cue.
# Lines starting with # are ignored.
#
"""


@dataclass(frozen=True)
class TrackSpec:
    section: str
    scanner_key: str
    timeline_attr: str
    event_type: EventType


TRACK_SPECS: tuple[TrackSpec, ...] = (
    TrackSpec("SONGS", TRACK_SONGS, "songs", EventType.SONG),
    TrackSpec("SECTIONS", TRACK_SECTIONS, "sections", EventType.SECTION),
    TrackSpec("LYRICS", TRACK_LYRICS, "lyrics", EventType.LYRIC),
    TrackSpec("CHORDS", TRACK_CHORDS, "chords", EventType.CHORD),
    TrackSpec("CONTROL", TRACK_CONTROL, "stops", EventType.STOP),
)

TRACK_SPECS_BY_SECTION = {spec.section: spec for spec in TRACK_SPECS}
DEFAULT_TRACK_ORDER = tuple(spec.section for spec in TRACK_SPECS)


@dataclass(frozen=True)
class EventRow:
    start_beat: float
    end_beat: float | None
    text: str


def beat_key(beat: float) -> float:
    return round(beat, 4)


def format_beat(beat: float) -> str:
    return f"{beat:g}"


def beats_match(a: float, b: float) -> bool:
    return abs(a - b) <= BEAT_TOLERANCE


def escape_text(text: str) -> str:
    """Keep each clip name on one file line."""
    return (
        text.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def unescape_text(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def parse_timestamp_line(line: str) -> tuple[float, float | None, str] | None:
    """Return (start, end, text) when *line* is a timestamped event row."""
    parts = line.split("|", 2)
    if len(parts) != 3:
        return None

    try:
        start_beat = float(parts[0].strip())
    except ValueError:
        return None

    end_raw = parts[1].strip()
    if not end_raw:
        end_beat = None
    else:
        try:
            end_beat = float(end_raw)
        except ValueError:
            return None

    return start_beat, end_beat, unescape_text(parts[2])


def format_row(row: EventRow) -> str:
    end = "" if row.end_beat is None else f"{row.end_beat:g}"
    return f"{row.start_beat:g}|{end}|{escape_text(row.text)}"


def rows_from_clips(clips: list[ArrangementClip]) -> list[EventRow]:
    rows = [
        EventRow(
            start_beat=clip.start_time,
            end_beat=clip.start_time + clip.length,
            text=clip.name,
        )
        for clip in clips
    ]
    rows.sort(key=lambda row: row.start_beat)
    return rows


def rows_from_timeline_events(events) -> list[EventRow]:
    rows = [
        EventRow(
            start_beat=evt.start_beat,
            end_beat=evt.end_beat,
            text=evt.name,
        )
        for evt in events
    ]
    rows.sort(key=lambda row: row.start_beat)
    return rows


def _active_project_identity() -> str | None:
    project = engine_state.active_project
    if project:
        return project.get("identity")
    return resolve_project_identity_from_settings()


def rows_from_cache_section(section: str) -> list[EventRow]:
    payload = load_project_cache(_active_project_identity())
    if payload is None:
        raise CommandError(
            "No project cache found — scan the arrangement in ShowAble first, "
            "or export from Ableton without --from-cache."
        )

    spec = TRACK_SPECS_BY_SECTION[section]
    events = getattr(payload["timeline"], spec.timeline_attr)
    return rows_from_timeline_events(events)


def parse_section_rows(
    path: Path,
    lines: list[str],
    *,
    section: str | None = None,
    item_label: str = "event",
) -> list[EventRow]:
    rows: list[EventRow] = []
    seen_starts: set[float] = set()

    for line_no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            continue

        parsed = parse_timestamp_line(line)
        if parsed is not None:
            start_beat, end_beat, text = parsed
            key = beat_key(start_beat)
            if key in seen_starts:
                location = f"{path}:{line_no}"
                if section:
                    location = f"{path} [{section}] line {line_no}"
                raise CommandError(
                    f"{location}: duplicate start beat {format_beat(start_beat)}"
                )
            seen_starts.add(key)
            rows.append(EventRow(start_beat=start_beat, end_beat=end_beat, text=text))
            continue

        if not rows:
            location = f"{path}:{line_no}"
            if section:
                location = f"{path} [{section}] line {line_no}"
            raise CommandError(
                f"{location}: {item_label} line without a timestamp: {raw!r}"
            )

        prev = rows[-1]
        rows[-1] = EventRow(
            start_beat=prev.start_beat,
            end_beat=prev.end_beat,
            text=prev.text + "\n" + line,
        )

    return rows


def parse_events_file(path: Path) -> dict[str, list[EventRow]]:
    """Parse a multi-section events file into rows keyed by track section."""
    text = path.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().upper()
            if current not in TRACK_SPECS_BY_SECTION:
                raise CommandError(
                    f"{path}: unknown section {line!r} "
                    f"(expected one of {', '.join(DEFAULT_TRACK_ORDER)})"
                )
            sections.setdefault(current, [])
            continue
        if current is None:
            if not line or line.startswith("#"):
                continue
            raise CommandError(
                f"{path}: event line outside a track section: {raw!r}"
            )
        sections[current].append(raw)

    parsed: dict[str, list[EventRow]] = {}
    for section, lines in sections.items():
        rows = parse_section_rows(path, lines, section=section)
        if rows:
            parsed[section] = rows
    return parsed


def parse_single_track_file(path: Path, *, item_label: str = "event") -> list[EventRow]:
    rows = parse_section_rows(
        path,
        path.read_text(encoding="utf-8").splitlines(),
        item_label=item_label,
    )
    if not rows:
        raise CommandError(f"{path}: no {item_label} lines found")
    return rows


def format_events_file(rows_by_section: dict[str, list[EventRow]]) -> str:
    parts: list[str] = []
    for section in DEFAULT_TRACK_ORDER:
        rows = rows_by_section.get(section)
        if not rows:
            continue
        parts.append(f"[{section}]")
        parts.extend(format_row(row) for row in rows)
        parts.append("")
    body = "\n".join(parts)
    if body:
        body += "\n"
    return body


def resolve_track_specs(track_filter: list[str] | None) -> list[TrackSpec]:
    if not track_filter:
        return list(TRACK_SPECS)

    specs: list[TrackSpec] = []
    for name in track_filter:
        section = name.strip().upper()
        spec = TRACK_SPECS_BY_SECTION.get(section)
        if spec is None:
            raise CommandError(
                f"Unknown track {name!r} — expected one of "
                f"{', '.join(DEFAULT_TRACK_ORDER)}"
            )
        specs.append(spec)
    return specs


def apply_cache_updates(updates_by_section: dict[str, dict[float, str]]) -> dict[str, int]:
    identity = _active_project_identity()
    payload = load_project_cache(identity)
    if payload is None:
        return {}

    timeline: Timeline = payload["timeline"]
    changed_counts: dict[str, int] = {}

    for section, updates in updates_by_section.items():
        if not updates:
            continue
        spec = TRACK_SPECS_BY_SECTION[section]
        events = getattr(timeline, spec.timeline_attr)
        changed = 0
        new_events: list[TimelineEvent] = []

        for evt in events:
            new_name = None
            for start, text in updates.items():
                if beats_match(start, evt.start_beat):
                    new_name = text
                    break
            if new_name is not None and new_name != evt.name:
                new_events.append(
                    TimelineEvent(
                        start_beat=evt.start_beat,
                        end_beat=evt.end_beat,
                        type=spec.event_type,
                        name=new_name,
                    )
                )
                changed += 1
            else:
                new_events.append(evt)

        if changed:
            getattr(timeline, spec.timeline_attr).clear()
            for evt in new_events:
                getattr(timeline, spec.timeline_attr).add(evt)
            changed_counts[section] = changed

    if changed_counts:
        project = payload.get("project") or {}
        effective_identity = identity or project.get("identity")
        if effective_identity:
            save_project_cache(
                identity=effective_identity,
                name=project.get("name", ""),
                file_path=project.get("file_path", ""),
                timeline=timeline,
                timeline_errors=payload["timeline_errors"],
                tempo=payload["tempo"],
                cue_points=payload["cue_points"],
                mixer_tracks=payload["mixer_tracks"],
            )
    return changed_counts


@dataclass
class LiveImportResult:
    section: str
    updated: int
    unchanged: int
    missing_in_live: list[float]
    extra_in_live: list[float]
    pending: dict[float, str]


def import_rows_to_live(
    *,
    section: str,
    track_id: int,
    clips: list[ArrangementClip],
    updates: dict[float, str],
    dry_run: bool,
    set_clip_name: Callable[[int, int, str], None],
    report_change: Callable[[float, str, str], None],
) -> LiveImportResult:
    clip_by_start: dict[float, tuple[int, str]] = {}
    for index, clip in enumerate(clips):
        clip_by_start[beat_key(clip.start_time)] = (index, clip.name)

    missing_in_live: list[float] = []
    unchanged = 0
    pending: dict[float, str] = {}

    for start, new_text in updates.items():
        match = None
        for clip_start, (index, old_text) in clip_by_start.items():
            if beats_match(start, clip_start):
                match = (index, old_text)
                break
        if match is None:
            missing_in_live.append(start)
            continue
        index, old_text = match
        if new_text == old_text:
            unchanged += 1
            continue
        pending[start] = new_text
        if dry_run:
            report_change(start, old_text, new_text)
        else:
            set_clip_name(track_id, index, new_text)

    extra_in_live = [
        start
        for start in clip_by_start
        if not any(beats_match(start, edited_start) for edited_start in updates)
    ]

    return LiveImportResult(
        section=section,
        updated=len(pending),
        unchanged=unchanged,
        missing_in_live=missing_in_live,
        extra_in_live=extra_in_live,
        pending=pending,
    )
