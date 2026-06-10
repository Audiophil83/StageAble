# Remoteable patch for AbletonOSC

Upstream [AbletonOSC](https://github.com/ideoforms/AbletonOSC) returns all
arrangement clip names in a single OSC message. For tracks with many long lyric
clip names, that reply exceeds UDP/OSC size limits and the query times out.

Meter map scans also used to require one OSC round trip per song/section
boundary (seek + time signature + tempo). Remoteable adds a batched endpoint so
Live seeks internally and returns all samples in one reply.

This patch adds three endpoints:

| Address | Query params | Response params |
|---|---|---|
| `/live/track/get/arrangement_clips/name_chunk` | `track_id`, `offset`, `limit` | `track_id`, `offset`, `total_count`, `[name, ...]` |
| `/live/track/set/arrangement_clips/name` | `track_id`, `clip_index`, `name` | *(none)* |
| `/live/song/get/meter_at_beats` | `beat1`, `beat2`, … | `saved_ok`, `count`, `beat1`, `num1`, `den1`, `tempo1`, … |

Remoteable tries the bulk `/live/track/get/arrangement_clips/name` first, then
falls back to chunked reads automatically. Meter map scans use
`/live/song/get/meter_at_beats` when patched, otherwise fall back to the legacy
per-beat seek loop.

## Install

1. Install [AbletonOSC](https://github.com/ideoforms/AbletonOSC#installation) if
   you have not already.
2. From the Remoteable repo root:

```bash
python scripts/install_abletonosc_patch.py
```

3. Restart Ableton Live and re-select **AbletonOSC** under *Preferences → Link /
   Tempo / MIDI → Control Surface*.

The installer backs up your existing `track.py` and `song.py` to `.py.orig` once
each.

## Verify

```bash
python manage.py debug_clips --track LYRICS --verbose
```

After patching:

- `name` should succeed (via chunked fallback) and report all arrangement clips.
- The **Meter at beats** section should report `OK` for `/live/song/get/meter_at_beats 0 4 8`.
