"""
Diagnose arrangement-clip OSC queries for a track.

Usage:
    python manage.py debug_clips --track 5
    python manage.py debug_clips --track LYRICS --verbose
    python manage.py debug_clips --track LYRICS --timeout 15
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from engine.config import get_app_settings
from engine.osc_client import AbletonOSCClient
from engine.scanner import scan_tracks

_ARRANGEMENT_CLIP_QUERIES = ("start_time", "length", "name")
_ARRANGEMENT_CLIP_ADDRESS = "/live/track/get/arrangement_clips/{field}"
_ARRANGEMENT_CLIP_NAME_CHUNK = "/live/track/get/arrangement_clips/name_chunk"
_METER_AT_BEATS = "/live/song/get/meter_at_beats"
_TRACK_DATA_ADDRESS = "/live/song/get/track_data"
_OSC_SIZE_WARN_8K = 8192
_OSC_SIZE_WARN_64K = 65507


@dataclass
class QueryResult:
    field: str
    ok: bool
    elapsed_ms: float
    clip_count: int
    reply: list[Any] | None


@dataclass
class TrackDataResult:
    label: str
    properties: list[str]
    ok: bool
    elapsed_ms: float
    reply: list[Any] | None
    parsed: dict[str, Any] = field(default_factory=dict)


def _osc_padded_string_bytes(s: str) -> int:
    """Byte size of one OSC string argument (length prefix + data + padding)."""
    raw = s.encode("utf-8") + b"\0"
    return 4 + ((len(raw) + 3) // 4) * 4


def estimate_arrangement_name_reply_bytes(names: list[str]) -> int:
    """Rough lower bound for the OSC reply payload (address + type tags + args)."""
    address = _ARRANGEMENT_CLIP_ADDRESS.format(field="name")
    total = _osc_padded_string_bytes(address)
    # Type tag string: comma + one type char per argument, padded.
    type_tag = "," + "s" + "i" + "s" * len(names)
    total += _osc_padded_string_bytes(type_tag)
    total += 4  # track_id int
    for name in names:
        total += _osc_padded_string_bytes(name)
    return total


def _estimate_reply_bytes(values: list[Any]) -> int:
    total = _osc_padded_string_bytes(_TRACK_DATA_ADDRESS)
    for value in values:
        if isinstance(value, str):
            total += _osc_padded_string_bytes(value)
        elif isinstance(value, (int, float)):
            total += 4
        elif value is None:
            total += 4
    return total


def _resolve_track_id(osc: AbletonOSCClient, track: str) -> tuple[int, str]:
    if track.isdigit():
        track_id = int(track)
        name = osc.get_track_name(track_id)
        if name is None:
            raise CommandError(f"Track index {track_id} not found or unreadable")
        return track_id, name

    needle = track.strip().lower()
    for info in scan_tracks(osc):
        if info.name.strip().lower() == needle:
            return info.index, info.name
    raise CommandError(f"No track named '{track}' found")


def _query_arrangement_field(
    osc: AbletonOSCClient,
    track_id: int,
    field: str,
    *,
    timeout: float,
) -> QueryResult:
    address = _ARRANGEMENT_CLIP_ADDRESS.format(field=field)
    t0 = time.monotonic()
    reply = osc.query(address, track_id, timeout=timeout, warn_timeout=False)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    clip_count = len(reply) - 1 if reply else 0
    return QueryResult(
        field=field,
        ok=reply is not None,
        elapsed_ms=elapsed_ms,
        clip_count=clip_count,
        reply=reply,
    )


def _parse_single_track_data(reply: list[Any], properties: list[str]) -> dict[str, Any]:
    """Parse track_data for one track (track_index_min .. track_index_max)."""
    cursor = 0
    parsed: dict[str, Any] = {}
    clip_props = [p for p in properties if p.startswith("clip.")]
    clip_prop_count = len(clip_props)

    for prop in properties:
        obj, _ = prop.split(".", 1)
        if obj == "track":
            parsed[prop] = reply[cursor] if cursor < len(reply) else None
            cursor += 1
        elif obj == "clip":
            if clip_prop_count == 0:
                parsed[prop] = []
                continue
            remaining = len(reply) - cursor
            values_for_this_prop = remaining // clip_prop_count
            parsed[prop] = reply[cursor : cursor + values_for_this_prop]
            cursor += values_for_this_prop

    non_null_clip_names = [
        v for v in parsed.get("clip.name", []) if v is not None and str(v) != ""
    ]
    return {
        **parsed,
        "session_slot_count": len(parsed.get("clip.name", [])),
        "session_clips_with_names": len(non_null_clip_names),
        "values_consumed": cursor,
        "values_total": len(reply),
    }


def _query_track_data(
    osc: AbletonOSCClient,
    track_index_min: int,
    track_index_max: int,
    properties: list[str],
    *,
    label: str,
    timeout: float,
) -> TrackDataResult:
    t0 = time.monotonic()
    reply = osc.query(
        _TRACK_DATA_ADDRESS,
        track_index_min,
        track_index_max,
        *properties,
        timeout=timeout,
        warn_timeout=False,
    )
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    track_count = track_index_max - track_index_min
    parsed: dict[str, Any] = {}
    if reply is not None:
        if track_count == 1:
            parsed = _parse_single_track_data(reply, properties)
        else:
            parsed = {"raw_len": len(reply), "track_count": track_count}

    return TrackDataResult(
        label=label,
        properties=properties,
        ok=reply is not None,
        elapsed_ms=elapsed_ms,
        reply=reply,
        parsed=parsed,
    )


class Command(BaseCommand):
    help = (
        "Diagnose arrangement-clip OSC queries (start_time, length, name) "
        "and compare with /live/song/get/track_data"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--track",
            required=True,
            help="Track index (e.g. 5) or name (e.g. LYRICS)",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=15.0,
            help="Seconds to wait per query (default: 15)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print first/last 3 clip names and start times when available",
        )
        parser.add_argument(
            "--skip-track-data",
            action="store_true",
            help="Skip /live/song/get/track_data probes",
        )

    def handle(self, *args, **options):
        track_arg: str = options["track"]
        timeout: float = options["timeout"]
        verbose: bool = options["verbose"]
        skip_track_data: bool = options["skip_track_data"]

        cfg = get_app_settings()
        osc = AbletonOSCClient(host=cfg.ableton_osc_host)
        osc.start()
        try:
            if not osc.is_connected():
                raise CommandError(
                    "Live control surface not reachable — is Live running with "
                    "ShowAble Bridge enabled?"
                )

            track_id, track_name = _resolve_track_id(osc, track_arg)
            self.stdout.write(
                f"Track #{track_id} ({track_name}) — timeout {timeout}s per query\n"
            )

            self.stdout.write("Arrangement clip endpoints:\n")
            results: dict[str, QueryResult] = {}
            for field in _ARRANGEMENT_CLIP_QUERIES:
                result = _query_arrangement_field(
                    osc, track_id, field, timeout=timeout
                )
                results[field] = result
                status = "OK" if result.ok else "TIMEOUT"
                self.stdout.write(
                    f"  {field:11} {status:7}  clips={result.clip_count:4d}  "
                    f"{result.elapsed_ms:7.0f} ms"
                )

            chunk_result = self._run_name_chunk_probe(osc, track_id, timeout=timeout)
            if chunk_result is not None:
                results["name_chunk_full"] = chunk_result

            track_data_results: list[TrackDataResult] = []
            if not skip_track_data:
                track_data_results = self._run_track_data_probes(
                    osc, track_id, timeout=timeout
                )

            self._run_meter_at_beats_probe(osc, timeout=timeout)

            self._print_diagnosis(results, track_data_results)

            if verbose:
                self._print_verbose(results, track_data_results)

        finally:
            osc.stop()

    def _run_name_chunk_probe(
        self,
        osc: AbletonOSCClient,
        track_id: int,
        *,
        timeout: float,
    ) -> QueryResult | None:
        """Probe name_chunk and, if supported, read all names via the client helper."""
        self.stdout.write("\nArrangement clip name_chunk (ShowAble Bridge):\n")

        t0 = time.monotonic()
        probe = osc.query(
            _ARRANGEMENT_CLIP_NAME_CHUNK,
            track_id,
            0,
            1,
            timeout=timeout,
            warn_timeout=False,
        )
        probe_ms = (time.monotonic() - t0) * 1000.0
        if probe is None:
            self.stdout.write(
                f"  probe offset=0 limit=1     MISSING  {probe_ms:7.0f} ms\n"
                "  Install the bridge: python scripts/install_bridge.py"
            )
            return None

        total = int(probe[2]) if len(probe) > 2 else 0
        self.stdout.write(
            f"  probe offset=0 limit=1     OK       total={total}  {probe_ms:7.0f} ms"
        )

        t0 = time.monotonic()
        names = osc.get_arrangement_clip_names(track_id)
        full_ms = (time.monotonic() - t0) * 1000.0
        ok = names is not None
        count = len(names) if names else 0
        status = "OK" if ok else "FAIL"
        self.stdout.write(
            f"  get_arrangement_clip_names() {status:7}  clips={count:4d}  "
            f"{full_ms:7.0f} ms"
        )
        return QueryResult(
            field="name_chunk_full",
            ok=ok,
            elapsed_ms=full_ms,
            clip_count=count,
            reply=[track_id, *names] if names else None,
        )

    def _run_meter_at_beats_probe(
        self,
        osc: AbletonOSCClient,
        *,
        timeout: float,
    ) -> None:
        """Probe the batched meter endpoint provided by ShowAble Bridge."""
        self.stdout.write("\nMeter at beats (ShowAble Bridge):\n")

        t0 = time.monotonic()
        probe = osc.query(_METER_AT_BEATS, 0.0, 4.0, 8.0, timeout=timeout, warn_timeout=False)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        if probe is None:
            self.stdout.write(
                f"  probe beats 0 4 8        MISSING  {elapsed_ms:7.0f} ms\n"
                "  Install the bridge: python scripts/install_bridge.py"
            )
            return

        if len(probe) < 2 or int(probe[0]) != 1:
            self.stdout.write(
                f"  probe beats 0 4 8        FAIL     {elapsed_ms:7.0f} ms\n"
                f"  Reply: {probe!r}"
            )
            return

        count = int(probe[1])
        samples = []
        idx = 2
        for _ in range(count):
            if idx + 3 >= len(probe):
                break
            beat = float(probe[idx])
            num = int(probe[idx + 1])
            den = int(probe[idx + 2])
            tempo = float(probe[idx + 3])
            samples.append(f"{beat:g}→{num}/{den}@{tempo:g}")
            idx += 4

        detail = ", ".join(samples) if samples else "(no samples)"
        self.stdout.write(
            f"  probe beats 0 4 8        OK       {elapsed_ms:7.0f} ms\n"
            f"  samples: {detail}"
        )

    def _run_track_data_probes(
        self,
        osc: AbletonOSCClient,
        track_id: int,
        *,
        timeout: float,
    ) -> list[TrackDataResult]:
        self.stdout.write("\n/live/song/get/track_data probes:\n")
        self.stdout.write(
            "  (AbletonOSC clip.* properties refer to Session View clip slots, "
            "not arrangement clips.)\n"
        )

        probes: list[tuple[str, list[str]]] = [
            ("track.name only", ["track.name"]),
            (
                "session clip.name + clip.length",
                ["track.name", "clip.name", "clip.length"],
            ),
            (
                "session clip.name + clip.length + clip.start_time",
                ["track.name", "clip.name", "clip.length", "clip.start_time"],
            ),
        ]

        results: list[TrackDataResult] = []
        for label, properties in probes:
            result = _query_track_data(
                osc,
                track_id,
                track_id + 1,
                properties,
                label=label,
                timeout=timeout,
            )
            results.append(result)
            status = "OK" if result.ok else "TIMEOUT"
            reply_len = len(result.reply) if result.reply else 0
            self.stdout.write(
                f"  {label:40} {status:7}  values={reply_len:4d}  "
                f"{result.elapsed_ms:7.0f} ms"
            )
            if result.ok and result.parsed:
                slots = result.parsed.get("session_slot_count")
                named = result.parsed.get("session_clips_with_names")
                if slots is not None:
                    self.stdout.write(
                        f"    session slots={slots}  "
                        f"slots with clip names={named}"
                    )
                if result.reply:
                    est = _estimate_reply_bytes(result.reply)
                    self.stdout.write(f"    estimated reply size: ~{est} B")
                    if "clip.name" in result.parsed:
                        names = [
                            str(v)
                            for v in result.parsed["clip.name"]
                            if v is not None
                        ]
                        if names:
                            utf8 = sum(len(n.encode("utf-8")) for n in names)
                            self.stdout.write(
                                f"    session clip name UTF-8 total: {utf8} B"
                            )

        return results

    def _print_diagnosis(
        self,
        results: dict[str, QueryResult],
        track_data_results: list[TrackDataResult],
    ) -> None:
        start = results["start_time"]
        length = results["length"]
        name = results["name"]

        self.stdout.write("")

        if start.ok and length.ok and not name.ok:
            self.stdout.write(
                self.style.WARNING(
                    "Numeric arrangement clip data readable; bulk "
                    "/live/track/get/arrangement_clips/name likely exceeds "
                    "OSC limit or failed to send."
                )
            )
            chunk_full = results.get("name_chunk_full")
            if chunk_full and chunk_full.ok:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Chunked name_chunk API recovered {chunk_full.clip_count} "
                        "clip names — ShowAble Bridge is working."
                    )
                )
            elif chunk_full is None or not chunk_full.ok:
                self.stdout.write(
                    self.style.WARNING(
                        "Run: python scripts/install_bridge.py "
                        "(then restart Live)"
                    )
                )

        session_named = 0
        for td in track_data_results:
            if td.ok and td.parsed:
                session_named = max(
                    session_named, td.parsed.get("session_clips_with_names", 0)
                )

        if start.ok and start.clip_count > 0 and session_named == 0:
            self.stdout.write(
                "track_data session clip slots are empty on this track — "
                "lyrics live in Arrangement View only; use arrangement_clips "
                "endpoints (with the ShowAble name_chunk patch for large tracks)."
            )
        elif session_named > 0 and start.clip_count != session_named:
            self.stdout.write(
                self.style.WARNING(
                    f"Arrangement clips={start.clip_count} vs session clips "
                    f"with names={session_named} — views differ."
                )
            )

        track_data_names_ok = any(
            td.ok
            and td.parsed.get("session_clips_with_names", 0) > 0
            for td in track_data_results
        )
        if track_data_names_ok and not name.ok:
            self.stdout.write(
                self.style.WARNING(
                    "track_data returned session clip names but arrangement "
                    "clip names still failed — track_data cannot replace "
                    "arrangement_clips for this track."
                )
            )

        if name.ok and name.reply:
            names = [str(v) for v in name.reply[1:]]
        else:
            chunk_full = results.get("name_chunk_full")
            if chunk_full and chunk_full.ok and chunk_full.reply:
                names = [str(v) for v in chunk_full.reply[1:]]
            else:
                names = []

        if names:
            if name.ok and not names:
                self.stdout.write("Name query succeeded but returned zero clip names.")
                return

            char_lengths = [len(n) for n in names]
            utf8_lengths = [len(n.encode("utf-8")) for n in names]
            total_utf8 = sum(utf8_lengths)
            estimated = estimate_arrangement_name_reply_bytes(names)

            self.stdout.write(
                f"Names: count={len(names)}  "
                f"chars min/avg/max={min(char_lengths)}/"
                f"{sum(char_lengths) // len(names)}/{max(char_lengths)}  "
                f"total UTF-8={total_utf8} B"
            )
            self.stdout.write(f"Estimated OSC reply size: ~{estimated} B")

            for threshold, label in (
                (_OSC_SIZE_WARN_8K, "8 KiB"),
                (_OSC_SIZE_WARN_64K, "64 KiB"),
            ):
                if estimated > threshold:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  exceeds common {label} OSC/UDP threshold ({threshold} B)"
                        )
                    )

            null_names = [i for i, n in enumerate(names) if "\0" in n]
            if null_names:
                self.stdout.write(
                    self.style.ERROR(
                        f"Clip names contain null bytes at indices: {null_names[:10]}"
                    )
                )

        elif not start.ok and not length.ok and not name.ok:
            self.stdout.write(
                self.style.ERROR(
                    "All arrangement clip queries failed — check the Live control "
                    "surface / Live for errors on this track."
                )
            )

        if start.ok and length.ok and name.ok:
            if (
                start.clip_count != length.clip_count
                or start.clip_count != name.clip_count
            ):
                self.stdout.write(
                    self.style.WARNING(
                        f"Clip count mismatch: start_time={start.clip_count} "
                        f"length={length.clip_count} name={name.clip_count}"
                    )
                )

    def _print_verbose(
        self,
        results: dict[str, QueryResult],
        track_data_results: list[TrackDataResult],
    ) -> None:
        self.stdout.write("\nVerbose sample:")

        if results["start_time"].ok and results["start_time"].reply:
            starts = [float(v) for v in results["start_time"].reply[1:]]
            self.stdout.write(f"  arrangement start_time first 3: {starts[:3]}")
            if len(starts) > 3:
                self.stdout.write(f"  arrangement start_time last  3: {starts[-3:]}")

        if results["name"].ok and results["name"].reply:
            names = [str(v) for v in results["name"].reply[1:]]
        else:
            chunk_full = results.get("name_chunk_full")
            if chunk_full and chunk_full.ok and chunk_full.reply:
                names = [str(v) for v in chunk_full.reply[1:]]
            else:
                names = []

        if names:
            for label, sample in (("first 3", names[:3]), ("last 3", names[-3:])):
                self.stdout.write(f"  arrangement name {label}:")
                for i, n in enumerate(sample):
                    preview = n if len(n) <= 80 else n[:77] + "..."
                    self.stdout.write(f"    [{i}] {preview!r}")

        for td in track_data_results:
            if not td.ok or "clip.name" not in td.parsed:
                continue
            names = [
                str(v)
                for v in td.parsed["clip.name"]
                if v is not None and str(v) != ""
            ]
            if not names:
                continue
            self.stdout.write(f"  track_data ({td.label}) session clip names:")
            for n in names[:3]:
                preview = n if len(n) <= 80 else n[:77] + "..."
                self.stdout.write(f"    {preview!r}")
