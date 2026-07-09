#!/usr/bin/env bash
# Sign and notarize RemoteAble.app for distribution.
#
# Required environment variables:
#   APPLE_ID              Apple ID email
#   APPLE_APP_PASSWORD    App-specific password
#   APPLE_TEAM_ID         Team ID
#   CODESIGN_IDENTITY     e.g. "Developer ID Application: Your Name (TEAMID)"
#
# Usage:
#   ./scripts/packaging/sign_and_notarize.sh dist/RemoteAble.app

set -euo pipefail

APP_PATH="${1:-dist/RemoteAble.app}"
ZIP_PATH="${APP_PATH%.app}.zip"
IDENTITY="${CODESIGN_IDENTITY:?Set CODESIGN_IDENTITY}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found: $APP_PATH" >&2
  exit 1
fi

echo "Signing $APP_PATH with $IDENTITY"
codesign --force --deep --options runtime --sign "$IDENTITY" "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"

echo "Creating notarization zip"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

echo "Submitting for notarization"
xcrun notarytool submit "$ZIP_PATH" \
  --apple-id "$APPLE_ID" \
  --password "$APPLE_APP_PASSWORD" \
  --team-id "$APPLE_TEAM_ID" \
  --wait

echo "Stapling notarization ticket"
xcrun stapler staple "$APP_PATH"
spctl --assess --type execute -v "$APP_PATH"

echo "Done: $APP_PATH is signed and notarized"
