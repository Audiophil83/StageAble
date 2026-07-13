# Video 1 — Installing StageAble and Setting Up in Ableton

**Runtime target:** ~6–8 min  
**Audience:** Musicians who already use Ableton Live  
**Goal:** Viewer can install StageAble, connect it to Ableton, and open the web UI on another device.

**Prerequisites on screen:** Fresh Mac (or clean demo), purchase email with download link, Ableton Live installed.

---

## Recording checklist

- [ ] StageAble-macOS.zip downloaded and unzipped
- [ ] StageAble.app in Applications
- [ ] License activated (or trial mode noted)
- [ ] Ableton Live opened at least once before bridge install
- [ ] Bridge installed via menu bar
- [ ] Live restarted; Control Surface = StageAble
- [ ] Browser UI open on a second device (phone or tablet)
- [ ] Lock/unlock demonstrated
- [ ] Rescan clicked successfully

---

## Opening (30 sec)

**On screen:** StageAble menu bar icon visible; Ableton Live open in background.

**Say:**

- "StageAble gives you live show control for Ableton — lyrics, chords, setlists, and transport — from any phone, tablet, or laptop on your network."
- "In this video we'll install the app, connect it to Ableton, and get the browser UI running."

---

## Section 1 — Install StageAble (1.5 min)

**On screen:** Download → unzip → drag to Applications → launch.

**Say:**

- Download `StageAble-macOS.zip` from your purchase email.
- Move `StageAble.app` to Applications and launch it.
- First launch shows the license agreement — accept to continue.
- Activate your license from the menu bar: **Activate License…**
- Without a license, trial mode gives you **15 minutes per session** — enough to follow along.

**Mention briefly:** macOS Gatekeeper may block unsigned builds — right-click → Open if needed.

---

## Section 2 — Install the Ableton Bridge (2 min)

**On screen:** Open Live once → StageAble menu bar → **Install Ableton Bridge…** → restart Live → Preferences.

**Say:**

- StageAble talks to Ableton over a bundled **control surface** called StageAble Bridge — no Max for Live, no separate MIDI routing.
- **Open Ableton Live at least once first** — the installer needs your User Library folder.
- In the StageAble menu bar, choose **Install Ableton Bridge…**
- **Restart Ableton Live** — this step is required.
- Go to **Preferences → Link / Tempo / MIDI → Control Surface** and select **StageAble**.

**Key point:** This is OSC over UDP (ports 11000/11001), not a MIDI port setup. Viewers should not look for MIDI I/O settings.

---

## Section 3 — Verify connection and open the web UI (2 min)

**On screen:** Live running with control surface enabled → menu bar shows address like `192.168.1.10:8000` → open URL on phone/tablet.

**Say:**

- With Live running and StageAble selected as control surface, the menu bar shows a local network address.
- On any device on the same Wi‑Fi, open that URL in a browser — no app install on the device.
- The UI starts in **locked mode**: performers see the Performance view only; transport is disabled until someone unlocks.
- Tap the **lock button** on one device to unlock — that device gets full control (Setlist, Mixer, Rehearsal tabs).

**Demo:** Show connection indicator in UI (connected vs disconnected). Briefly mention: if disconnected, check Live is running and the control surface is enabled.

---

## Section 4 — First Rescan (1 min)

**On screen:** Unlock controls → open **Admin → Rescan**.

**Say:**

- StageAble reads your Ableton **Arrangement View** and caches it.
- After any track or clip changes in Live, hit **Rescan** — from **Admin → Rescan** in the UI or the menu bar.
- We'll set up the actual tracks in the next video; for now, confirm the app is connected and scanning.

---

## Closing (30 sec)

**Say:**

- "You now have StageAble installed, the bridge connected to Ableton, and the browser UI open on your devices."
- "Next video: how to structure your Ableton project so StageAble knows your songs, sections, lyrics, and chords."

**Recap checklist (optional on-screen overlay):**

1. StageAble.app installed + licensed
2. Bridge installed + Live restarted
3. Control Surface = StageAble
4. Browser UI open on LAN device
5. Unlock on one control device

---

## Common mistakes to mention

- Forgot to open Live before installing the bridge
- Forgot to restart Live after bridge install
- Looking for MIDI port settings instead of Control Surface
- Phone on a different Wi‑Fi network than the Mac running StageAble
