# Remoteable patch for AbletonOSC

Upstream [AbletonOSC](https://github.com/ideoforms/AbletonOSC) returns all
arrangement clip names in a single OSC message. For tracks with many long lyric
clip names, that reply exceeds UDP/OSC size limits and the query times out.

This patch adds one endpoint:

| Address | Query params | Response params |
|---|---|---|
| `/live/track/get/arrangement_clips/name_chunk` | `track_id`, `offset`, `limit` | `track_id`, `offset`, `total_count`, `[name, ...]` |

Remoteable tries the bulk `/live/track/get/arrangement_clips/name` first, then
falls back to chunked reads automatically.

## Install

1. Install [AbletonOSC](https://github.com/ideoforms/AbletonOSC#installation) if
   you have not already.
2. From the Remoteable repo root:

```bash
python scripts/install_abletonosc_patch.py
```

3. Restart Ableton Live and re-select **AbletonOSC** under *Preferences → Link /
   Tempo / MIDI → Control Surface*.

The installer backs up your existing `track.py` to `track.py.orig` once.

## Verify

```bash
python manage.py debug_clips --track LYRICS --verbose
```

After patching, `name` should succeed (via chunked fallback) and report 359 clips.
