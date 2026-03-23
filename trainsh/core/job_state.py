# tmux-trainsh job state management
# Persists recipe execution state in JSONL checkpoints for resume capability

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .runtime_store import RuntimeStore


@dataclass
class JobState:
    """Persistent state for a recipe execution job."""

    job_id: str
    recipe_path: str
    recipe_name: str
    current_step: int = 0
    total_steps: int = 0
    status: str = "running"  # running, completed, failed, cancelled
    variables: Dict[str, str] = field(default_factory=dict)
    hosts: Dict[str, str] = field(default_factory=dict)
    storages: Dict[str, object] = field(default_factory=dict)
    window_sessions: Dict[str, str] = field(default_factory=dict)
    next_window_index: int = 0
    tmux_session: str = ""
    bridge_session: str = ""
    vast_instance_id: Optional[str] = None
    vast_start_time: Optional[str] = None
    runpod_pod_id: Optional[str] = None
    runpod_start_time: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    error: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class JobStateManager:
    """Manages persistent job states in JSONL checkpoints."""

    def __init__(self, db_path: Optional[str] = None):
        self.store = RuntimeStore(db_path)

    def save(self, state: JobState) -> None:
        state.updated_at = datetime.now().isoformat()
        self.store.save_checkpoint(
            {
                "run_id": state.job_id,
                "recipe_path": os.path.abspath(os.path.expanduser(state.recipe_path)),
                "recipe_name": state.recipe_name,
                "current_step": int(state.current_step),
                "total_steps": int(state.total_steps),
                "status": state.status,
                "variables": dict(state.variables),
                "hosts": dict(state.hosts),
                "storages": dict(state.storages),
                "window_sessions": dict(state.window_sessions),
                "next_window_index": int(state.next_window_index),
                "tmux_session": state.tmux_session,
                "bridge_session": state.bridge_session,
                "vast_instance_id": state.vast_instance_id,
                "vast_start_time": state.vast_start_time,
                "runpod_pod_id": state.runpod_pod_id,
                "runpod_start_time": state.runpod_start_time,
                "error": state.error,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
            }
        )

    def load(self, job_id: str) -> Optional[JobState]:
        row = self.store.get_checkpoint(job_id)
        if not row:
            return None
        return JobState(
            job_id=str(row.get("run_id", "")),
            recipe_path=str(row.get("recipe_path", "")),
            recipe_name=str(row.get("recipe_name", "")),
            current_step=int(row.get("current_step", 0) or 0),
            total_steps=int(row.get("total_steps", 0) or 0),
            status=str(row.get("status", "running")),
            variables=dict(row.get("variables", {}) or {}),
            hosts=dict(row.get("hosts", {}) or {}),
            storages=dict(row.get("storages", {}) or {}),
            window_sessions=dict(row.get("window_sessions", {}) or {}),
            next_window_index=int(row.get("next_window_index", 0) or 0),
            tmux_session=str(row.get("tmux_session", "") or ""),
            bridge_session=str(row.get("bridge_session", "") or ""),
            vast_instance_id=row.get("vast_instance_id"),
            vast_start_time=row.get("vast_start_time"),
            runpod_pod_id=row.get("runpod_pod_id"),
            runpod_start_time=row.get("runpod_start_time"),
            created_at=str(row.get("created_at", "")),
            updated_at=str(row.get("updated_at", "")),
            error=str(row.get("error", "") or ""),
        )

    def delete(self, job_id: str) -> None:
        self.store.delete_checkpoint(job_id)

    def find_by_recipe(self, recipe_path: str) -> Optional[JobState]:
        record = self.store.latest_checkpoint_for_recipe(recipe_path)
        return self.load(str(record.get("run_id", ""))) if record else None

    def find_resumable(self, recipe_path: str) -> Optional[JobState]:
        record = self.store.latest_checkpoint_for_recipe(
            recipe_path,
            statuses={"running", "failed"},
        )
        return self.load(str(record.get("run_id", ""))) if record else None

    def list_all(self, limit: int = 20) -> List[JobState]:
        rows = self.store.list_checkpoints(limit=int(limit))
        return [state for row in rows if (state := self.load(str(row.get("run_id", ""))))]

    def list_running(self) -> List[JobState]:
        rows = self.store.list_checkpoints(status="running")
        return [state for row in rows if (state := self.load(str(row.get("run_id", ""))))]

    def cleanup_old(self, days: int = 7) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return self.store.cleanup_checkpoints(
            cutoff=cutoff,
            statuses={"completed", "cancelled"},
        )


def generate_job_id() -> str:
    """Generate a unique job ID."""
    import uuid

    return str(uuid.uuid4())[:8]


def check_remote_condition(host_spec: str, condition: str) -> tuple[bool, str]:
    """
    Check a condition on a remote host.

    Args:
        host_spec: SSH host spec (e.g., "root@host -p 22")
        condition: Condition string (e.g., "file:/path/to/file")

    Returns:
        (condition_met, message)
    """
    import shlex
    import subprocess

    if condition.startswith("file:"):
        filepath = condition[5:]
        cmd = f"test -f {shlex.quote(filepath)} && echo EXISTS || echo NOTFOUND"
    else:
        return False, f"Unknown condition type: {condition}"

    tokens = shlex.split(host_spec) if host_spec else []
    ssh_args = ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes"]

    host = ""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            ssh_args.append(token)
            if token in {"-p", "-i", "-J", "-o", "-F"} and i + 1 < len(tokens):
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


__all__ = ["JobState", "JobStateManager", "check_remote_condition", "generate_job_id"]
