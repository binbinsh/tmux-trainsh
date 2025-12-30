#!/usr/bin/env bash
#
# Build and install macOS app to /Applications
# Usage: ./scripts/build-macos-app.sh [--no-install] [--skip-notarize]
#
set -euo pipefail

[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS required" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
KEYCHAIN_PATH="$HOME/Library/Keychains/login.keychain-db"

NO_INSTALL=false
SKIP_NOTARIZE=false

for arg in "$@"; do
  case $arg in
    --no-install) NO_INSTALL=true ;;
    --skip-notarize) SKIP_NOTARIZE=true ;;
    --help|-h) echo "Usage: $0 [--no-install] [--skip-notarize]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

# Load .env
[[ -f "$ENV_FILE" ]] || { echo "Missing .env at $ENV_FILE" >&2; exit 1; }
set -a; source "$ENV_FILE"; set +a

# Resolve signing identity
: "${APPLE_SIGNING_IDENTITY:=${APPLE_DEVELOPER_ID:-}}"
[[ -n "$APPLE_SIGNING_IDENTITY" ]] || { echo "APPLE_SIGNING_IDENTITY required" >&2; exit 1; }
[[ -n "${APPLE_CERTIFICATE:-}" ]] || { echo "APPLE_CERTIFICATE required" >&2; exit 1; }
[[ -n "${APPLE_CERTIFICATE_PASSWORD:-}" ]] || { echo "APPLE_CERTIFICATE_PASSWORD required" >&2; exit 1; }
[[ -n "${APPLE_PASSWORD:-}" && -z "${APPLE_ID_PASSWORD:-}" ]] && export APPLE_ID_PASSWORD="$APPLE_PASSWORD"

# Temp dir with cleanup
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Import certificate if not already present
if ! security find-identity -v -p codesigning "$KEYCHAIN_PATH" 2>/dev/null | grep -Fq "$APPLE_SIGNING_IDENTITY"; then
  echo "Importing certificate..."

  # Import intermediate cert
  curl -sL "https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer" -o "$TMP_DIR/intermediate.cer" \
    && security import "$TMP_DIR/intermediate.cer" -k "$KEYCHAIN_PATH" -T /usr/bin/codesign 2>/dev/null || true

  # Import developer cert (file path or base64)
  if [[ -f "$APPLE_CERTIFICATE" ]]; then
    CERT_PATH="$APPLE_CERTIFICATE"
  else
    CERT_PATH="$TMP_DIR/certificate.p12"
    printf "%s" "$APPLE_CERTIFICATE" | base64 --decode > "$CERT_PATH"
  fi
  security import "$CERT_PATH" -k "$KEYCHAIN_PATH" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign -A

  # Verify import
  security find-identity -v -p codesigning "$KEYCHAIN_PATH" 2>/dev/null | grep -Fq "$APPLE_SIGNING_IDENTITY" \
    || { echo "Failed to import certificate" >&2; exit 1; }
fi

# Build
echo "Building..."
cd "$ROOT_DIR"
npm run tauri:build -- --bundles app

PRODUCT_NAME="$(python3 -c "import json; print(json.load(open('src-tauri/tauri.conf.json'))['productName'])")"
APP_BUNDLE="$ROOT_DIR/src-tauri/target/release/bundle/macos/${PRODUCT_NAME}.app"
[[ -d "$APP_BUNDLE" ]] || { echo "App bundle not found" >&2; exit 1; }

codesign --verify --deep --strict "$APP_BUNDLE"

# Notarize (if credentials available)
if [[ "$SKIP_NOTARIZE" != true && -n "${APPLE_ID:-}" && -n "${APPLE_ID_PASSWORD:-}" && -n "${APPLE_TEAM_ID:-}" ]]; then
  echo "Notarizing..."
  ZIP_PATH="$TMP_DIR/${PRODUCT_NAME}.zip"
  ditto -c -k --keepParent "$APP_BUNDLE" "$ZIP_PATH"
  xcrun notarytool submit "$ZIP_PATH" --apple-id "$APPLE_ID" --password "$APPLE_ID_PASSWORD" --team-id "$APPLE_TEAM_ID" --wait
  xcrun stapler staple "$APP_BUNDLE"
fi

# Install
if [[ "$NO_INSTALL" != true ]]; then
  TARGET="/Applications/Doppio.app"
  rm -rf "$TARGET"
  ditto "$APP_BUNDLE" "$TARGET"
  echo "Installed to $TARGET"
else
  echo "Built: $APP_BUNDLE"
fi
