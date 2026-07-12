# Video 2 — Ableton Project Structure

**Runtime target:** ~12–15 min  
**Audience:** Musicians who already use Ableton Live  
**Goal:** Viewer understands the five semantic tracks, cue points, CONTROL/STOP clips, and how to build songs, sections, lyrics, and chords.

**Prerequisites on screen:** Demo project per [`demo-project-setup.md`](demo-project-setup.md) (or build it live on camera). StageAble connected and unlocked.

---

## Recording checklist

- [ ] Arrangement View visible with semantic tracks alongside audio tracks
- [ ] SONGS track with 2–3 clips (Drifts, Neon Sky, Last Light)
- [ ] Cue points matching each SONGS clip name
- [ ] SECTIONS clips on at least one song
- [ ] LYRICS clips including one overlapping pair
- [ ] CHORDS clips with symbols like `Am7`, `F | Bb`
- [ ] CONTROL track with `STOP` clips at song endings
- [ ] Rescan demonstrated after edits
- [ ] Song jump demo (cue point vs clip start)
- [ ] STOP demo (play through vs seek over)

---

## Opening (30 sec)

**On screen:** Arrangement View with semantic tracks visible alongside regular audio tracks.

**Say:**

- "StageAble doesn't replace your Ableton session — it reads specially named tracks in **Arrangement View**."
- "Think of these tracks as a metadata layer on top of your audio/MIDI tracks. Session View clips are not used."

---

## Section 1 — The track map (2 min)

**On screen:** Show all five tracks in Arrangement View.

**Say (narrate each row):**

| Track | Required? | What clip name means |
|-------|-----------|---------------------|
| **SONGS** | Yes | Song title |
| **SECTIONS** | No | Section label (Intro, Verse, Chorus…) |
| **LYRICS** | No | Lyric line to display |
| **CHORDS** | No | Chord symbol (shown verbatim) |
| **CONTROL** | No | Only `STOP` is recognized |

- Track names are **case-insensitive** (`Songs`, `SONGS`, `songs` all work).
- All other tracks are ignored — your existing audio/MIDI setup stays as-is.
- **`[MIX]` tracks** (e.g. `[MIX] Kick`) are separate — covered in Video 3.

---

## Section 2 — SONGS track + cue points (3 min)

**On screen:** SONGS track with three clips → cue markers in Live's cue lane.

**Say:**

- **SONGS is mandatory.** Without it, StageAble cannot build a timeline.
- One arrangement clip per song. Clip **name** = song title. Clip **position and length** define where the song lives on the timeline.
- Songs **must not overlap**. Gaps between songs are fine.
- **Critical:** song **navigation** uses Ableton **cue points**, not clip start positions.
- For each song, add a cue marker whose name **exactly matches** the SONGS clip name.
- The cue point can be placed at your actual jump-in point (e.g. after a count-in) — it doesn't have to match the clip start.

**Demo:** Jump to Drifts in StageAble. If the cue is at beat 4 and the SONGS clip starts at 0, the playhead lands at beat 4.

**Gotcha:** Missing cue point = jump skipped with a warning. Always pair every SONGS clip with a cue point.

---

## Section 3 — SECTIONS track (2 min)

**On screen:** SECTIONS clips spanning Intro / Verse / Chorus on Drifts.

**Say:**

- One clip per section; clip name = the label shown on stage.
- Clips span the section duration on the timeline.
- Sections **must not overlap** (unlike lyrics).
- Used for live display and for Rehearsal mode (Video 3).

**Tip:** Name sections consistently across songs (`Verse 1`, `Chorus`) — helps rehearsal and readability.

Reference beats for Drifts (from `demo-events.txt`):

- Intro: 0–16
- Verse 1: 16–48
- Chorus: 48–80
- Verse 2: 80–112
- Outro: 112–128

---

## Section 4 — LYRICS track (2 min)

**On screen:** LYRICS clips with text in clip names; highlight overlapping pair at beats 24–32.

**Say:**

- Each clip's **name is the lyric line** — can be a full sentence.
- Must be **Arrangement View** clips.
- **Overlapping clips are allowed** — useful for harmonies or layered cues.
- The bundled StageAble Bridge handles long clip names reliably.

**Demo lines (Drifts verse):**

- Beat 16: "Walking through the static haze"
- Beat 24: "Every step retraces yesterday" (overlaps previous line from beat 24–32)

**Optional (skip unless targeting power users):** Bulk edit via `python manage.py lyrics_io export/import`.

---

## Section 5 — CHORDS track (1.5 min)

**On screen:** CHORDS clips — `Am7`, `F | Bb`, `Cmaj7`.

**Say:**

- Clip name = chord symbol, shown **verbatim** on the Performance display.
- One active chord at a time — clips **must not overlap**.
- Place clips where the harmony changes, aligned with your arrangement.

---

## Section 6 — CONTROL track and STOP clips (3 min)

**On screen:** CONTROL track with `STOP` clips at beats 127, 287, 447.

**Say:**

- The CONTROL track is for automation markers, not audio.
- **Only clips named `STOP`** are recognized (case-insensitive). Any other name is ignored.
- When the playhead **crosses** a STOP clip during forward playback, StageAble automatically stops Ableton transport.
- STOP does **not** fire when you manually seek/jump over it — only on natural playback crossing.
- Place a short STOP clip at each song ending.
- STOP clips also enable **setlist auto-advance** (Video 3): when a setlist is active, crossing STOP cues the next song.

**Demo 1:** Play Drifts to the end → transport stops at STOP.  
**Demo 2:** Jump from Intro directly past the STOP clip → transport does not stop.

---

## Section 7 — Rescan and verify (1 min)

**On screen:** Rescan in StageAble → Performance view shows songs and live updates.

**Say:**

- After any clip or track change: **Rescan**.
- StageAble caches the project — changes in Live are not live until you rescan.
- Confirm songs appear in the song list, sections/lyrics/chords update as playhead moves.

---

## Closing (30 sec)

**Say:**

- "Your Ableton project is now a show-ready data layer: songs, sections, lyrics, chords, and stop points."
- "Next video: the StageAble interface — Performance, Setlist, Mixer, and Rehearsal views."

---

## Mantra (repeat once)

Arrangement View only → named tracks → cue points for songs → Rescan after edits.
