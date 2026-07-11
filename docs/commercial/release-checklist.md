# Release checklist

## Build

- [ ] Merge to `main`; CI computes version and builds artifacts
- [ ] macOS: `python scripts/build_mac_app.py`
- [ ] Windows: `python scripts/build_windows_app.py` (on Windows runner)

## Sign

- [ ] macOS: `./scripts/packaging/sign_and_notarize.sh dist/StageAble.app`
- [ ] Windows: `pwsh scripts/packaging/sign_windows.ps1 dist/StageAble/StageAble.exe`

## Publish

- [ ] Upload `StageAble-macOS.zip` to CDN
- [ ] Upload Windows folder zip to CDN
- [ ] Generate appcast: `python scripts/packaging/generate_appcast.py --version X.Y.Z --macos-url ... -o dist/appcast.xml`
- [ ] Upload `appcast.xml` to `https://downloads.stageable.app/appcast-macos.xml`

## Verify

- [ ] Fresh Mac: install, launch, no Gatekeeper warning
- [ ] Activate license key from purchase
- [ ] Check for Updates finds new version when appcast is ahead
