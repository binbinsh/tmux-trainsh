# Update checker for tmux-trainsh
# Checks PyPI for newer versions and caches results

import json
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

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
    import os
    try:
        # Manually configure proxy from environment variables
        proxies = {}
        for var in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
            if os.environ.get(var):
                proxies["https"] = os.environ[var]
                proxies["http"] = os.environ[var]
                break

        proxy_handler = urllib.request.ProxyHandler(proxies)
        opener = urllib.request.build_opener(proxy_handler)

        req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
        with opener.open(req, timeout=15) as resp:
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


def _has_command(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    try:
        subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def detect_install_method() -> str:
    """
    Detect how tmux-trainsh was installed.

    Returns one of: 'uv_tool', 'pipx', 'uv_pip', 'pip'
    """
    # Don't use resolve() - symlinks in uv/tools point to uv/python which breaks detection
    exe_str = sys.executable

    # Check for uv tool install (e.g., ~/.local/share/uv/tools/tmux-trainsh/...)
    if "/.local/share/uv/tools/" in exe_str or "/uv/tools/" in exe_str:
        return "uv_tool"

    # Check for pipx install (e.g., ~/.local/pipx/venvs/tmux-trainsh/...)
    if "/.local/pipx/venvs/" in exe_str or "/pipx/venvs/" in exe_str:
        return "pipx"

    # For venv/pip installs, prefer uv pip if uv is available (faster)
    if _has_command("uv"):
        return "uv_pip"

    return "pip"


def get_update_command() -> str:
    """Return the appropriate update command based on install method."""
    method = detect_install_method()
    pkg = PYPI_PACKAGE

    commands = {
        "uv_tool": f"uv tool install -U {pkg}",
        "pipx": f"pipx upgrade {pkg}",
        "uv_pip": f"uv pip install -U {pkg}",
        "pip": f"pip install -U {pkg}",
    }
    return commands.get(method, f"pip install -U {pkg}")


def perform_update() -> Tuple[bool, str]:
    """
    Attempt to perform the update automatically.

    Returns (success, message) tuple.
    """
    method = detect_install_method()

    cmds = {
        "uv_tool": ["uv", "tool", "install", "-U", PYPI_PACKAGE],
        "pipx": ["pipx", "upgrade", PYPI_PACKAGE],
        "uv_pip": ["uv", "pip", "install", "-U", PYPI_PACKAGE],
        "pip": ["pip", "install", "-U", PYPI_PACKAGE],
    }

    cmd = cmds.get(method)
    if not cmd:
        return False, f"Unknown install method. Run manually: {get_update_command()}"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, f"Successfully updated. Restart to use the new version."
        else:
            error = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return False, f"Update failed: {error}\nRun manually: {' '.join(cmd)}"
    except subprocess.TimeoutExpired:
        return False, f"Update timed out. Run manually: {' '.join(cmd)}"
    except FileNotFoundError:
        # The tool (uv/pipx/pip) is not found
        return False, f"'{cmd[0]}' not found. Run manually: {get_update_command()}"
