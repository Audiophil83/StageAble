# Demo Ableton Project — Tutorial Setup

Use this guide to build the `.als` project referenced in the StageAble tutorial
videos. The arrangement events are defined in
[`demo-events.txt`](demo-events.txt).

**Assumptions:** 120 BPM, 4/4 time signature, Arrangement View only.

---

## Tracks to create

Create these tracks in Arrangement View (names are case-insensitive):

| Track | Type in Live | Notes |
|-------|--------------|-------|
| **SONGS** | MIDI or audio (empty) | Mandatory — metadata only |
| **SECTIONS** | MIDI or audio (empty) | Section labels |
| **LYRICS** | MIDI or audio (empty) | Lyric cues |
| **CHORDS** | MIDI or audio (empty) | Chord symbols |
| **CONTROL** | MIDI or audio (empty) | STOP markers |
| **[MIX] Kick** | Your kick track | Mixer tab (Video 3) |
| **[MIX] Bass** | Your bass track | Mixer tab (Video 3) |
| **[MIX] Keys** | Your keys/synth track | Mixer tab (Video 3) |
| **Audio 1–3** | Audio with content | Optional backing audio per song |

Semantic tracks (SONGS through CONTROL) do not need audio content — empty
arrangement clips with the correct names and positions are enough. Add simple
audio loops on regular tracks if you want audible playback during demos.

---

## Songs (SONGS track)

Add three non-overlapping clips:

| Clip name | Start (beat) | Length (beats) | Bars (4/4) |
|-----------|--------------|----------------|------------|
| Drifts | 0 | 128 | 32 |
| Neon Sky | 160 | 128 | 32 |
| Last Light | 320 | 128 | 32 |

Gaps between songs (beats 128–159 and 288–319) are intentional.

---

## Cue points (required for song navigation)

Add one cue marker per song. Names must **exactly match** the SONGS clip name.

| Cue name | Position (beat) | Notes |
|----------|-----------------|-------|
| Drifts | 0 | Or beat 4 to demo count-in offset |
| Neon Sky | 160 | |
| Last Light | 320 | |

**Video 2 demo tip:** Place the Drifts cue at beat 4 (one bar count-in) while
the SONGS clip still starts at 0. Jumping to Drifts in StageAble lands at the
cue point, not the clip start.

---

## Sections, lyrics, chords, CONTROL

Copy beat ranges and clip names from [`demo-events.txt`](demo-events.txt).

Quick reference:

- **SECTIONS** — Intro / Verse / Chorus / Outro per song; must not overlap
- **LYRICS** — Lines at beats 16–40 overlap intentionally (Drifts verse)
- **CHORDS** — One active chord at a time; use symbols like `F | Bb`
- **CONTROL** — Three short `STOP` clips at beats 127, 287, and 447

---

## Mixer tracks

Rename three instrument tracks with the `[MIX]` prefix:

- `[MIX] Kick`
- `[MIX] Bass`
- `[MIX] Keys`

Rescan StageAble after renaming so they appear in the Mixer tab.

---

## Setlist for Video 3

Prepare this setlist in the StageAble UI (or have it ready to build on camera):

| Order | Song | Auto-play next | Gap (seconds) |
|-------|------|----------------|---------------|
| 1 | Drifts | Yes | 3 |
| 2 | Neon Sky | Yes | 3 |
| 3 | Last Light | No | — |

This demonstrates auto-cue: STOP at end of Drifts → 3 s countdown → Neon Sky
plays automatically.

---

## Mixer preset for Video 3

Save a preset named **Verse** with Kick and Bass active, Keys inactive. Save a
second preset **Chorus** with all three active. Demo loading presets during
Video 3 Section 4.

---

## Verify before recording

1. StageAble Bridge installed; Control Surface = **StageAble**
2. All five semantic tracks present; SONGS has three clips
3. Three cue points with matching names
4. Three `[MIX]` tracks renamed
5. Three CONTROL clips named `STOP`
6. **Rescan** in StageAble — song list shows Drifts, Neon Sky, Last Light
7. Play through Drifts — section, lyrics, and chords update in Performance view
8. Play to beat 127 — transport stops at STOP

---

## Bulk import (optional)

If your demo project is already scanned, you can push clip names from the events
file:

```bash
python manage.py events_io import docs/videos/demo-events.txt
```

Clip positions must already exist in Ableton at the beat numbers in the file.
Import updates names only; it does not create clips.
