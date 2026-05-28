"""
Timeline Engine — builds an in-memory timeline from Ableton arrangement data
and resolves active events for any given playhead position.

The timeline is a flat sorted list of ``TimelineEvent`` objects.  At runtime
the engine performs interval lookups to determine which song, section, lyrics,
chords, and control events are active.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sortedcontainers import SortedList

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    SONG = "SONG"
    SECTION = "SECTION"
    LYRIC = "LYRIC"
    CHORD = "CHORD"
    STOP = "STOP"


@dataclass(frozen=True, order=True)
class TimelineEvent:
    """A single event on the arrangement timeline.

    Ordering is by ``start_beat`` so we can binary-search efficiently.
    """

    start_beat: float
    type: EventType = field(compare=False)
    name: str = field(compare=False, default="")
    end_beat: Optional[float] = field(compare=False, default=None)

    @property
    def duration(self) -> float | None:
        if self.end_beat is not None:
            return self.end_beat - self.start_beat
        return None

    def contains(self, beat: float) -> bool:
        """Return True if *beat* falls within [start_beat, end_beat)."""
        if self.end_beat is None:
            return beat >= self.start_beat
        return self.start_beat <= beat < self.end_beat


@dataclass
class ArrangementClip:
    """Raw clip data as read from AbletonOSC."""

    name: str
    start_time: float  # beats
    length: float  # beats


@dataclass
class Timeline:
    """Full arrangement timeline with typed event lists.

    Provides fast lookup of active events by playhead position.
    """

    songs: SortedList = field(default_factory=lambda: SortedList(key=lambda e: e.start_beat))
    sections: SortedList = field(default_factory=lambda: SortedList(key=lambda e: e.start_beat))
    lyrics: SortedList = field(default_factory=lambda: SortedList(key=lambda e: e.start_beat))
    chords: SortedList = field(default_factory=lambda: SortedList(key=lambda e: e.start_beat))
    stops: SortedList = field(default_factory=lambda: SortedList(key=lambda e: e.start_beat))

    # Validation state
    errors: list[str] = field(default_factory=list)
    is_valid: bool = field(default=True)

    # ── building ─────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        song_clips: list[ArrangementClip],
        section_clips: list[ArrangementClip] | None = None,
        lyric_clips: list[ArrangementClip] | None = None,
        control_clips: list[ArrangementClip] | None = None,
        chord_clips: list[ArrangementClip] | None = None,
    ) -> Timeline:
        """Construct a validated Timeline from raw clip data."""
        tl = cls()

        # -- SONGS (mandatory) -----------------------------------------
        if not song_clips:
            tl.errors.append("No clips found on SONGS track.")
            tl.is_valid = False
        else:
            # Sort by start_time for validation
            sorted_songs = sorted(song_clips, key=lambda c: c.start_time)
            for i, clip in enumerate(sorted_songs):
                end = clip.start_time + clip.length
                evt = TimelineEvent(
                    start_beat=clip.start_time,
                    end_beat=end,
                    type=EventType.SONG,
                    name=clip.name,
                )
                tl.songs.add(evt)

            # Validate: no overlaps (gaps are allowed — songs can be
            # placed anywhere on the arrangement timeline)
            for i in range(len(sorted_songs) - 1):
                cur_end = sorted_songs[i].start_time + sorted_songs[i].length
                nxt_start = sorted_songs[i + 1].start_time
                if cur_end > nxt_start + 0.001:  # small tolerance
                    tl.errors.append(
                        f"SONGS overlap: '{sorted_songs[i].name}' ends at "
                        f"{cur_end:.2f} but '{sorted_songs[i + 1].name}' starts at "
                        f"{nxt_start:.2f}"
                    )
                    tl.is_valid = False

        # -- SECTIONS (optional) ----------------------------------------
        if section_clips:
            sorted_sections = sorted(section_clips, key=lambda c: c.start_time)
            for clip in sorted_sections:
                end = clip.start_time + clip.length
                tl.sections.add(
                    TimelineEvent(
                        start_beat=clip.start_time,
                        end_beat=end,
                        type=EventType.SECTION,
                        name=clip.name,
                    )
                )
            # Validate: no overlaps
            for i in range(len(sorted_sections) - 1):
                cur_end = sorted_sections[i].start_time + sorted_sections[i].length
                nxt_start = sorted_sections[i + 1].start_time
                if cur_end > nxt_start + 0.001:
                    tl.errors.append(
                        f"SECTIONS overlap: '{sorted_sections[i].name}' ends at "
                        f"{cur_end:.2f} but '{sorted_sections[i + 1].name}' starts at "
                        f"{nxt_start:.2f}"
                    )

        # -- LYRICS ------------------------------------------------------
        if lyric_clips:
            for clip in sorted(lyric_clips, key=lambda c: c.start_time):
                end = clip.start_time + clip.length
                tl.lyrics.add(
                    TimelineEvent(
                        start_beat=clip.start_time,
                        end_beat=end,
                        type=EventType.LYRIC,
                        name=clip.name,
                    )
                )

        # -- CHORDS (optional) ------------------------------------------
        if chord_clips:
            sorted_chords = sorted(chord_clips, key=lambda c: c.start_time)
            for clip in sorted_chords:
                end = clip.start_time + clip.length
                tl.chords.add(
                    TimelineEvent(
                        start_beat=clip.start_time,
                        end_beat=end,
                        type=EventType.CHORD,
                        name=clip.name,
                    )
                )
            for i in range(len(sorted_chords) - 1):
                cur_end = sorted_chords[i].start_time + sorted_chords[i].length
                nxt_start = sorted_chords[i + 1].start_time
                if cur_end > nxt_start + 0.001:
                    tl.errors.append(
                        f"CHORDS overlap: '{sorted_chords[i].name}' ends at "
                        f"{cur_end:.2f} but '{sorted_chords[i + 1].name}' starts at "
                        f"{nxt_start:.2f}"
                    )

        # -- CONTROL (STOP events only) ---------------------------------
        if control_clips:
            for clip in sorted(control_clips, key=lambda c: c.start_time):
                if clip.name.strip().upper() == "STOP":
                    end = clip.start_time + clip.length
                    if end <= clip.start_time:
                        end = clip.start_time + 0.001
                    tl.stops.add(
                        TimelineEvent(
                            start_beat=clip.start_time,
                            end_beat=end,
                            type=EventType.STOP,
                            name="STOP",
                        )
                    )
                else:
                    logger.warning(
                        "Unknown CONTROL event '%s' at beat %.2f — ignored",
                        clip.name,
                        clip.start_time,
                    )

        if tl.errors:
            for err in tl.errors:
                logger.error("Timeline validation: %s", err)

        return tl

    # ── resolution ───────────────────────────────────────────────────

    def active_song(self, beat: float) -> TimelineEvent | None:
        """Return the song active at the given beat, or None."""
        return self._find_active(self.songs, beat)

    def active_section(self, beat: float) -> TimelineEvent | None:
        return self._find_active(self.sections, beat)

    def active_chord(self, beat: float) -> TimelineEvent | None:
        return self._find_active(self.chords, beat)

    def active_lyrics(self, beat: float) -> list[TimelineEvent]:
        """Return all lyrics active at the given beat."""
        result = []
        for evt in self.lyrics:
            if evt.start_beat > beat:
                break
            if evt.contains(beat):
                result.append(evt)
        return result

    def active_stop(self, beat: float) -> TimelineEvent | None:
        """Return the STOP control clip active at *beat*, or None."""
        return self._find_active(self.stops, beat)

    def stop_entered(self, prev_beat: float, cur_beat: float) -> TimelineEvent | None:
        """Return the STOP clip the playhead just entered during forward motion.

        Only fires when *cur_beat* is inside a STOP clip and *prev_beat* was not
        (i.e. the playhead ran onto the clip, not a seek across the timeline).
        """
        if cur_beat <= prev_beat:
            return None
        stop = self.active_stop(cur_beat)
        if stop is None or self.active_stop(prev_beat) is not None:
            return None
        return stop

    def next_stop_after(self, beat: float) -> TimelineEvent | None:
        """Return the next STOP clip strictly after *beat* (by clip start)."""
        idx = self.stops.bisect_right(TimelineEvent(start_beat=beat, type=EventType.STOP))
        if idx < len(self.stops):
            return self.stops[idx]
        return None

    def all_songs(self) -> list[TimelineEvent]:
        return list(self.songs)

    def all_sections(self) -> list[TimelineEvent]:
        return list(self.sections)

    def all_chords(self) -> list[TimelineEvent]:
        return list(self.chords)

    def song_at_index(self, index: int) -> TimelineEvent | None:
        if 0 <= index < len(self.songs):
            return self.songs[index]
        return None

    def song_index(self, beat: float) -> int | None:
        """Return the 0-based index of the song at *beat*, or None."""
        for i, evt in enumerate(self.songs):
            if evt.contains(beat):
                return i
        return None

    # ── private ──────────────────────────────────────────────────────

    @staticmethod
    def _find_active(events: SortedList, beat: float) -> TimelineEvent | None:
        """Binary-ish search for the event containing *beat*."""
        # Find the rightmost event starting at or before beat
        dummy = TimelineEvent(start_beat=beat, type=EventType.SONG)
        idx = events.bisect_right(dummy) - 1
        if idx >= 0:
            evt = events[idx]
            if evt.contains(beat):
                return evt
        return None
