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

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from engine.config import get_app_settings
from engine.event_io import (
    LYRICS_FILE_HEADER,
    EventRow,
    apply_cache_updates,
    beats_match,
    format_beat,
    format_row,
    import_rows_to_live,
    parse_single_track_file,
    rows_from_cache_section,
    rows_from_clips,
)
from engine.osc_client import AbletonOSCClient
from engine.scanner import (
    TRACK_LYRICS,
    find_semantic_tracks,
    read_arrangement_clips,
    scan_tracks,
)


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
            rows = rows_from_cache_section("LYRICS")
            source = "project cache"
        else:
            cfg = get_app_settings()
            osc = AbletonOSCClient(host=cfg.ableton_osc_host)
            osc.start()
            try:
                if not osc.is_connected():
                    raise CommandError(
                        "Live control surface not reachable — is Live running with "
                        "RemoteAble Bridge enabled? Use --from-cache to export the "
                        "last scan instead."
                    )
                track_id = self._find_lyrics_track(osc)
                clips = read_arrangement_clips(osc, track_id)
                if not clips:
                    raise CommandError("LYRICS track has no arrangement clips.")
                rows = rows_from_clips(clips)
                source = f"Ableton track {track_id}"
            finally:
                osc.stop()

        body = "\n".join(format_row(row) for row in rows) + "\n"
        path.write_text(LYRICS_FILE_HEADER + body, encoding="utf-8")
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

        edited = parse_single_track_file(path, item_label="lyric")
        updates = {row.start_beat: row.text for row in edited}

        if cache_only:
            if dry_run:
                current = rows_from_cache_section("LYRICS")
                self._report_dry_run(current, updates)
                return
            changed_counts = apply_cache_updates({"LYRICS": updates})
            changed = changed_counts.get("LYRICS", 0)
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
                    "Live control surface not reachable — is Live running with "
                    "RemoteAble Bridge enabled? Use --cache-only to update the "
                    "saved scan only."
                )

            track_id = self._find_lyrics_track(osc)
            clips = read_arrangement_clips(osc, track_id)
            if not clips:
                raise CommandError("LYRICS track has no arrangement clips.")

            result = import_rows_to_live(
                section="LYRICS",
                track_id=track_id,
                clips=clips,
                updates=updates,
                dry_run=dry_run,
                set_clip_name=osc.set_arrangement_clip_name,
                report_change=lambda start, old, new: self.stdout.write(
                    f"  beat {format_beat(start)}: {old!r} -> {new!r}"
                ),
            )

            if dry_run:
                self.stdout.write(
                    f"Would update {result.updated} lyric(s), "
                    f"{result.unchanged} unchanged, "
                    f"{len(result.missing_in_live)} unmatched in file, "
                    f"{len(result.extra_in_live)} only in Live"
                )
                if result.missing_in_live:
                    self.stdout.write(
                        self.style.WARNING(
                            "No matching clip for beats: "
                            + ", ".join(
                                format_beat(b) for b in result.missing_in_live
                            )
                        )
                    )
                return

            if result.missing_in_live:
                self.stdout.write(
                    self.style.WARNING(
                        "Skipped "
                        f"{len(result.missing_in_live)} line(s) with no matching clip: "
                        + ", ".join(format_beat(b) for b in result.missing_in_live)
                    )
                )

            changed_counts = apply_cache_updates({"LYRICS": result.pending})
            cache_changed = changed_counts.get("LYRICS", 0)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {result.updated} clip name(s) in Ableton "
                    f"({result.unchanged} unchanged, {cache_changed} in project cache)"
                )
            )
        finally:
            osc.stop()

    def _find_lyrics_track(self, osc: AbletonOSCClient) -> int:
        tracks = scan_tracks(osc)
        semantic = find_semantic_tracks(tracks)
        lyrics_track = semantic.get(TRACK_LYRICS)
        if lyrics_track is None:
            raise CommandError(
                "No LYRICS track found in the Ableton set — add a track named LYRICS."
            )
        return lyrics_track.index

    def _report_dry_run(
        self, current: list[EventRow], updates: dict[float, str]
    ) -> None:
        pending = 0
        for row in current:
            new_text = None
            for start, text in updates.items():
                if beats_match(start, row.start_beat):
                    new_text = text
                    break
            if new_text is not None and new_text != row.text:
                pending += 1
                self.stdout.write(
                    f"  beat {format_beat(row.start_beat)}: "
                    f"{row.text!r} -> {new_text!r}"
                )
        self.stdout.write(f"Would update {pending} lyric(s) in the project cache")
