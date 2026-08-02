# To-Dos

# Bugs to be fixed

- CI / CD — **partial** (macOS release workflow + Windows `workflow_dispatch`; CDN upload + signing need secrets)

# Features to be implemented

#### Versioning system — **done**

Automatic semver from Conventional Commits via `[scripts/versioning/next_version.py](scripts/versioning/next_version.py)` and `[.gitea/workflows/release.yml](.gitea/workflows/release.yml)`.

#### Song time instead of no. of bars

Still unsure how this is supposed to work.

#### Update Mechanism — **partial**

Appcast generation (`[scripts/packaging/generate_appcast.py](scripts/packaging/generate_appcast.py)`), update checker (`[engine/updates.py](engine/updates.py)`), and menu item **Check for Updates…** are implemented. Full Sparkle.framework embed (in-app download + install) is optional.

#### Mixer

Real mixer with volume slider.

#### User management

LAN password / auth for WebSocket and REST.

#### Client Logging

---

# Open-source release checklist

| Step | Status | Notes |
| --- | --- | --- |
| Remove proprietary licensing / trial mode | **done** | Removed `engine/licensing.py`, EULA acceptance, and entitlement checks |
| Add project LICENSE (MIT) | **done** | Root `[LICENSE](LICENSE)` |
| Update README and website | **done** | Open-source framing; commercial docs removed |
| Publish repository publicly | **pending** | Push to a public Git host |
| Tag first open-source release | **pending** | Attach macOS / Windows build artifacts to GitHub/Gitea release |
| Record YouTube tutorial series | **pending** | See `[docs/videos/](docs/videos/)` |

---

## Quick reference — distribution-related files

| Area | Key files |
| --- | --- |
| Updates | `engine/updates.py`, `scripts/packaging/generate_appcast.py` |
| Desktop UI | `engine/platform_ui.py`, `engine/status_ui.py`, `engine/tray_ui.py` |
| Legal | `LICENSE`, `engine/legal.py`, `THIRD-PARTY-LICENSES.txt` |
| macOS release | `scripts/packaging/sign_and_notarize.sh` |
| Windows release | `scripts/build_windows_app.py`, `scripts/packaging/sign_windows.ps1` |
| Website | `website/index.html` |
