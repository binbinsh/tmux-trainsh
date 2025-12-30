#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 1
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd base64
require_cmd codesign
require_cmd ditto
require_cmd npm
require_cmd python3
require_cmd security
require_cmd uuidgen

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env at $ENV_FILE" >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  if [[ -n "${APPLE_DEVELOPER_ID:-}" ]]; then
    export APPLE_SIGNING_IDENTITY="$APPLE_DEVELOPER_ID"
  else
    echo "APPLE_SIGNING_IDENTITY or APPLE_DEVELOPER_ID is required in .env" >&2
    exit 1
  fi
fi

if [[ -z "${APPLE_CERTIFICATE:-}" ]]; then
  echo "APPLE_CERTIFICATE is required in .env" >&2
  exit 1
fi

if [[ -z "${APPLE_CERTIFICATE_PASSWORD:-}" ]]; then
  echo "APPLE_CERTIFICATE_PASSWORD is required in .env" >&2
  exit 1
fi

if [[ -n "${APPLE_PASSWORD:-}" && -z "${APPLE_ID_PASSWORD:-}" ]]; then
  export APPLE_ID_PASSWORD="$APPLE_PASSWORD"
fi

TMP_DIR="$(mktemp -d)"
KEYCHAIN_PASSWORD="$(uuidgen | tr -d '-')"
KEYCHAIN_PATH="$TMP_DIR/doppio-build.keychain-db"
DEFAULT_KEYCHAIN=""
if DEFAULT_OUTPUT="$(security default-keychain -d user 2>/dev/null)"; then
  DEFAULT_KEYCHAIN="$(printf "%s" "$DEFAULT_OUTPUT" | tr -d '\"')"
fi
declare -a ORIGINAL_KEYCHAIN_LIST
ORIGINAL_KEYCHAIN_LIST=()
if KEYCHAIN_LIST_OUTPUT="$(security list-keychains -d user 2>/dev/null)"; then
  while IFS= read -r line; do
    ORIGINAL_KEYCHAIN_LIST+=("${line//\"/}")
  done < <(printf "%s" "$KEYCHAIN_LIST_OUTPUT")
fi

cleanup() {
  local exit_code=$?
  if [[ -n "${DEFAULT_KEYCHAIN:-}" ]]; then
    security default-keychain -s "$DEFAULT_KEYCHAIN" >/dev/null 2>&1 || true
  fi
  if [[ ${#ORIGINAL_KEYCHAIN_LIST[@]} -gt 0 ]]; then
    security list-keychains -d user -s "${ORIGINAL_KEYCHAIN_LIST[@]}" >/dev/null 2>&1 || true
  fi
  security delete-keychain "$KEYCHAIN_PATH" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
  exit "$exit_code"
}
trap cleanup EXIT

umask 077

echo "Preparing signing keychain..."
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security default-keychain -s "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -t 3600 -u "$KEYCHAIN_PATH"
# Include system root certificates for chain validation
SYSTEM_ROOTS="/System/Library/Keychains/SystemRootCertificates.keychain"
if [[ ${#ORIGINAL_KEYCHAIN_LIST[@]} -gt 0 ]]; then
  security list-keychains -d user -s "$KEYCHAIN_PATH" "$SYSTEM_ROOTS" "${ORIGINAL_KEYCHAIN_LIST[@]}"
else
  security list-keychains -d user -s "$KEYCHAIN_PATH" "$SYSTEM_ROOTS"
fi

# Download and import Apple Developer ID G2 intermediate certificate
# This is required for certificates signed by the G2 intermediate CA
echo "Downloading Apple Developer ID G2 intermediate certificate..."
INTERMEDIATE_CERT_URL="https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer"
INTERMEDIATE_CERT_PATH="$TMP_DIR/DeveloperIDG2CA.cer"
if ! curl -sL "$INTERMEDIATE_CERT_URL" -o "$INTERMEDIATE_CERT_PATH"; then
  echo "Warning: Failed to download intermediate certificate" >&2
fi
if [[ -f "$INTERMEDIATE_CERT_PATH" ]]; then
  security import "$INTERMEDIATE_CERT_PATH" -k "$KEYCHAIN_PATH" -T /usr/bin/codesign >/dev/null 2>&1
fi

CERT_PATH="$TMP_DIR/certificate.p12"
if [[ -f "$APPLE_CERTIFICATE" ]]; then
  CERT_PATH="$APPLE_CERTIFICATE"
else
  printf "%s" "$APPLE_CERTIFICATE" | base64 --decode > "$CERT_PATH"
fi

security import "$CERT_PATH" -k "$KEYCHAIN_PATH" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign -A >/dev/null 2>&1
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH" >/dev/null 2>&1

IDENTITY_LIST="$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" 2>/dev/null || true)"
if ! grep -Fq "$APPLE_SIGNING_IDENTITY" <<<"$IDENTITY_LIST"; then
  echo "Signing identity not found after importing certificate: $APPLE_SIGNING_IDENTITY" >&2
  if security find-certificate -a -c "$APPLE_SIGNING_IDENTITY" "$KEYCHAIN_PATH" >/dev/null 2>&1; then
    echo "Certificate is present but not a codesigning identity (missing private key or invalid cert)." >&2
  else
    echo "Certificate matching the identity was not found in the keychain. Check APPLE_CERTIFICATE." >&2
  fi
  if [[ -z "${SKIP_IDENTITY_CHECK:-}" ]]; then
    exit 1
  fi
  echo "Continuing because SKIP_IDENTITY_CHECK=1 was set." >&2
fi

echo "Building Tauri app bundle..."
cd "$ROOT_DIR"
npm run tauri:build -- --bundles app

PRODUCT_NAME="$(python3 - <<'PY'
import json

with open("src-tauri/tauri.conf.json", "r", encoding="utf-8") as f:
    print(json.load(f)["productName"])
PY
)"

APP_BUNDLE_PATH="$ROOT_DIR/src-tauri/target/release/bundle/macos/${PRODUCT_NAME}.app"
if [[ ! -d "$APP_BUNDLE_PATH" ]]; then
  APP_BUNDLE_PATH="$(find "$ROOT_DIR/src-tauri/target" -type d -path "*/release/bundle/macos/${PRODUCT_NAME}.app" -print -quit)"
fi

if [[ -z "${APP_BUNDLE_PATH:-}" || ! -d "$APP_BUNDLE_PATH" ]]; then
  echo "Built app bundle not found for ${PRODUCT_NAME}.app" >&2
  exit 1
fi

echo "Verifying codesign..."
codesign --verify --deep --strict "$APP_BUNDLE_PATH"

TARGET_APP="/Applications/Doppio.app"
if [[ -e "$TARGET_APP" ]]; then
  rm -rf "$TARGET_APP"
fi

echo "Installing to $TARGET_APP"
ditto "$APP_BUNDLE_PATH" "$TARGET_APP"
echo "Done."
