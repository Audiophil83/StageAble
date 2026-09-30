# StageAble

Real-time show-control system for Ableton Live. Reads your arrangement via
[AbletonOSC](https://github.com/ideoforms/AbletonOSC), builds a deterministic
timeline of songs, sections, lyrics, chords and stop markers, then streams the live
state to any number of browser clients over WebSocket.

---

## Features

- Song / section / chord / lyrics overlay resolved in real time from the playhead
- Automatic STOP-event playback control (no Max4Live required)
- Multi-client web UI with transport controls and setlist display
- Keyboard shortcuts (Space = play/stop, arrows = prev/next song)
- Song navigation via named cue points
- Persistent setlist management via REST API
- Auto-reconnects to Ableton if the connection drops
- macOS menu bar and Windows system tray desktop apps with auto-update checks
- Server-side MIDI Learn and macOS Bluetooth HID remote control

## MIDI and Bluetooth controllers

Open **Admin → Devices** in a browser on the computer running StageAble. Device
administration is intentionally unavailable to other computers on the LAN.

MIDI Learn supports Note, Control Change, and Program Change messages. Notes
fire on note-on and re-arm on release. CC controls fire when crossing value 64
upward and re-arm below 64. Available actions are Play/Pause, Stop, Previous
Song, and Next Song. Mappings are global to the StageAble installation and work
even when no browser is open.

On macOS, **Open Bluetooth Pairing** opens the native Bluetooth Settings pane.
Pair the remote there, return to StageAble, and click **Refresh**. Keyboard-style
Bluetooth HID remotes can then be learned like MIDI controls. macOS may require
StageAble to be enabled under **System Settings → Privacy & Security → Input
Monitoring**; restart StageAble after granting access.
Grant **Accessibility** as well when using Play/Pause or skip buttons. StageAble
uses it to stop a mapped remote media key from also launching or controlling
Apple Music. While an enabled Bluetooth remote is connected, those media keys
are captured for StageAble rather than passed to other macOS applications.

Bluetooth support is limited to controls exposed by macOS as keyboard HID input.
Voice, touch, motion, vendor-specific BLE services, and gamepad protocols are not
supported. Fire TV remote models vary, and models that do not expose standard HID
buttons may not be compatible. Windows device input is planned but not enabled in
this release.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11+** | Tested on 3.13 |
| **Ableton Live** | With Arrangement View content |
| **StageAble Bridge** | Ableton Live control surface bundled with this repo (a trimmed, self-contained fork of AbletonOSC — no separate AbletonOSC install needed). Install from the menu bar app (**Install Ableton Bridge…**) or with `python scripts/install_bridge.py`, then enable **StageAble** under *Preferences > Link / Tempo / MIDI > Control Surface*. |

The bridge listens on UDP port **11000** and replies on port **11001** by
default. StageAble uses the same defaults, and remains compatible with a stock
AbletonOSC install if you prefer to use that instead.

---

## Quick Start

```bash
# Clone and enter the project
cd stageable

# Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run database migrations
STAGEABLE_NO_ENGINE=1 python manage.py migrate

# Start the server (engine auto-starts and connects to Ableton)
daphne -b 0.0.0.0 -p 8000 stageable.asgi:application
```

Open **http://localhost:8000** in a browser. Open it on as many devices as you
like -- all clients stay in sync.

### Alternative: engine-only mode

If you only need the polling engine without the web UI (e.g. for testing):

```bash
python manage.py run_engine
```

---

## Ableton Arrangement Setup

StageAble reads up to five specially-named tracks from your Ableton arrangement.
Track names are matched **case-insensitively** (e.g. `Songs`, `SONGS`,
`songs` all work).

### SONGS (mandatory)

Exactly one track named **SONGS**. Each arrangement clip on this track defines
a song and is used for **identifying the currently playing song only**:

- Clip name = song title
- Clip position = song start (in beats)
- Clip length = song duration

Songs **must not overlap**. Gaps between songs are fine -- place them wherever
you want on the timeline.

**Navigation** uses cue points instead of clip positions (see [Cue Points](#cue-points) below). Place a named cue marker at each song's desired jump position — the cue point name must match the corresponding SONGS clip name.

### SECTIONS (optional)

A track named **SECTIONS**. Each clip defines a structural section (Intro,
Verse, Chorus, etc.). Used for navigation and UI display. Clips must not
overlap.

### LYRICS (optional)

A track named **LYRICS**. Each clip represents a lyric cue:

- Clip name = the lyric text to display
- Multiple lyrics can be active at the same time (overlapping clips are OK)

### CHORDS (optional)

A track named **CHORDS**. Each clip represents the current chord symbol to display:

- Clip name = chord text (shown verbatim, e.g. `Am7`, `F | Bb`)
- One chord is active at a time; clips must not overlap

### CONTROL (optional)

A track named **CONTROL**. Only one clip type is recognised:

- Clips named **STOP** -- when the playhead crosses a STOP marker, StageAble
  automatically stops Ableton's transport.

Any clip with a name other than `STOP` is ignored (with a log warning).

### Mixer tracks (optional)

Any track whose name **starts with** `[MIX]` appears in the **Mixer** tab in the
browser client, where you can toggle each channel **Active** (audible) or
**Inactive** (muted) during a show.

- Example: rename a track to `[MIX] Kick` — it shows as **Kick** in the mixer.
- The prefix is stripped for display; spacing after `[MIX]` is optional
  (`[MIX]Kick` and `[MIX] Kick` both work).
- Rescan after renaming tracks in Ableton so StageAble picks up changes.
- Mute state is refreshed about once per second from Ableton (same slow poll as
  tempo/time signature), so changes made in Live’s mixer stay in sync with the UI.
- Semantic tracks (`SONGS`, `SECTIONS`, etc.) use **whole-name** matching, so
  `[MIX] SONGS` is treated as a mixer track, not a song track.

### Cue Points

StageAble uses Ableton's **cue markers** for song navigation. When you jump to a
song, the engine looks for a cue point whose name matches the SONGS clip name and
jumps to it via `/live/song/cue_point/jump`. This correctly positions the playhead
regardless of transport state (unlike `jump_by` / `set_current_song_time`, which can
drift when stopped).

- Cue point names **must match** the corresponding SONGS clip name exactly.
- If no matching cue point exists, the jump is skipped and a warning is logged.

All other tracks in your set are ignored by StageAble (except `[MIX]` tracks for the mixer).

---

## Configuration

Engine settings are stored in the database (singleton ``AppSettings`` row) and
can be managed at runtime through the Django admin or REST API. Environment
variables are only used as defaults when the settings row is first created.

### Settings fields

| Field | Default | Description |
|---|---|---|
| `ableton_osc_host` | `127.0.0.1` | IP address of the machine running Ableton |
| `ableton_osc_send_port` | `11000` | Port the Live control surface listens on |
| `ableton_osc_recv_port` | `11001` | Port StageAble listens on for OSC replies |
| `engine_poll_hz` | `20` | How often (per second) the engine polls Ableton |

### Changing settings

- **Django Admin** — navigate to `/admin/engine/appsettings/` and edit the
  singleton row.
- **REST API** — `GET/PATCH /api/settings/` to read or update settings at
  runtime. Changes are hot-reloaded immediately.

### Initial seed (env vars)

The environment variables below are only read when the settings row is first
created (e.g. on first migration). After that, they are ignored in favour of
the database.

| Variable | Default |
|---|---|
| `ABLETON_OSC_HOST` | `127.0.0.1` |
| `ABLETON_OSC_SEND_PORT` | `11000` |
| `ABLETON_OSC_RECV_PORT` | `11001` |
| `ENGINE_POLL_HZ` | `20` |

### LAN setup

To connect to Ableton on a different machine, set `ableton_osc_host` to that
machine's IP (via Admin or API) and make sure UDP ports 11000/11001 are
reachable.

### Other env vars

| Variable | Default | Description |
|---|---|---|
| `DJANGO_DEBUG` | `True` (dev) / `False` (frozen `.app`) | Set to `False` in production; frozen builds default to `False` automatically |
| `DJANGO_SECRET_KEY` | *(dev key)* | Override in production |
| `STAGEABLE_NO_ENGINE` | *(unset)* | Set to any value to prevent auto-starting the engine (useful for running migrations) |
| `STAGEABLE_FROZEN` | *(unset)* | Set by the PyInstaller launcher; enables production defaults and static file serving |
| `STAGEABLE_VERSION` | from `VERSION` file | Override the bundled app version string |
| `STAGEABLE_APPCAST_URL` | `https://downloads.stageable.app/appcast-macos.xml` | URL of the Sparkle-style appcast for update checks |

---

## Architecture

```
Ableton Live
    |
    | UDP/OSC (11000 / 11001)
    |
AbletonOSCClient            osc_client.py     Bidirectional OSC over python-osc
    |
    |-- Scanner              scanner.py        Reads tracks + clips, builds Timeline
    |-- Runtime Loop         runtime.py        20 Hz poll, STOP detection, broadcast
    |
EngineState                  state.py          Thread-safe global state singleton
    |
    |-- REST API             views.py          Transport control, song/section data, setlists
    |-- WebSocket            consumers.py      Real-time state stream + command input
    |
Browser clients              app.js / HTML     Vanilla JS SPA, no build step
```

### How it works

1. On startup, StageAble connects to the Live control surface (StageAble
   Bridge) and **loads the last
   arrangement scan from the database** (songs, sections, lyrics, chords,
   cue points, mixer tracks). Use **Rescan** in the client or menu bar app
   to read the live set from Ableton and refresh the cache.

2. A background thread runs the **runtime loop** at 20 Hz (configurable). Each
   tick:
   - Reads the current playhead position and playing state from Ableton via OSC
   - Resolves which song, section, chord, and lyrics are active (binary search on
     sorted interval lists)
   - Checks for **STOP crossings**: if the playhead moved forward past a STOP
     marker since the last tick, it sends a stop command to Ableton
   - If the state changed since the last broadcast, pushes a snapshot to all
     connected WebSocket clients

3. Browser clients connect via WebSocket at `/ws/engine/` and receive the full
   state on connect, then incremental updates. Clients can send commands
   (play, stop, seek, jump) which are forwarded to Ableton through the engine.

### Data flow

- **Ableton is the only transport authority.** StageAble never overrides
  Ableton's state -- it reads, augments, and relays.
- **Last write wins.** Multiple clients can send commands simultaneously; there
  is no locking.
- **The frontend is stateless.** It only renders whatever the backend sends.

---

## API Reference

### WebSocket

Connect to `ws://<host>:<port>/ws/engine/`.

#### Server -> Client messages

| `type` | Payload | When |
|---|---|---|
| `state` | Full engine state object (see below) | On connect and every time state changes (~20 Hz max) |
| `ack` | `{ "command": "<name>" }` | After a command is processed |
| `error` | `{ "message": "..." }` | On invalid or failed command |

**State object shape:**

```json
{
  "connection_status": "connected",
  "is_playing": true,
  "transport_position": 64.0,
  "tempo": 128.0,
  "signature_numerator": 4,
  "signature_denominator": 4,
  "active_song": { "name": "Drifts", "type": "SONG", "start_beat": 0.0, "end_beat": 544.0 },
  "active_song_index": 0,
  "active_section": { "name": "Verse 1", "type": "SECTION", "start_beat": 16.0, "end_beat": 48.0 },
  "active_chord": { "name": "Am7", "type": "CHORD", "start_beat": 32.0, "end_beat": 48.0 },
  "active_lyrics": [{ "name": "Some lyric line", "type": "LYRIC", "start_beat": 64.0, "end_beat": 68.0 }],
  "next_stop": 544.0,
  "timeline_valid": true,
  "timeline_errors": [],
  "last_update": 1716660140.123
}
```

#### Client -> Server commands

Send JSON with a `"command"` field:

| Command | Extra fields | Effect |
|---|---|---|
| `play` | -- | Start Ableton transport |
| `stop` | -- | Stop Ableton transport |
| `seek` | `"beat": 64.0` | Move playhead to beat position |
| `jump_to_song` | `"index": 2` | Jump to song by 0-based index (via cue point) |
| `jump_to_section` | `"start_beat": 48.0` | Jump to section start beat |
| `rescan` | -- | Re-read arrangement from Ableton and rebuild timeline |

### REST API

All endpoints are under `/api/`. No authentication required (configurable).

#### Engine status

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/status/` | Current engine state snapshot (same shape as WebSocket state) |

#### Transport control

| Method | Endpoint | Body | Description |
|---|---|---|---|
| POST | `/api/transport/play/` | -- | Start playback |
| POST | `/api/transport/stop/` | -- | Stop playback |
| POST | `/api/transport/seek/` | `{ "beat": 64.0 }` | Seek to beat |
| POST | `/api/transport/jump-to-song/` | `{ "index": 0 }` | Jump to song (via cue point) |
| POST | `/api/transport/jump-to-section/` | `{ "start_beat": 48.0 }` | Jump to section start beat |

#### Arrangement data

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/songs/` | All songs from the timeline |
| GET | `/api/sections/` | All sections from the timeline |
| GET | `/api/chords/` | All chords from the timeline |
| POST | `/api/rescan/` | Re-scan the Ableton arrangement |

#### Setlist CRUD

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/setlists/` | List all setlists |
| POST | `/api/setlists/` | Create a setlist (with optional nested entries) |
| GET | `/api/setlists/{id}/` | Get a single setlist with entries |
| PUT | `/api/setlists/{id}/` | Replace a setlist (entries are replaced entirely) |
| PATCH | `/api/setlists/{id}/` | Partial update |
| DELETE | `/api/setlists/{id}/` | Delete a setlist |
| POST | `/api/setlists/{id}/activate/` | Mark as active (deactivates all others) |

---

## Project Structure

```
stageable/
├── manage.py                          Django management CLI
├── requirements.txt                   Python dependencies
├── VERSION                            Current release version
├── StageAble.spec                    PyInstaller spec (macOS .app)
├── StageAble-windows.spec            PyInstaller spec (Windows folder)
├── stageable/                        Django project package
│   ├── settings.py                    All configuration
│   ├── asgi.py                        ASGI entrypoint + static files + engine auto-start
│   ├── urls.py                        Root URL routing
│   └── wsgi.py                        WSGI fallback
├── engine/                            Core application
│   ├── osc_client.py                  Bidirectional AbletonOSC client (python-osc)
│   ├── timeline.py                    Timeline data structures + interval resolution
│   ├── scanner.py                     Reads arrangement from Ableton, builds Timeline
│   ├── state.py                       Thread-safe global EngineState singleton
│   ├── runtime.py                     20 Hz poll loop, STOP detection, WS broadcast
│   ├── consumers.py                   WebSocket consumer (state stream + commands)
│   ├── views.py                       REST API views
│   ├── urls.py                        API URL routing
│   ├── routing.py                     WebSocket URL routing
│   ├── models.py                      Setlist + SetlistEntry Django models
│   ├── serializers.py                 DRF serializers
│   ├── updates.py                     Appcast-based update checker
│   ├── legal.py                       Bundled license document helpers
│   ├── paths.py                       Cross-platform app data directories
│   ├── platform_ui.py                 Desktop UI dispatch (macOS / Windows)
│   ├── status_ui.py                   macOS menu bar UI (rumps)
│   ├── tray_ui.py                     Windows system tray UI (pystray)
│   ├── bridge_installer.py            Ableton bridge install logic
│   ├── admin.py                       Django admin config
│   ├── startup.py                     One-shot engine auto-start guard
│   ├── tests/                         Automated tests
│   └── management/commands/
│       └── run_engine.py              `python manage.py run_engine` standalone command
├── scripts/
│   ├── build_mac_app.py               Build macOS .app bundle
│   ├── build_windows_app.py           Build Windows distribution folder
│   ├── install_bridge.py              CLI bridge installer
│   ├── packaging/
│   │   ├── launcher.py                PyInstaller entry point
│   │   ├── sign_and_notarize.sh       macOS code signing + notarization
│   │   ├── sign_windows.ps1           Windows Authenticode signing
│   │   └── generate_appcast.py        Sparkle appcast XML generator
│   └── versioning/
│       └── next_version.py            Semver bump from Conventional Commits
├── website/                           Project website (static HTML)
├── templates/
│   └── index.html                     Single-page frontend
└── static/
    ├── app.js                         Frontend JS (WebSocket, rendering, controls)
    └── style.css                      Dark theme CSS
```

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| Space | Toggle play / stop |
| Arrow Right | Next song |
| Arrow Left | Previous song |

---

## Troubleshooting

**"No track named 'SONGS' found"**
Your Ableton set must have exactly one track named `SONGS` (case-insensitive).

**Engine shows "disconnected"**
Make sure Ableton is running with the **StageAble** control surface enabled.
Check that UDP ports 11000/11001 are not blocked by a firewall.

**Static files not loading (404)**
In development, StageAble serves static files automatically in DEBUG mode via
`ASGIStaticFilesHandler`. Frozen `.app` / Windows builds serve static files
even with `DJANGO_DEBUG=False`. For a manual production deployment without the
bundled app, run `python manage.py collectstatic` and serve the `staticfiles/`
directory.

**Menu bar address does not update after network change**
The macOS menu bar app polls the LAN address every 10 seconds and updates
automatically. Use **Refresh Address** in the menu for an immediate update.

**OSC query timeouts in the log / LYRICS shows 0 clips**
Bulk arrangement clip name queries can exceed OSC/UDP size limits when a track
has many long clip names (typical on LYRICS). Install StageAble Bridge and
restart Live:

```bash
python scripts/install_bridge.py
```

StageAble falls back to chunked name reads automatically once the bridge is
installed. To diagnose:

```bash
python manage.py debug_clips --track LYRICS --verbose
OSC_DEBUG=1 python manage.py debug_clips --track LYRICS
```

This queries `start_time`, `length`, and `name` separately and reports timing,
clip counts, and estimated OSC payload size. Set `OSC_DEBUG=1` to log incoming
name replies (or use Django `DEBUG` logging on `engine.osc_client`).

**Other OSC query timeouts**
OSC replies have a 2-second timeout. If Ableton is under heavy load or
the network is slow, queries may time out. The engine will retry on the next
poll tick.

**Time signature stays 4/4 or log mentions missing `signature_*`**
An older Remote Script may not expose `/live/song/get/signature_numerator` and
`signature_denominator`. StageAble defaults to 4/4. Reinstall StageAble Bridge
(`python scripts/install_bridge.py`), restart Live, and re-select the control
surface.

**Time signature looks wrong or never changes**
Ableton reports the meter **at the playhead** (it updates as you move through
time-signature markers in the arrangement). StageAble polls this on the slow
poll loop. If the UI shows 3/8 but you expect 3/4, check which marker applies at the current playhead
position in Live’s arrangement ruler.

---

## Building and releases

StageAble ships as a **macOS `.app`** menu bar bundle and a **Windows folder**
distribution, both built with [PyInstaller](https://pyinstaller.org/). A Linux
Gitea runner **cannot** produce a working `.app` (macOS Mach-O binaries are
required), so CI uses a **macOS `act_runner`** for release builds.

### Local macOS build

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller pillow
python scripts/build_mac_app.py
open dist/StageAble.app
```

The bundled app runs as a **macOS menu bar app** (no Dock icon). Click the
menu bar icon to see the server address, open it in a browser, copy it, check
for updates, or quit.

The bundled app stores its SQLite database in
`~/Library/Application Support/StageAble/db.sqlite3`.

Frozen builds automatically set `DJANGO_DEBUG=False` and serve static assets
from the bundled files.

**Unsigned builds:** macOS Gatekeeper may block the first launch. Right-click the app and
choose **Open**, or allow it in *System Settings → Privacy & Security*.

If the app opens but closes again after a few seconds, macOS may be applying
**App Translocation** (quarantine). Remove the quarantine attribute and retry:

```bash
xattr -cr StageAble.app
```

When something goes wrong the Daphne server log is written to
`~/Library/Application Support/StageAble/daphne.log`.

### Local Windows build

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller pillow pystray
python scripts\build_windows_app.py
dist\StageAble\StageAble.exe
```

Windows builds use a **system tray icon** (pystray) with the same actions as the
macOS menu bar. App data is stored under `%LOCALAPPDATA%\StageAble\`.

### Code signing

**macOS** — sign and notarize before public distribution:

```bash
export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export APPLE_ID="you@example.com"
export APPLE_APP_PASSWORD="app-specific-password"
export APPLE_TEAM_ID="XXXXXXXXXX"
chmod +x scripts/packaging/sign_and_notarize.sh
./scripts/packaging/sign_and_notarize.sh dist/StageAble.app
```

**Windows** — Authenticode signing (requires a `.pfx` certificate):

```powershell
$env:WINDOWS_SIGNING_CERT_PATH = "C:\certs\codesign.pfx"
$env:WINDOWS_SIGNING_CERT_PASSWORD = "..."
pwsh scripts/packaging/sign_windows.ps1 dist/StageAble/StageAble.exe
```

See the [Building and releases](#building-and-releases) section above for the
release workflow.

### Auto-updates

The desktop app includes **Check for Updates…** which reads a Sparkle-style
appcast XML. Generate an appcast when publishing a release:

```bash
python scripts/packaging/generate_appcast.py \
  --version 1.0.0 \
  --macos-url "https://downloads.stageable.app/StageAble-macOS-1.0.0.zip" \
  --windows-url "https://downloads.stageable.app/StageAble-Windows-1.0.0.zip" \
  --length 12345678 \
  -o dist/appcast-macos.xml
```

Override the appcast URL with `STAGEABLE_APPCAST_URL`. A full
[Sparkle](https://sparkle-project.org/) framework embed is optional; the
current implementation opens the download URL in the browser.

### Gitea Actions CI/CD

On every push to `main`, [`.gitea/workflows/release.yml`](.gitea/workflows/release.yml):

1. Runs `python3 manage.py check` on the Mac runner
2. Computes the next semver from Conventional Commits (`scripts/versioning/next_version.py`)
3. Tags and builds `StageAble.app` on the Mac runner
4. Generates `appcast-macos.xml`
5. Optionally signs/notarizes when `CODESIGN_IDENTITY` and Apple secrets are set
6. Optionally uploads to CDN when `STAGEABLE_CDN_UPLOAD_CMD` is set
7. Publishes `StageAble-macOS.zip` and the appcast as a Gitea release

Windows builds use a separate manual workflow:
[`.gitea/workflows/release-windows.yml`](.gitea/workflows/release-windows.yml)
(`workflow_dispatch` on `windows-latest`).

The workflow uses the Mac runner's installed `python3` (not
`actions/setup-python`, which requires GitHub-hosted paths like
`/Users/runner/hostedtoolcache` and fails on self-hosted `act_runner` hosts).

**Mac runner setup (one-time):**

1. Enable Actions in your Gitea instance and repo
2. Ensure Python 3.11+ is available: `python3 --version`
3. Install and register `act_runner` on a Mac with host execution:

   ```bash
   brew install act_runner
   act_runner register \
     --instance https://YOUR_GITEA \
     --token YOUR_REGISTRATION_TOKEN \
     --name macos-builder \
     --labels macos-latest:host
   ```

4. Set `executor: host` in the runner config (see
   [`docs/act_runner-macos.example.yaml`](docs/act_runner-macos.example.yaml)).
   If the runner daemon uses a minimal `PATH`, set `runner.envs.PATH` there so
   `python3` and `pip` are found, then restart the runner.
5. Start the runner: `act_runner daemon --config /path/to/config.yaml`

Keep your existing Linux Docker runner for `runs-on: ubuntu-latest` jobs.

### Running tests

```bash
STAGEABLE_NO_ENGINE=1 python manage.py test engine.tests
```

---

## License

StageAble is open-source software released under the [MIT License](LICENSE).

Copyright © 2026 Philipp Schleicher.

StageAble bundles third-party open-source components (Django, Twisted, Channels,
python-osc, and others) under their respective permissive licenses. Their required
copyright and license notices are reproduced in
[`THIRD-PARTY-LICENSES.txt`](THIRD-PARTY-LICENSES.txt). The bundled Ableton Live
control surface additionally ships its own attribution in
[`stageable_bridge/NOTICE`](stageable_bridge/NOTICE).

StageAble is not affiliated with or endorsed by Ableton AG.
