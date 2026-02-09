# tmux-trainsh tmux naming helpers
# Centralized generation/parsing for tmux session names.

from __future__ import annotations

import re
from typing import Optional


def get_job_token(job_id: str) -> str:
    """Normalized short token used in tmux naming."""
    return (job_id or "")[:8]


def _sanitize_name(value: str) -> str:
    """Sanitize arbitrary names to tmux-safe snake-like segments."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value or "")
    normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
    return normalized or "job"


def get_job_name(recipe_name: str, job_id: str) -> str:
    """Human-readable job name used in tmux sessions."""
    recipe_token = _sanitize_name(recipe_name)
    return f"{recipe_token}_{get_job_token(job_id)}"


def get_session_name(recipe_name: str, job_id: str, index: int) -> str:
    """Unified tmux session naming: train_<job_name>_<index>."""
    return f"train_{get_job_name(recipe_name, job_id)}_{index}"


def get_live_session_name(recipe_name: str, job_id: str, index: int = 0) -> str:
    """Session name used when auto-entering tmux from a plain terminal."""
    return get_session_name(recipe_name, job_id, index)


def get_bridge_session_name(recipe_name: str, job_id: str, index: int = 0) -> str:
    """Detached local bridge session for a job."""
    return get_session_name(recipe_name, job_id, index)


def get_window_session_prefix(recipe_name: str, job_id: str) -> str:
    """Prefix for per-window tmux sessions of a job."""
    return f"train_{get_job_name(recipe_name, job_id)}_"


def get_window_session_name(recipe_name: str, job_id: str, index: int) -> str:
    """Deterministic tmux session name for a recipe window index."""
    return f"{get_window_session_prefix(recipe_name, job_id)}{index}"


def parse_window_session_index(session_name: str, recipe_name: str, job_id: str) -> Optional[int]:
    """Parse numeric window index from session name if it matches this job prefix."""
    prefix = get_window_session_prefix(recipe_name, job_id)
    if not session_name.startswith(prefix):
        return None
    suffix = session_name[len(prefix):]
    return int(suffix) if suffix.isdigit() else None

