"""
Export and import clip names on semantic arrangement tracks for offline editing.

Usage:
    python manage.py events_io export events.txt
    python manage.py events_io import events.txt
    python manage.py events_io export chords.txt --tracks CHORDS
    python manage.py events_io import chords.txt --tracks CHORDS

Export reads from Ableton by default; use --from-cache if Live is not running.
Import pushes corrected clip names back into Ableton and updates the project cache.
Use --cache-only to update the cache without touching Live.

Tracks: SONGS, SECTIONS, LYRICS, CHORDS, CONTROL

File format (one clip per line within each section):
    [TRACK_NAME]
    start_beat|end_beat|clip name

Multi-line clip names are written on a single line; embedded line breaks use \\n.
Lines starting with # are comments. Only edit clip names — keep beat numbers
unchanged so import can match clips reliably.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from engine.config import get_app_settings
from engine.event_io import (
    DEFAULT_TRACK_ORDER,
    EVENTS_FILE_HEADER,
    EventRow,
    apply_cache_updates,
    beats_match,
    format_beat,
    format_events_file,
    import_rows_to_live,
    parse_events_file,
    resolve_track_specs,
    rows_from_cache_section,
    rows_from_clips,
)
from engine.osc_client import AbletonOSCClient
from engine.scanner import find_semantic_tracks, read_arrangement_clips, scan_tracks


class Command(BaseCommand):
    help = (
        "Export and import clip names on SONGS, SECTIONS, LYRICS, CHORDS, "
        "and CONTROL tracks."
    )

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="action", required=True)

        export_parser = subparsers.add_parser(
            "export",
            help="Write track events to a text file for offline editing",
        )
        export_parser.add_argument(
            "file",
            type=Path,
            help="Output path (e.g. events.txt)",
        )
        export_parser.add_argument(
            "--from-cache",
            action="store_true",
            help="Read from the saved project cache instead of Ableton",
        )
        export_parser.add_argument(
            "--tracks",
            type=str,
            default="",
            help="Comma-separated track list (default: all tracks)",
        )

        import_parser = subparsers.add_parser(
            "import",
            help="Apply edited events from a text file",
        )
        import_parser.add_argument(
            "file",
            type=Path,
            help="Edited events file",
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
        import_parser.add_argument(
            "--tracks",
            type=str,
            default="",
            help="Comma-separated track list to limit import (default: all in file)",
        )

    def handle(self, *args, **options):
        action: str = options["action"]
        if action == "export":
            self._export(options)
        else:
            self._import(options)

    @staticmethod
    def _parse_track_filter(raw: str) -> list[str] | None:
        if not raw.strip():
            return None
        return [part.strip() for part in raw.split(",") if part.strip()]

    def _export(self, options) -> None:
        path: Path = options["file"]
        from_cache: bool = options["from_cache"]
        track_specs = resolve_track_specs(self._parse_track_filter(options["tracks"]))

        rows_by_section: dict[str, list[EventRow]] = {}

        if from_cache:
            for spec in track_specs:
                rows = rows_from_cache_section(spec.section)
                if rows:
                    rows_by_section[spec.section] = rows
            source = "project cache"
        else:
            cfg = get_app_settings()
            osc = AbletonOSCClient(host=cfg.ableton_osc_host)
            osc.start()
            try:
                if not osc.is_connected():
                    raise CommandError(
                        "Live control surface not reachable — is Live running with "
                        "StageAble Bridge enabled? Use --from-cache to export the "
                        "last scan instead."
                    )

                tracks = scan_tracks(osc)
                semantic = find_semantic_tracks(tracks)
                source_parts: list[str] = []

                for spec in track_specs:
                    track = semantic.get(spec.scanner_key)
                    if track is None:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipping {spec.section}: track not found in Ableton"
                            )
                        )
                        continue
                    clips = read_arrangement_clips(osc, track.index)
                    if not clips:
                        continue
                    rows_by_section[spec.section] = rows_from_clips(clips)
                    source_parts.append(f"{spec.section} #{track.index}")

                if not rows_by_section:
                    raise CommandError(
                        "No arrangement clips found on the requested track(s)."
                    )
                source = "Ableton (" + ", ".join(source_parts) + ")"
            finally:
                osc.stop()

        body = format_events_file(rows_by_section)
        path.write_text(EVENTS_FILE_HEADER + body, encoding="utf-8")

        total = sum(len(rows) for rows in rows_by_section.values())
        summary = ", ".join(
            f"{section}: {len(rows_by_section[section])}"
            for section in DEFAULT_TRACK_ORDER
            if section in rows_by_section
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {total} event(s) from {source} to {path} ({summary})"
            )
        )

    def _import(self, options) -> None:
        path: Path = options["file"]
        cache_only: bool = options["cache_only"]
        dry_run: bool = options["dry_run"]
        track_filter = self._parse_track_filter(options["tracks"])

        if not path.is_file():
            raise CommandError(f"File not found: {path}")

        parsed = parse_events_file(path)
        if track_filter:
            allowed = {name.strip().upper() for name in track_filter}
            parsed = {
                section: rows for section, rows in parsed.items() if section in allowed
            }
        if not parsed:
            raise CommandError(f"{path}: no track sections found to import")

        updates_by_section = {
            section: {row.start_beat: row.text for row in rows}
            for section, rows in parsed.items()
        }

        if cache_only:
            if dry_run:
                self._report_cache_dry_run(parsed)
                return
            changed_counts = apply_cache_updates(updates_by_section)
            self._report_cache_import(changed_counts)
            return

        cfg = get_app_settings()
        osc = AbletonOSCClient(host=cfg.ableton_osc_host)
        osc.start()
        try:
            if not osc.is_connected():
                raise CommandError(
                    "Live control surface not reachable — is Live running with "
                    "StageAble Bridge enabled? Use --cache-only to update the "
                    "saved scan only."
                )

            tracks = scan_tracks(osc)
            semantic = find_semantic_tracks(tracks)
            pending_by_section: dict[str, dict[float, str]] = {}

            for section, updates in updates_by_section.items():
                spec = resolve_track_specs([section])[0]
                track = semantic.get(spec.scanner_key)
                if track is None:
                    raise CommandError(
                        f"No {section} track found in the Ableton set."
                    )

                clips = read_arrangement_clips(osc, track.index)
                if not clips:
                    raise CommandError(f"{section} track has no arrangement clips.")

                result = import_rows_to_live(
                    section=section,
                    track_id=track.index,
                    clips=clips,
                    updates=updates,
                    dry_run=dry_run,
                    set_clip_name=osc.set_arrangement_clip_name,
                    report_change=lambda start, old, new: self.stdout.write(
                        f"  [{section}] beat {format_beat(start)}: {old!r} -> {new!r}"
                    ),
                )
                pending_by_section[section] = result.pending

                if dry_run:
                    self.stdout.write(
                        f"[{section}] would update {result.updated}, "
                        f"{result.unchanged} unchanged, "
                        f"{len(result.missing_in_live)} unmatched in file, "
                        f"{len(result.extra_in_live)} only in Live"
                    )
                elif result.missing_in_live:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[{section}] skipped {len(result.missing_in_live)} "
                            "line(s) with no matching clip: "
                            + ", ".join(
                                format_beat(b) for b in result.missing_in_live
                            )
                        )
                    )

            if dry_run:
                return

            changed_counts = apply_cache_updates(pending_by_section)
            total_live = sum(len(p) for p in pending_by_section.values())
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {total_live} clip name(s) in Ableton "
                    f"({self._format_cache_summary(changed_counts)})"
                )
            )
        finally:
            osc.stop()

    def _report_cache_dry_run(self, parsed: dict[str, list[EventRow]]) -> None:
        total = 0
        for section, edited_rows in parsed.items():
            current = rows_from_cache_section(section)
            pending = 0
            for row in current:
                updates = {r.start_beat: r.text for r in edited_rows}
                new_text = None
                for start, text in updates.items():
                    if beats_match(start, row.start_beat):
                        new_text = text
                        break
                if new_text is not None and new_text != row.text:
                    pending += 1
                    total += 1
                    self.stdout.write(
                        f"  [{section}] beat {format_beat(row.start_beat)}: "
                        f"{row.text!r} -> {new_text!r}"
                    )
            self.stdout.write(
                f"[{section}] would update {pending} event(s) in the project cache"
            )
        self.stdout.write(f"Would update {total} event(s) in the project cache")

    def _report_cache_import(self, changed_counts: dict[str, int]) -> None:
        total = sum(changed_counts.values())
        if not changed_counts:
            self.stdout.write(self.style.SUCCESS("No changes in the project cache"))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {total} event(s) in the project cache "
                f"({self._format_cache_summary(changed_counts)})"
            )
        )

    @staticmethod
    def _format_cache_summary(changed_counts: dict[str, int]) -> str:
        parts = [
            f"{section}: {changed_counts[section]}"
            for section in DEFAULT_TRACK_ORDER
            if section in changed_counts
        ]
        return ", ".join(parts) if parts else "0 in cache"
