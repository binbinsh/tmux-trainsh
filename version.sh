#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") <version>" >&2
  echo "Example: $(basename "$0") 1.2.3" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

if [[ $# -ne 1 ]]; then
  usage
fi

VERSION="$1"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
  echo "Invalid version: $VERSION" >&2
  exit 1
fi

require_cmd python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR" && pwd)"

python3 - "$ROOT_DIR" "$VERSION" <<'PY'
import json
import os
import sys

root = sys.argv[1]
version = sys.argv[2]


def log_update(target):
    print(f"🔧 Updated {target} to {version}")


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def update_json_file(path, updater):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    updater(data)
    write_json(path, data)


def update_package_json():
    path = os.path.join(root, "package.json")
    update_json_file(path, lambda data: data.__setitem__("version", version))
    log_update("package.json")


def update_package_lock():
    path = os.path.join(root, "package-lock.json")

    def updater(data):
        data["version"] = version
        packages = data.get("packages")
        if isinstance(packages, dict) and "" in packages and isinstance(packages[""], dict):
            packages[""]["version"] = version

    update_json_file(path, updater)
    log_update("package-lock.json")


def update_tauri_conf():
    path = os.path.join(root, "src-tauri", "tauri.conf.json")
    update_json_file(path, lambda data: data.__setitem__("version", version))
    log_update("src-tauri/tauri.conf.json")


def update_cargo_toml():
    path = os.path.join(root, "src-tauri", "Cargo.toml")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = []
    in_package = False
    updated = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_package = stripped == "[package]"
        if in_package and stripped.startswith("version"):
            key = stripped.split("=", 1)[0].strip()
            if key == "version":
                prefix = line.split("version", 1)[0]
                out.append(f'{prefix}version = "{version}"')
                updated = True
                continue
        out.append(line)
    if not updated:
        raise SystemExit("Could not find [package] version in Cargo.toml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    log_update("src-tauri/Cargo.toml")


def update_cargo_lock():
    path = os.path.join(root, "src-tauri", "Cargo.lock")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = []
    in_package = False
    current_name = None
    updated = False
    for line in lines:
        stripped = line.strip()
        if stripped == "[[package]]":
            in_package = True
            current_name = None
            out.append(line)
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_package = False
            current_name = None
        if in_package and stripped.startswith("name ="):
            value = stripped.split("=", 1)[1].strip()
            current_name = value[1:-1] if value.startswith('"') and value.endswith('"') else value
            out.append(line)
            continue
        if in_package and current_name == "doppio" and stripped.startswith("version ="):
            prefix = line.split("version", 1)[0]
            out.append(f'{prefix}version = "{version}"')
            updated = True
            continue
        out.append(line)
    if not updated:
        raise SystemExit("Could not find package doppio in Cargo.lock")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    log_update("src-tauri/Cargo.lock (package doppio)")


update_package_json()
update_package_lock()
update_tauri_conf()
update_cargo_toml()
update_cargo_lock()

print(f"✅ Updated version to {version}")
PY

echo "Done."
