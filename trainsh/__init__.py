# tmux-trainsh: GPU training workflow automation
# License: MIT

import os
import re
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


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


def _resolve_git_commit() -> str:
    """Resolve git commit hash (7 chars) for version display."""
    env_hash = os.getenv("TRAINSH_GIT_COMMIT", "").strip()
    if env_hash:
        return env_hash[:7]

    try:
        root = Path(__file__).resolve().parents[1]
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        ).strip()
        if re.fullmatch(r"[0-9a-fA-F]{7}", commit):
            return commit.lower()
    except (OSError, subprocess.SubprocessError):
        pass

    return "unknown"

try:
    __version__ = version("tmux-trainsh")
except PackageNotFoundError:
    __version__ = _read_local_version()

__git_commit__ = _resolve_git_commit()
if __git_commit__ != "unknown":
    __display_version__ = f"{__version__} ({__git_commit__})"
else:
    __display_version__ = __version__


def main(args: list[str]) -> str | None:
    """Entry point for trainsh command."""
    from .main import main as trainsh_main
    return trainsh_main(["trainsh"] + list(args))
