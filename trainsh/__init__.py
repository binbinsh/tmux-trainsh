# tmux-trainsh: GPU training workflow automation
# License: MIT

import os
import re
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .pyrecipe import Host, HostPath, Recipe, Storage, StoragePath, VastHost, load_python_recipe, official_uv_install_command


def _read_local_version() -> str:
    """Read fallback version from local pyproject.toml."""
    try:
        root = Path(__file__).resolve().parents[1]
        pyproject = root / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass
    return "0.0.0-dev"


def _should_prefer_local_version() -> bool:
    """Prefer the working tree version when running from a source checkout."""
    root = Path(__file__).resolve().parents[1]
    return (root / ".git").exists() and (root / "pyproject.toml").exists()


def _resolve_build_number() -> int:
    """Resolve build number from git commit count (1-based)."""
    env_num = os.getenv("TRAINSH_BUILD_NUMBER", "").strip()
    if env_num:
        try:
            return int(env_num)
        except ValueError:
            pass

    try:
        root = Path(__file__).resolve().parents[1]
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        ).strip()
        return int(count)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    return 0

_local_version = _read_local_version()
try:
    _installed_version = version("tmux-trainsh")
except PackageNotFoundError:
    __version__ = _local_version
else:
    __version__ = _local_version if _should_prefer_local_version() else _installed_version

__build_number__ = _resolve_build_number()
if __build_number__ > 0:
    __display_version__ = f"{__version__} (build {__build_number__})"
else:
    __display_version__ = __version__


def main(args: list[str]) -> str | None:
    """Entry point for trainsh command."""
    from .main import main as trainsh_main
    return trainsh_main(["trainsh"] + list(args))


__all__ = [
    "Host",
    "HostPath",
    "Recipe",
    "Storage",
    "StoragePath",
    "VastHost",
    "__build_number__",
    "__display_version__",
    "__version__",
    "load_python_recipe",
    "main",
    "official_uv_install_command",
]
