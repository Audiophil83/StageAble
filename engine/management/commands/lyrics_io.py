"""
Export and import LYRICS track clip names for offline editing.

Usage:
    python manage.py lyrics_io export lyrics.txt
    python manage.py lyrics_io import lyrics.txt

Export reads from Ableton by default; use --from-cache if Live is not running.
Import pushes corrected text back into Ableton clip names and updates the project
cache. Use --cache-only to update the cache without touching Live.

File format (one lyric cue per line):
    start_beat|end_beat|lyric text

Multi-line clip names are written on a single line; embedded line breaks use \\n.
Lines starting with # are comments. Only edit the lyric text — keep the beat
numbers unchanged so import can match clips reliably.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from engine.config import get_app_settings
from engine.osc_client import AbletonOSCClient
from engine.project_cache import load_project_cache, save_project_cache
from engine.scanner import (
    TRACK_LYRICS,
    find_semantic_tracks,
    read_arrangement_clips,
    scan_tracks,
)
from engine.timeline import EventType, TimelineEvent

_BEAT_TOLERANCE = 0.01
_FILE_HEADER = """# Remoteable lyrics
# Format: start_beat|end_beat|lyric text
# Edit only the lyric text (after the second |). Do not change beat numbers.
# Use \\n in the text for a line break within one lyric cue.
# Lines starting with # are ignored.
#
"""


@dataclass(frozen=True)
class LyricRow:
    start_beat: float
    end_beat: float | None
    text: str


def _beat_key(beat: float) -> float:
    return round(beat, 4)


def _rows_from_clips(clips) -> list[LyricRow]:
    rows = [
        LyricRow(
            start_beat=clip.start_time,
            end_beat=clip.start_time + clip.length,
            text=clip.name,
        )
        for clip in clips
    ]
    rows.sort(key=lambda row: row.start_beat)
    return rows


def _rows_from_cache() -> list[LyricRow]:
    payload = load_project_cache()
    if payload is None:
        raise CommandError(
            "No project cache found — scan the arrangement in Remoteable first, "
            "or export from Ableton without --from-cache."
        )

    rows: list[LyricRow] = []
    for evt in payload["timeline"].lyrics:
        rows.append(
            LyricRow(
                start_beat=evt.start_beat,
                end_beat=evt.end_beat,
                text=evt.name,
            )
        )
    rows.sort(key=lambda row: row.start_beat)
    return rows


def _escape_text(text: str) -> str:
    """Keep each lyric cue on one file line."""
    return (
        text.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _unescape_text(text: str) -> str:
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


def _parse_timestamp_line(line: str) -> tuple[float, float | None, str] | None:
    """Return (start, end, text) when *line* is a timestamped lyric row."""
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

    return start_beat, end_beat, _unescape_text(parts[2])


def _format_row(row: LyricRow) -> str:
    end = "" if row.end_beat is None else f"{row.end_beat:g}"
    return f"{row.start_beat:g}|{end}|{_escape_text(row.text)}"


def _parse_file(path: Path) -> list[LyricRow]:
    rows: list[LyricRow] = []
    seen_starts: set[float] = set()

    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parsed = _parse_timestamp_line(line)
        if parsed is not None:
            start_beat, end_beat, text = parsed
            key = _beat_key(start_beat)
            if key in seen_starts:
                raise CommandError(
                    f"{path}:{line_no}: duplicate start beat {_format_beat(start_beat)}"
                )
            seen_starts.add(key)
            rows.append(LyricRow(start_beat=start_beat, end_beat=end_beat, text=text))
            continue

        if not rows:
            raise CommandError(
                f"{path}:{line_no}: lyric line without a timestamp: {raw!r}"
            )

        prev = rows[-1]
        rows[-1] = LyricRow(
            start_beat=prev.start_beat,
            end_beat=prev.end_beat,
            text=prev.text + "\n" + line,
        )

    if not rows:
        raise CommandError(f"{path}: no lyric lines found")
    return rows


def _format_beat(beat: float) -> str:
    return f"{beat:g}"


def _beats_match(a: float, b: float) -> bool:
    return abs(a - b) <= _BEAT_TOLERANCE


def _find_lyrics_track(osc: AbletonOSCClient) -> int:
    tracks = scan_tracks(osc)
    semantic = find_semantic_tracks(tracks)
    lyrics_track = semantic.get(TRACK_LYRICS)
    if lyrics_track is None:
        raise CommandError(
            "No LYRICS track found in the Ableton set — add a track named LYRICS."
        )
    return lyrics_track.index


def _apply_cache_updates(updates: dict[float, str]) -> int:
    payload = load_project_cache()
    if payload is None:
        return 0

    timeline = payload["timeline"]
    changed = 0
    new_lyrics: list[TimelineEvent] = []
    for evt in timeline.lyrics:
        key = _beat_key(evt.start_beat)
        new_name = None
        for start, text in updates.items():
            if _beats_match(start, evt.start_beat):
                new_name = text
                break
        if new_name is not None and new_name != evt.name:
            new_lyrics.append(
                TimelineEvent(
                    start_beat=evt.start_beat,
                    end_beat=evt.end_beat,
                    type=EventType.LYRIC,
                    name=new_name,
                )
            )
            changed += 1
        else:
            new_lyrics.append(evt)

    if changed:
        timeline.lyrics.clear()
        for evt in new_lyrics:
            timeline.lyrics.add(evt)
        save_project_cache(
            timeline=timeline,
            timeline_errors=payload["timeline_errors"],
            tempo=payload["tempo"],
            cue_points=payload["cue_points"],
            mixer_tracks=payload["mixer_tracks"],
        )
    return changed


class Command(BaseCommand):
    help = "Export LYRICS clip names to a text file and import corrections back."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="action", required=True)

        export_parser = subparsers.add_parser(
            "export",
            help="Write lyrics to a text file for offline editing",
        )
        export_parser.add_argument(
            "file",
            type=Path,
            help="Output path (e.g. lyrics.txt)",
        )
        export_parser.add_argument(
            "--from-cache",
            action="store_true",
            help="Read from the saved project cache instead of Ableton",
        )

        import_parser = subparsers.add_parser(
            "import",
            help="Apply edited lyrics from a text file",
        )
        import_parser.add_argument(
            "file",
            type=Path,
            help="Edited lyrics file",
        )
        import_parser.add_argument(
            "--cache-only",
            action="store_true",
            help="Update the project cache only (do not write to Ableton)",
        )
        import_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing",
        )

    def handle(self, *args, **options):
        action: str = options["action"]
        if action == "export":
            self._export(options)
        else:
            self._import(options)

    def _export(self, options) -> None:
        path: Path = options["file"]
        from_cache: bool = options["from_cache"]

        if from_cache:
            rows = _rows_from_cache()
            source = "project cache"
        else:
            cfg = get_app_settings()
            osc = AbletonOSCClient(host=cfg.ableton_osc_host)
            osc.start()
            try:
                if not osc.is_connected():
                    raise CommandError(
                        "AbletonOSC not reachable — is Live running with AbletonOSC "
                        "enabled? Use --from-cache to export the last scan instead."
                    )
                track_id = _find_lyrics_track(osc)
                clips = read_arrangement_clips(osc, track_id)
                if not clips:
                    raise CommandError("LYRICS track has no arrangement clips.")
                rows = _rows_from_clips(clips)
                source = f"Ableton track {track_id}"
            finally:
                osc.stop()

        body = "\n".join(_format_row(row) for row in rows) + "\n"
        path.write_text(_FILE_HEADER + body, encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(rows)} lyrics from {source} to {path}"
            )
        )

    def _import(self, options) -> None:
        path: Path = options["file"]
        cache_only: bool = options["cache_only"]
        dry_run: bool = options["dry_run"]

        if not path.is_file():
            raise CommandError(f"File not found: {path}")

        edited = _parse_file(path)
        updates = {row.start_beat: row.text for row in edited}

        if cache_only:
            if dry_run:
                current = _rows_from_cache()
                self._report_dry_run(current, updates)
                return
            changed = _apply_cache_updates(updates)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {changed} lyric(s) in the project cache"
                )
            )
            return

        cfg = get_app_settings()
        osc = AbletonOSCClient(host=cfg.ableton_osc_host)
        osc.start()
        try:
            if not osc.is_connected():
                raise CommandError(
                    "AbletonOSC not reachable — is Live running with AbletonOSC "
                    "enabled? Use --cache-only to update the saved scan only."
                )

            track_id = _find_lyrics_track(osc)
            clips = read_arrangement_clips(osc, track_id)
            if not clips:
                raise CommandError("LYRICS track has no arrangement clips.")

            clip_by_start: dict[float, tuple[int, str]] = {}
            for index, clip in enumerate(clips):
                key = _beat_key(clip.start_time)
                clip_by_start[key] = (index, clip.name)

            missing_in_live: list[float] = []
            unchanged = 0
            pending: dict[float, str] = {}

            for start, new_text in updates.items():
                match = None
                for clip_start, (index, old_text) in clip_by_start.items():
                    if _beats_match(start, clip_start):
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
                    self.stdout.write(
                        f"  beat {_format_beat(start)}: {old_text!r} -> {new_text!r}"
                    )
                else:
                    osc.set_arrangement_clip_name(track_id, index, new_text)

            extra_in_live = [
                start
                for start in clip_by_start
                if not any(_beats_match(start, edited_start) for edited_start in updates)
            ]

            if dry_run:
                self.stdout.write(
                    f"Would update {len(pending)} lyric(s), "
                    f"{unchanged} unchanged, "
                    f"{len(missing_in_live)} unmatched in file, "
                    f"{len(extra_in_live)} only in Live"
                )
                if missing_in_live:
                    self.stdout.write(
                        self.style.WARNING(
                            "No matching clip for beats: "
                            + ", ".join(_format_beat(b) for b in missing_in_live)
                        )
                    )
                return

            if missing_in_live:
                self.stdout.write(
                    self.style.WARNING(
                        "Skipped "
                        f"{len(missing_in_live)} line(s) with no matching clip: "
                        + ", ".join(_format_beat(b) for b in missing_in_live)
                    )
                )

            cache_changed = _apply_cache_updates(pending)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {len(pending)} clip name(s) in Ableton "
                    f"({unchanged} unchanged, {cache_changed} in project cache)"
                )
            )
        finally:
            osc.stop()

    def _report_dry_run(
        self, current: list[LyricRow], updates: dict[float, str]
    ) -> None:
        pending = 0
        for row in current:
            new_text = updates.get(row.start_beat)
            if new_text is None:
                for start, text in updates.items():
                    if _beats_match(start, row.start_beat):
                        new_text = text
                        break
            if new_text is not None and new_text != row.text:
                pending += 1
                self.stdout.write(
                    f"  beat {_format_beat(row.start_beat)}: "
                    f"{row.text!r} -> {new_text!r}"
                )
        self.stdout.write(f"Would update {pending} lyric(s) in the project cache")
