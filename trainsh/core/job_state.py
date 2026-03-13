# tmux-trainsh job state management
# Persists recipe execution state in runtime.db for resume capability

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .runtime_db import (
    connect_runtime_db,
    json_dumps,
    json_loads,
    load_run_hosts,
    load_run_storages,
    load_run_windows,
    replace_run_hosts,
    replace_run_storages,
    replace_run_windows,
)


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
    """Manages persistent job states in sqlite."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def save(self, state: JobState) -> None:
        state.updated_at = datetime.now().isoformat()
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            conn.execute(
                """
                INSERT INTO job_checkpoint (
                    run_id, recipe_path, recipe_name, current_step, total_steps, status,
                    variables_json, next_window_index, tmux_session, bridge_session,
                    vast_instance_id, vast_start_time, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    recipe_path=excluded.recipe_path,
                    recipe_name=excluded.recipe_name,
                    current_step=excluded.current_step,
                    total_steps=excluded.total_steps,
                    status=excluded.status,
                    variables_json=excluded.variables_json,
                    next_window_index=excluded.next_window_index,
                    tmux_session=excluded.tmux_session,
                    bridge_session=excluded.bridge_session,
                    vast_instance_id=excluded.vast_instance_id,
                    vast_start_time=excluded.vast_start_time,
                    error=excluded.error,
                    created_at=COALESCE(job_checkpoint.created_at, excluded.created_at),
                    updated_at=excluded.updated_at
                """,
                (
                    state.job_id,
                    os.path.abspath(os.path.expanduser(state.recipe_path)),
                    state.recipe_name,
                    int(state.current_step),
                    int(state.total_steps),
                    state.status,
                    json_dumps(state.variables),
                    int(state.next_window_index),
                    state.tmux_session,
                    state.bridge_session,
                    state.vast_instance_id,
                    state.vast_start_time,
                    state.error,
                    state.created_at,
                    state.updated_at,
                ),
            )
            replace_run_windows(
                conn,
                state.job_id,
                {
                    name: {
                        "host": spec,
                        "remote_session": state.window_sessions.get(name, ""),
                    }
                    for name, spec in state.hosts.items()
                },
            )
            if state.hosts:
                replace_run_hosts(conn, state.job_id, state.hosts)
            if state.storages:
                replace_run_storages(conn, state.job_id, state.storages)
            conn.commit()
        finally:
            conn.close()

    def load(self, job_id: str) -> Optional[JobState]:
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            row = conn.execute(
                """
                SELECT run_id, recipe_path, recipe_name, current_step, total_steps, status,
                       variables_json, next_window_index, tmux_session, bridge_session,
                       vast_instance_id, vast_start_time, error, created_at, updated_at
                FROM job_checkpoint
                WHERE run_id=?
                """,
                (job_id,),
            ).fetchone()
            if not row:
                return None
            windows = load_run_windows(conn, job_id)
            stored_hosts = load_run_hosts(conn, job_id)
            for name, payload in windows.items():
                host_spec = payload.get("host", "")
                if host_spec:
                    stored_hosts[name] = host_spec
            return JobState(
                job_id=str(row["run_id"]),
                recipe_path=str(row["recipe_path"]),
                recipe_name=str(row["recipe_name"]),
                current_step=int(row["current_step"] or 0),
                total_steps=int(row["total_steps"] or 0),
                status=str(row["status"]),
                variables=dict(json_loads(row["variables_json"], {})),
                hosts=stored_hosts,
                storages=load_run_storages(conn, job_id),
                window_sessions={name: payload.get("remote_session", "") for name, payload in windows.items()},
                next_window_index=int(row["next_window_index"] or 0),
                tmux_session=str(row["tmux_session"] or ""),
                bridge_session=str(row["bridge_session"] or ""),
                vast_instance_id=row["vast_instance_id"],
                vast_start_time=row["vast_start_time"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                error=str(row["error"] or ""),
            )
        finally:
            conn.close()

    def delete(self, job_id: str) -> None:
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            conn.execute("DELETE FROM run_window WHERE run_id=?", (job_id,))
            conn.execute("DELETE FROM job_checkpoint WHERE run_id=?", (job_id,))
            conn.commit()
        finally:
            conn.close()

    def find_by_recipe(self, recipe_path: str) -> Optional[JobState]:
        recipe_path = os.path.abspath(os.path.expanduser(recipe_path))
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            row = conn.execute(
                """
                SELECT run_id
                FROM job_checkpoint
                WHERE recipe_path=?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (recipe_path,),
            ).fetchone()
        finally:
            conn.close()
        return self.load(str(row["run_id"])) if row else None

    def find_resumable(self, recipe_path: str) -> Optional[JobState]:
        recipe_path = os.path.abspath(os.path.expanduser(recipe_path))
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            row = conn.execute(
                """
                SELECT run_id
                FROM job_checkpoint
                WHERE recipe_path=? AND status IN ('running', 'failed')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (recipe_path,),
            ).fetchone()
        finally:
            conn.close()
        return self.load(str(row["run_id"])) if row else None

    def list_all(self, limit: int = 20) -> List[JobState]:
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            rows = conn.execute(
                """
                SELECT run_id
                FROM job_checkpoint
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        finally:
            conn.close()
        return [state for row in rows if (state := self.load(str(row["run_id"])))]

    def list_running(self) -> List[JobState]:
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            rows = conn.execute(
                """
                SELECT run_id
                FROM job_checkpoint
                WHERE status='running'
                ORDER BY updated_at DESC
                """
            ).fetchall()
        finally:
            conn.close()
        return [state for row in rows if (state := self.load(str(row["run_id"])))]

    def cleanup_old(self, days: int = 7) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = connect_runtime_db(self.db_path, check_same_thread=False)
        try:
            rows = conn.execute(
                """
                SELECT run_id
                FROM job_checkpoint
                WHERE status IN ('completed', 'cancelled') AND updated_at < ?
                """,
                (cutoff,),
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in rows]
            if not run_ids:
                return 0
            conn.executemany("DELETE FROM run_window WHERE run_id=?", [(run_id,) for run_id in run_ids])
            conn.executemany("DELETE FROM job_checkpoint WHERE run_id=?", [(run_id,) for run_id in run_ids])
            conn.commit()
        finally:
            conn.close()
        return len(run_ids)


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


__all__ = ["JobState", "JobStateManager", "check_remote_condition", "generate_job_id"]
