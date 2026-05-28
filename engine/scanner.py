"""
Arrangement Scanner — reads track and clip data from Ableton via OSC and
builds a Timeline.

This is called on startup and can be re-triggered at any time to refresh
the timeline (e.g. after the user edits the arrangement).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .osc_client import AbletonOSCClient
from .timeline import ArrangementClip, Timeline

logger = logging.getLogger(__name__)

# Track names are matched case-insensitively
TRACK_SONGS = "songs"
TRACK_SECTIONS = "sections"
TRACK_LYRICS = "lyrics"
TRACK_CONTROL = "control"
TRACK_CHORDS = "chords"

SEMANTIC_TRACKS = {
    TRACK_SONGS,
    TRACK_SECTIONS,
    TRACK_LYRICS,
    TRACK_CONTROL,
    TRACK_CHORDS,
}


@dataclass
class TrackInfo:
    index: int
    name: str


def scan_tracks(osc: AbletonOSCClient) -> list[TrackInfo]:
    """Return a list of all tracks in the live set."""
    num_tracks = osc.get_num_tracks()
    if num_tracks is None:
        raise ConnectionError("Cannot read number of tracks from Ableton")

    tracks = []
    for i in range(num_tracks):
        name = osc.get_track_name(i)
        if name is None:
            logger.warning("Could not read name for track %d", i)
            continue
        tracks.append(TrackInfo(index=i, name=name))
    return tracks


def find_semantic_tracks(tracks: list[TrackInfo]) -> dict[str, TrackInfo]:
    """Identify the semantic tracks (SONGS, SECTIONS, LYRICS, CONTROL, CHORDS)."""
    found: dict[str, TrackInfo] = {}
    for t in tracks:
        normalised = t.name.strip().lower()
        if normalised in SEMANTIC_TRACKS:
            if normalised in found:
                logger.warning(
                    "Duplicate semantic track '%s' (indices %d and %d) — using first",
                    t.name,
                    found[normalised].index,
                    t.index,
                )
            else:
                found[normalised] = t
    return found


def read_arrangement_clips(
    osc: AbletonOSCClient, track_id: int
) -> list[ArrangementClip]:
    """Read all arrangement clips from a track."""
    names = osc.get_arrangement_clip_names(track_id)
    starts = osc.get_arrangement_clip_start_times(track_id)
    lengths = osc.get_arrangement_clip_lengths(track_id)

    if names is None or starts is None or lengths is None:
        logger.warning("Could not read arrangement clips for track %d", track_id)
        return []

    if not (len(names) == len(starts) == len(lengths)):
        logger.error(
            "Clip data length mismatch on track %d: names=%d starts=%d lengths=%d",
            track_id,
            len(names),
            len(starts),
            len(lengths),
        )
        return []

    clips = []
    for name, start, length in zip(names, starts, lengths):
        clips.append(ArrangementClip(name=name, start_time=start, length=length))
    return clips


def scan_arrangement(osc: AbletonOSCClient) -> Timeline:
    """Full scan: read all tracks, identify semantic tracks, build timeline.

    Returns a (possibly invalid) Timeline — callers should check
    ``timeline.is_valid`` and ``timeline.errors``.
    """
    logger.info("Scanning Ableton arrangement...")

    tracks = scan_tracks(osc)
    logger.info("Found %d tracks: %s", len(tracks), [t.name for t in tracks])

    semantic = find_semantic_tracks(tracks)
    logger.info(
        "Semantic tracks: %s",
        {k: f"{v.name} (#{v.index})" for k, v in semantic.items()},
    )

    # SONGS track is mandatory
    song_clips: list[ArrangementClip] = []
    section_clips: list[ArrangementClip] | None = None
    lyric_clips: list[ArrangementClip] | None = None
    control_clips: list[ArrangementClip] | None = None
    chord_clips: list[ArrangementClip] | None = None

    if TRACK_SONGS not in semantic:
        logger.error("No SONGS track found — timeline will be invalid")
        # Build empty timeline with error
        tl = Timeline()
        tl.errors.append(
            "No track named 'SONGS' found. "
            "You must have exactly one track named 'SONGS'."
        )
        tl.is_valid = False
        return tl

    song_clips = read_arrangement_clips(osc, semantic[TRACK_SONGS].index)
    logger.info("SONGS: %d clips", len(song_clips))

    if TRACK_SECTIONS in semantic:
        section_clips = read_arrangement_clips(osc, semantic[TRACK_SECTIONS].index)
        logger.info("SECTIONS: %d clips", len(section_clips))

    if TRACK_LYRICS in semantic:
        lyric_clips = read_arrangement_clips(osc, semantic[TRACK_LYRICS].index)
        logger.info("LYRICS: %d clips", len(lyric_clips))

    if TRACK_CONTROL in semantic:
        control_clips = read_arrangement_clips(osc, semantic[TRACK_CONTROL].index)
        logger.info("CONTROL: %d clips", len(control_clips))

    if TRACK_CHORDS in semantic:
        chord_clips = read_arrangement_clips(osc, semantic[TRACK_CHORDS].index)
        logger.info("CHORDS: %d clips", len(chord_clips))

    timeline = Timeline.build(
        song_clips=song_clips,
        section_clips=section_clips,
        lyric_clips=lyric_clips,
        control_clips=control_clips,
        chord_clips=chord_clips,
    )

    if timeline.is_valid:
        logger.info(
            "Timeline built: %d songs, %d sections, %d lyrics, %d chords, %d stops",
            len(timeline.songs),
            len(timeline.sections),
            len(timeline.lyrics),
            len(timeline.chords),
            len(timeline.stops),
        )
    else:
        logger.error("Timeline has errors: %s", timeline.errors)

    return timeline
