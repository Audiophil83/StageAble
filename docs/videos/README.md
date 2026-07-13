# StageAble Tutorial Videos — Talking Protocols

Structured narration outlines for three tutorial videos. Audience: musicians who
already use Ableton Live. Tone: practical, demo-driven.

| Video | Script | Runtime |
|-------|--------|---------|
| 1 — Install & setup | [01-install-and-setup.md](01-install-and-setup.md) | ~6–8 min |
| 2 — Ableton project structure | [02-ableton-project-structure.md](02-ableton-project-structure.md) | ~12–15 min |
| 3 — StageAble interface | [03-stageable-interface.md](03-stageable-interface.md) | ~14–16 min |

---

## Before you record

1. Build the demo Ableton project: [demo-project-setup.md](demo-project-setup.md)
2. Reference timeline data: [demo-events.txt](demo-events.txt)
3. StageAble installed, bridge connected, browser UI tested on a second device

---

## Suggested recording order

Record **Video 2** first if building the demo project on camera — it produces
the `.als` used in Videos 1 (rescan) and 3 (full UI demo). Alternatively,
pre-build the demo set and record Video 1 → 2 → 3 in publish order.

---

## Recording tips

- **Screen layout:** Split or picture-in-picture — Ableton Arrangement View +
  StageAble browser UI side by side where possible.
- **Pacing:** Pause on each Rescan so viewers see the UI update.
- **Mantra:** Arrangement View only → named tracks → cue points for songs →
  Rescan after edits.

### Common mistakes (call out once across the series)

- Forgot to restart Live after bridge install
- SONGS clip without matching cue point
- CONTROL clip not named `STOP`
- Editing Live but not rescanning
- Looking for MIDI port settings instead of Control Surface

---

## Source references

- Install flow: [user-guide.md](../commercial/user-guide.md)
- Track rules and cue points: [README.md](../../README.md) (Ableton Arrangement Setup)
- UI implementation: [templates/index.html](../../templates/index.html), [static/app.js](../../static/app.js)
