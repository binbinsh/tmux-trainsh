# tmux-trainsh job state management
# Persists recipe execution state for resume capability

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

from ..constants import CONFIG_DIR


# Directory for job state files
JOBS_DIR = CONFIG_DIR / "jobs"


@dataclass
class JobState:
    """Persistent state for a recipe execution job."""

    job_id: str
    recipe_path: str
    recipe_name: str
    current_step: int = 0
    total_steps: int = 0
    status: str = "running"  # running, completed, failed, cancelled

    # Runtime variables (for interpolation on resume)
    variables: Dict[str, str] = field(default_factory=dict)

    # Host connections (for reconnection on resume)
    # Maps host name -> resolved SSH spec
    hosts: Dict[str, str] = field(default_factory=dict)

    # Tmux session name on remote (for reconnection)
    tmux_session: str = ""

    # Vast.ai instance tracking
    vast_instance_id: Optional[str] = None
    vast_start_time: Optional[str] = None  # ISO format timestamp

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    # Error message if failed
    error: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class JobStateManager:
    """Manages persistent job states."""

    def __init__(self):
        JOBS_DIR.mkdir(parents=True, exist_ok=True)

    def _get_path(self, job_id: str, timestamp: Optional[str] = None) -> Path:
        """Get the file path for a job state."""
        if timestamp:
            return JOBS_DIR / f"{timestamp}_{job_id}.json"
        # Find existing file with timestamp prefix
        matches = list(JOBS_DIR.glob(f"*_{job_id}.json"))
        if matches:
            return matches[0]
        # New file with current timestamp
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return JOBS_DIR / f"{ts}_{job_id}.json"

    def save(self, state: JobState) -> None:
        """Save job state to disk."""
        state.updated_at = datetime.now().isoformat()
        # Find existing file or create new one
        path = self._get_path(state.job_id)
        with open(path, "w") as f:
            json.dump(asdict(state), f, indent=2)

    def load(self, job_id: str) -> Optional[JobState]:
        """Load job state from disk."""
        # Find file with timestamp prefix
        matches = list(JOBS_DIR.glob(f"*_{job_id}.json"))
        if not matches:
            # Try old format without timestamp
            old_path = JOBS_DIR / f"{job_id}.json"
            if old_path.exists():
                matches = [old_path]
        if not matches:
            return None
        path = matches[0]
        with open(path, "r") as f:
            data = json.load(f)
        return JobState(**data)

    def delete(self, job_id: str) -> None:
        """Delete job state file."""
        matches = list(JOBS_DIR.glob(f"*_{job_id}.json"))
        for path in matches:
            path.unlink()

    def find_by_recipe(self, recipe_path: str) -> Optional[JobState]:
        """Find the latest job state for a recipe path."""
        recipe_path = os.path.abspath(os.path.expanduser(recipe_path))
        latest: Optional[JobState] = None
        latest_time = ""

        for path in JOBS_DIR.glob("*.json"):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                state = JobState(**data)
                if state.recipe_path == recipe_path:
                    if state.updated_at > latest_time:
                        latest = state
                        latest_time = state.updated_at
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        return latest

    def find_resumable(self, recipe_path: str) -> Optional[JobState]:
        """Find a resumable job state for a recipe (running or failed)."""
        state = self.find_by_recipe(recipe_path)
        if state and state.status in ("running", "failed"):
            return state
        return None

    def list_all(self, limit: int = 20) -> List[JobState]:
        """List all job states, sorted by updated_at descending."""
        states = []
        for path in JOBS_DIR.glob("*.json"):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                state = JobState(**data)
                states.append(state)
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        states.sort(key=lambda s: s.updated_at, reverse=True)
        return states[:limit]

    def list_running(self) -> List[JobState]:
        """List running job states."""
        return [s for s in self.list_all(limit=100) if s.status == "running"]

    def cleanup_old(self, days: int = 7) -> int:
        """Clean up job states older than specified days."""
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)
        count = 0

        for path in JOBS_DIR.glob("*.json"):
            state = self.load(path.stem)
            if state and state.status in ("completed", "cancelled"):
                updated = datetime.fromisoformat(state.updated_at)
                if updated < cutoff:
                    self.delete(state.job_id)
                    count += 1

        return count


def generate_job_id() -> str:
    """Generate a unique job ID."""
    import uuid
    return str(uuid.uuid4())[:8]


def get_tmux_session_name(job_id: str) -> str:
    """Get the tmux session name for a job."""
    return f"trainsh-{job_id}"


def check_remote_condition(host_spec: str, condition: str) -> tuple[bool, str]:
    """
    Check a condition on a remote host.

    Args:
        host_spec: SSH host spec (e.g., "root@host -p 22")
        condition: Condition string (e.g., "file:/path/to/file")

    Returns:
        (condition_met, message)
    """
    import subprocess
    import shlex

    if condition.startswith("file:"):
        filepath = condition[5:]
        cmd = f"test -f {shlex.quote(filepath)} && echo EXISTS || echo NOTFOUND"
    else:
        return False, f"Unknown condition type: {condition}"

    # Build SSH command
    tokens = shlex.split(host_spec) if host_spec else []
    ssh_args = ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes"]

    host = ""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            ssh_args.append(token)
            if token in {"-p", "-i", "-J", "-o", "-F"}:
                if i + 1 < len(tokens):
                    ssh_args.append(tokens[i + 1])
                    i += 1
        elif not host:
            host = token
        i += 1

    if not host:
        host = host_spec

    ssh_args.append(host)
    ssh_args.append(cmd)

    try:
        result = subprocess.run(
            ssh_args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if "EXISTS" in result.stdout:
            return True, f"Condition met: {condition}"
        return False, f"Condition not met: {condition}"
    except subprocess.TimeoutExpired:
        return False, "SSH connection timeout"
    except Exception as e:
        return False, f"SSH error: {e}"
