# Update checker for tmux-trainsh
# Checks PyPI for newer versions and caches results

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..constants import CONFIG_DIR

CACHE_FILE = CONFIG_DIR / "update_cache.json"
CACHE_TTL_HOURS = 24
PYPI_PACKAGE = "tmux-trainsh"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"


def parse_version(v: str) -> tuple[int, ...]:
    """Parse version string into tuple for comparison."""
    parts = v.replace("-", ".").replace("dev", "0").split(".")
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return tuple(result)


def fetch_latest_version() -> Optional[str]:
    """Fetch latest version from PyPI."""
    try:
        req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("info", {}).get("version")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def load_cache() -> dict:
    """Load cache from disk."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_cache(data: dict) -> None:
    """Save cache to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def get_latest_version(force: bool = False) -> Optional[str]:
    """Return latest version from cache or PyPI."""
    cache = load_cache()

    # Check cache validity
    if not force and cache.get("checked_at"):
        try:
            checked_at = datetime.fromisoformat(cache["checked_at"])
            if datetime.now() - checked_at < timedelta(hours=CACHE_TTL_HOURS):
                latest = cache.get("latest_version")
                if latest:
                    return latest
        except (ValueError, TypeError):
            pass

    # Fetch from PyPI
    latest = fetch_latest_version()
    if latest:
        save_cache({
            "latest_version": latest,
            "checked_at": datetime.now().isoformat(),
        })
    return latest


def check_for_updates(current_version: str, force: bool = False) -> Optional[str]:
    """
    Check if a newer version is available.

    Returns the latest version string if update available, None otherwise.
    Uses cache to avoid frequent network requests.
    """
    latest = get_latest_version(force=force)
    if latest and parse_version(latest) > parse_version(current_version):
        return latest
    return None


def print_update_notice(current: str, latest: str) -> None:
    """Print update notice to stderr."""
    print(
        f"\n\033[33m[update available]\033[0m {current} → {latest}\n"
        f"  Run: \033[1muv tool install -U {PYPI_PACKAGE}\033[0m\n",
        file=sys.stderr,
    )


def maybe_check_updates(current_version: str) -> None:
    """Check for updates and print notice if available."""
    if not sys.stderr.isatty():
        return
    latest = check_for_updates(current_version)
    if latest:
        print_update_notice(current_version, latest)
