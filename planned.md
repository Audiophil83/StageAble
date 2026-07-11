# To-Dos

# Bugs to be fixed

- ~~IP never changes~~ — **done** (menu bar polls every 10s; manual Refresh Address still available)
- CI / CD — **partial** (macOS release workflow + Windows `workflow_dispatch`; CDN upload + signing need secrets)
- ~~Transport controls are a bit strange~~ — **done** (Play button toggles play/stop like Space)

# Features to be implemented

#### Versioning system — **done**
Automatic semver from Conventional Commits via [`scripts/versioning/next_version.py`](scripts/versioning/next_version.py) and [`.gitea/workflows/release.yml`](.gitea/workflows/release.yml).

#### Song time instead of no. of bars
Still unsure how this is supposed to work.

#### Update Mechanism — **partial**
Appcast generation ([`scripts/packaging/generate_appcast.py`](scripts/packaging/generate_appcast.py)), update checker ([`engine/updates.py`](engine/updates.py)), and menu item **Check for Updates…** are implemented. Full Sparkle.framework embed (in-app download + install) is optional.

#### Mixer
Real mixer with volume slider.

#### User management
LAN password / auth for WebSocket and REST (see Phase 3 below).

#### Logging

---

# Paid distribution roadmap

Recommended pricing: **€49 / $49** launch (early adopter **€39**), **€69 / $69** after v1.0 stable. One-time perpetual license.

Full documentation: [`README.md` — Commercial distribution](README.md#commercial-distribution).

## Phase 0 — Ship readiness

| Step | Status | Code changes |
|------|--------|--------------|
| Fix IP never refreshes | **done** | Yes — [`engine/status_ui.py`](engine/status_ui.py) |
| Fix transport control quirks | **done** | Yes — [`static/app.js`](static/app.js) |
| Production build defaults | **done** | Yes — [`stageable/settings.py`](stageable/settings.py), [`stageable/asgi.py`](stageable/asgi.py), [`scripts/packaging/launcher.py`](scripts/packaging/launcher.py) |
| Expand automated tests | **done** | Yes — [`engine/tests/`](engine/tests/) |
| Reach v1.0.0 paid release baseline | **pending** | Partial — see [`docs/commercial/v1-release-criteria.md`](docs/commercial/v1-release-criteria.md) |

## Phase 1 — macOS paid launch

| Step | Status | Code changes |
|------|--------|--------------|
| Privacy policy and Impressum | **pending** | No |
| Refund and withdrawal policy page | **pending** | No |
| Choose storefront (Lemon Squeezy / Paddle / Gumroad) | **pending** | No — [`docs/commercial/storefront-setup.md`](docs/commercial/storefront-setup.md) |
| License key generation and delivery | **pending** | No (storefront); webhook = Partial |
| License activation in app | **done** | Yes — [`engine/licensing.py`](engine/licensing.py), menu + REST API |
| Trial / demo mode (15 min session) | **done** | Yes — [`engine/licensing.py`](engine/licensing.py) |
| Recommended pricing | **done** | No — documented in README |
| Apple Developer Program enrollment | **pending** | No |
| Code signing in CI | **done** | Yes — [`scripts/packaging/sign_and_notarize.sh`](scripts/packaging/sign_and_notarize.sh); needs CI secrets |
| Notarization and stapling | **done** | Yes — same script; needs Apple credentials |
| Sparkle / appcast auto-update | **partial** | Yes — appcast + menu checker; Sparkle.framework embed optional |
| Public download and update CDN | **pending** | Partial — CI hook in [`.gitea/workflows/release.yml`](.gitea/workflows/release.yml); host files manually |
| Product website | **partial** | No — template at [`website/index.html`](website/index.html); deploy + legal pages pending |
| YouTube tutorial series | **pending** | No |
| User-facing documentation | **done** | No — [`docs/commercial/user-guide.md`](docs/commercial/user-guide.md) |
| Customer support channel | **pending** | No |
| Private beta with performers | **pending** | No |

## Phase 2 — Windows

| Step | Status | Code changes |
|------|--------|--------------|
| PyInstaller build and packaging | **done** | Yes — [`scripts/build_windows_app.py`](scripts/build_windows_app.py), [`StageAble-windows.spec`](StageAble-windows.spec), [`.gitea/workflows/release-windows.yml`](.gitea/workflows/release-windows.yml) |
| Bridge installer paths | **done** | Yes — [`engine/bridge_installer.py`](engine/bridge_installer.py) |
| System tray UI (replace rumps) | **done** | Yes — [`engine/tray_ui.py`](engine/tray_ui.py), [`engine/platform_ui.py`](engine/platform_ui.py) |
| Authenticode code signing | **done** | Yes — [`scripts/packaging/sign_windows.ps1`](scripts/packaging/sign_windows.ps1); needs cert purchase |
| Auto-update mechanism | **done** | Yes — same appcast checker, `platform=windows` |
| Unified license (Mac + Windows) | **done** | Yes — single `SA-XXXX-XXXX-XXXX` key format |

## Phase 3 — Post-launch

| Step | Status | Code changes |
|------|--------|--------------|
| Optional LAN password / auth | **pending** | Yes |
| Crash and error reporting (e.g. Sentry) | **pending** | Yes |
| Paid major-version upgrades | **pending** | Partial |

---

## Quick reference — new files from distribution work

| Area | Key files |
|------|-----------|
| Licensing | `engine/licensing.py`, `/api/license/` endpoints |
| Updates | `engine/updates.py`, `scripts/packaging/generate_appcast.py` |
| Desktop UI | `engine/platform_ui.py`, `engine/status_ui.py`, `engine/tray_ui.py` |
| Paths | `engine/paths.py` |
| macOS release | `scripts/packaging/sign_and_notarize.sh` |
| Windows release | `scripts/build_windows_app.py`, `scripts/packaging/sign_windows.ps1` |
| Docs | `docs/commercial/*`, `website/index.html` |
