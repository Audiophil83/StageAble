# Video 3 — The StageAble Interface

**Runtime target:** ~14–16 min  
**Audience:** Musicians who already use Ableton Live  
**Goal:** Viewer can use all main views for a live show or rehearsal.

**Prerequisites on screen:** Demo project loaded and scanned ([`demo-project-setup.md`](demo-project-setup.md)). Two devices: one locked (phone), one unlocked (laptop). Setlist and mixer presets prepared per demo guide.

---

## Recording checklist

- [ ] Tab navigation visible (Performance, Setlist, Mixer, Rehearsal, Admin)
- [ ] Locked phone shows Performance only
- [ ] Unlock demonstrated on laptop
- [ ] Performance view walkthrough while playing Drifts
- [ ] Fullscreen mode demonstrated (F key)
- [ ] Setlist created, auto-cue configured, activated
- [ ] Auto-advance chain demo (Drifts → STOP → countdown → Neon Sky)
- [ ] Mixer toggles and preset save/load
- [ ] Rehearsal: play one section, loop two contiguous sections
- [ ] Leave Rehearsal confirmation shown
- [ ] Admin tab: Projects listed, rename path warning, delete unused project, Rescan section

---

## Opening (30 sec)

**On screen:** Tab navigation in header; locked phone beside unlocked laptop.

**Say:**

- "StageAble runs in any browser — one Mac runs the server and Ableton; phones and tablets are remote displays and controllers."
- "Five views: **Performance**, **Setlist**, **Mixer**, **Rehearsal**, and **Admin**."

---

## Section 1 — Client lock (1 min)

**On screen:** Locked phone (Performance only, no transport) → unlock on laptop.

**Say:**

- Devices start **locked** — performers see the show display without accidentally hitting transport.
- **Unlock** one device to get full access: Setlist editor, Mixer, Rehearsal, Admin, transport controls.
- Only one device needs to be unlocked for show management; others can stay locked as lyric/chord displays.

---

## Section 2 — Performance view (4 min)

**On screen:** Play through Drifts; point to each UI element.

**Walk through each element:**

1. **Song name** — current song from SONGS track
2. **Section** — current section with progress bar and sliding animation
3. **Chords** — current chord symbol
4. **Lyrics** — current lyric line(s); expandable for longer text
5. **Transport bar** — position, tempo, time signature
6. **Transport controls** — Play/Stop, Prev/Next song (when unlocked)
7. **Song list** — all songs (or setlist entries if a setlist is active); click to jump; progress bars show playback position
8. **Auto-advance banner** — appears when setlist auto-plays next song after STOP

**Keyboard shortcuts:**

- **Space** = play/stop
- **Left/Right arrows** = previous/next song

**Fullscreen demo:**

- Press **F** or use Fullscreen button — hides chrome, enlarges text for stage monitors.
- **Keep Screen Awake** — prevents device sleep during a show.

**Active setlist note:** When a setlist is activated, Performance shows **only setlist songs** in order, not the full timeline.

---

## Section 3 — Setlist view (4 min)

**On screen:** Setlist tab → New → add Drifts, Neon Sky, Last Light → configure auto-cue → Save → Activate.

**Say:**

- Setlists are **per Ableton project** — different shows, different orders.
- **New** → name the setlist → drag songs from **Available Songs** to **Setlist** (or click to add).
- Reorder by dragging entries.
- Between songs (except the last): configure **Auto-play next song** and **Wait (seconds)** gap.
- **Save** the setlist.
- **Activate** — only one active setlist per project; Performance view now follows this order.
- Songs missing from the arrangement show as **(missing)** — rescan or fix names.

**Demo the full auto-cue chain:**

1. Active setlist with auto-play enabled on Drifts (gap: 3 seconds)
2. Play Drifts → STOP at end → transport stops
3. Neon Sky is cued → countdown appears → auto-plays after 3 seconds

**Say:** "This is how you run a full show hands-free between songs."

---

## Section 4 — Mixer view (3 min)

**On screen:** `[MIX] Kick`, `[MIX] Bass`, `[MIX] Keys` in Ableton → Mixer tab.

**Say:**

- Any Ableton track starting with **`[MIX]`** appears here (prefix stripped: `[MIX] Kick` → "Kick").
- Toggle **Active** (unmuted) / **Inactive** (muted) per channel during a show.
- Mute state syncs from Live about once per second — changes in Live's mixer stay in sync.
- **Presets:** save current mute states as a named preset; load presets to recall a mix configuration for different songs or sections.
- Rescan after adding or renaming `[MIX]` tracks in Ableton.

**Demo presets:**

- Save **Verse** — Kick + Bass active, Keys inactive
- Save **Chorus** — all three active
- Load each preset and show mutes updating in Live

**Note:** Current mixer is mute/unmute only — no volume faders yet.

---

## Section 5 — Rehearsal view (3 min)

**On screen:** Cue Drifts → Rehearsal tab → play Verse 1 → loop Verse 1 + Chorus.

**Say:**

- Rehearsal is for **practicing sections** within the current song.
- Requires a **SECTIONS** track (from Video 2).
- Lists sections that fall within the active song's beat range.
- **Play** (per row) — jumps to section start and plays once (loop off).
- **Loop** — select **contiguous** sections via checkboxes, then Loop — sets Ableton's arrangement loop bracket and plays.
- **Stop** — stops transport and disables loop.
- Leaving the Rehearsal tab prompts confirmation and resets the loop bracket.

**Demo:** Select Verse 1 + Chorus (adjacent) → Loop → show looping indicator. Mention that non-contiguous selection is not allowed.

---

## Section 6 — Admin view (2 min)

**On screen:** Admin tab → Projects sub-tab → list of stored projects → Rename with warning → Delete an unused project → Rescan sub-tab.

**Say:**

- **Admin** groups project management, engine settings, and rescanning
- StageAble remembers each Ableton project you scan
- Setlists and mixer presets belong to a specific project
- If you move or rename the `.als` file on disk, use **Rename** to point StageAble at the new path
- The warning explains this only updates StageAble's record — it does not move the file
- **Delete** removes cached scan data, setlists, and mixer presets for projects you no longer use
- **Rescan** re-reads the arrangement from Ableton after edits
- **Settings** holds engine options such as OSC host and slide animations

---

## Closing (30 sec)

**Say:**

- "Performance for the show, Setlist for your running order, Mixer for channel control, Rehearsal for practice, Admin for projects, settings, and rescanning."
- "Structure your Ableton project, rescan after changes, and you're ready for the stage."

**End card:** Link to user guide, support@stageable.app, website.

---

## Screen layout tip

Split or picture-in-picture: Ableton Arrangement View + StageAble browser UI side by side where possible. Pause on each Rescan so viewers see the UI update.
