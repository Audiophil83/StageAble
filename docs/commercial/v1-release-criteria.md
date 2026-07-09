# v1.0.0 release criteria

RemoteAble v1.0.0 is the first **paid** release baseline.

## Must-have before tagging v1.0.0

- [ ] Known bugs fixed (IP refresh, transport controls)
- [ ] Frozen builds use production defaults (`DJANGO_DEBUG=False`)
- [ ] License activation and trial mode working
- [ ] macOS app signed and notarized
- [ ] Public download CDN + appcast hosted
- [ ] Marketing website live with legal pages
- [ ] At least 5 beta testers have run a full gig
- [ ] Automated tests pass for licensing, serve URLs, bridge paths

## Versioning

Use the existing Gitea release workflow (`scripts/versioning/next_version.py`). When criteria are met, merge to `main` and let CI tag `v1.0.0`.

## Post-v1.0

- Raise price to €69 / $69
- Begin Windows distribution (Phase 2)
- Add Sparkle.framework embed (optional upgrade from appcast checker)
