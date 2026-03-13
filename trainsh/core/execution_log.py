# tmux-trainsh execution log
# Detailed execution logs are persisted in runtime.db

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .runtime_db import (
    connect_runtime_db,
    json_dumps,
    json_loads,
    load_run_hosts,
    load_run_storages,
)


class ExecutionLogger:
    """Detailed execution logger backed by sqlite events."""

    def __init__(self, job_id: str, recipe_name: str, db_path: Optional[str] = None):
        self.job_id = job_id
        self.recipe_name = recipe_name
        self.conn = connect_runtime_db(db_path, check_same_thread=False)
        self._step_count = 0
        self._closed = False

    def _write(self, event: str, *, step_num: Optional[int] = None, **payload: Any) -> None:
        if self._closed:
            return
        ts = datetime.now().isoformat()
        self.conn.execute(
            """
            INSERT INTO recipe_events (run_id, event_name, step_num, payload_json, ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                self.job_id,
                event,
                step_num,
                json_dumps(payload),
                ts,
            ),
        )
        self.conn.commit()

    def start(
        self,
        recipe_name: str,
        variables: Dict[str, Any],
        hosts: Optional[Dict[str, str]] = None,
        recipe_path: str = "",
    ) -> None:
        """Lifecycle start is already persisted by callback sinks."""
        del recipe_name, variables, hosts, recipe_path

    def step_start(self, step_num: int, raw: str, step_type: str, details: Dict[str, Any]) -> None:
        """Lifecycle step start is already persisted by callback sinks."""
        self._step_count = step_num
        del raw, step_type, details

    def step_output(self, step_num: int, output: str, output_type: str = "result") -> None:
        max_chunk = 50000
        if len(output) > max_chunk:
            total_chunks = (len(output) + max_chunk - 1) // max_chunk
            for i in range(0, len(output), max_chunk):
                self._write(
                    "step_output",
                    step_num=step_num,
                    output_type=output_type,
                    output=output[i:i + max_chunk],
                    chunk=i // max_chunk,
                    total_chunks=total_chunks,
                )
            return
        self._write("step_output", step_num=step_num, output_type=output_type, output=output)

    def step_end(
        self,
        step_num: int,
        success: bool,
        duration_ms: int,
        result: str = "",
        error: str = "",
    ) -> None:
        """Lifecycle step end is already persisted by callback sinks."""
        self._step_count = step_num
        del success, duration_ms, result, error

    def log_detail(self, category: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        payload = {"category": category, "message": message}
        if data:
            payload["data"] = data
        self._write("detail", **payload)

    def log_ssh(self, host: str, command: str, returncode: int, stdout: str, stderr: str, duration_ms: int) -> None:
        self._write(
            "ssh_command",
            host=host,
            command=command,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    def log_tmux(self, operation: str, target: str, args: Dict[str, Any], success: bool, result: str) -> None:
        self._write(
            "tmux_operation",
            operation=operation,
            target=target,
            args=args,
            success=success,
            result=result,
        )

    def log_vast(
        self,
        operation: str,
        instance_id: Optional[int],
        request: Dict[str, Any],
        response: Dict[str, Any],
        success: bool,
    ) -> None:
        self._write(
            "vast_api",
            operation=operation,
            instance_id=instance_id,
            request=request,
            response=response,
            success=success,
        )

    def log_transfer(
        self,
        source: str,
        dest: str,
        method: str,
        bytes_transferred: int,
        duration_ms: int,
        success: bool,
        details: str,
    ) -> None:
        self._write(
            "file_transfer",
            source=source,
            dest=dest,
            method=method,
            bytes_transferred=bytes_transferred,
            duration_ms=duration_ms,
            success=success,
            details=details,
        )

    def log_wait(self, target: str, condition: str, elapsed_sec: int, remaining_sec: int, status: str) -> None:
        self._write(
            "wait_poll",
            target=target,
            condition=condition,
            elapsed_sec=elapsed_sec,
            remaining_sec=remaining_sec,
            status=status,
        )

    def log_variable(self, name: str, value: str, source: str) -> None:
        self._write(
            "variable_set",
            name=name,
            value=value,
            source=source,
        )

    def end(
        self,
        success: bool,
        duration_ms: int,
        final_variables: Optional[Dict[str, str]] = None,
    ) -> None:
        """Lifecycle end is already persisted by callback sinks."""
        del success, duration_ms, final_variables
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.conn.close()

    def __del__(self):
        if not self._closed and hasattr(self, "conn"):
            try:
                self.close()
            except Exception:
                pass


class ExecutionLogReader:
    """Execution log reader backed by runtime.db."""

    def __init__(self, db_path: Optional[str] = None):
        self.conn = connect_runtime_db(db_path, check_same_thread=False)

    def list_executions(self, limit: int = 20) -> List[dict]:
        rows = self.conn.execute(
            """
            SELECT run_id, recipe_name, recipe_path, started_at, success, duration_ms
            FROM recipe_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [
            {
                "job_id": str(row["run_id"]),
                "recipe": str(row["recipe_name"]),
                "recipe_path": str(row["recipe_path"]),
                "started": str(row["started_at"]),
                "success": row["success"] if row["success"] is not None else None,
                "duration_ms": int(row["duration_ms"] or 0),
                "file": "",
                "host_count": len(load_run_hosts(self.conn, str(row["run_id"]))),
                "storage_count": len(load_run_storages(self.conn, str(row["run_id"]))),
            }
            for row in rows
        ]

    def read_execution(self, job_id: str) -> List[dict]:
        rows = self.conn.execute(
            """
            SELECT event_name, step_num, payload_json, ts
            FROM recipe_events
            WHERE run_id=?
            ORDER BY event_id ASC
            """,
            (job_id,),
        ).fetchall()
        entries: List[dict] = []
        for row in rows:
            payload = json_loads(row["payload_json"], {})
            entry = {
                "event": str(row["event_name"]),
                "job_id": job_id,
                "step_num": row["step_num"],
                "ts": str(row["ts"]),
            }
            if isinstance(payload, dict):
                entry.update(payload)
            else:
                entry["payload"] = payload
            entries.append(entry)
        return entries

    def get_step_output(self, job_id: str, step_num: int) -> str:
        entries = self.read_execution(job_id)
        chunks = []
        for entry in entries:
            if entry.get("event") == "step_output" and entry.get("step_num") == step_num:
                chunks.append((entry.get("chunk", 0), entry.get("output", "")))
        chunks.sort(key=lambda item: item[0])
        return "".join(output for _, output in chunks)

    def get_execution_summary(self, job_id: str) -> Optional[dict]:
        run_row = self.conn.execute(
            """
            SELECT run_id, recipe_name, recipe_path, started_at, ended_at, success, duration_ms
            FROM recipe_runs
            WHERE run_id=?
            """,
            (job_id,),
        ).fetchone()
        if not run_row:
            return None

        summary = {
            "job_id": str(run_row["run_id"]),
            "recipe": str(run_row["recipe_name"]),
            "recipe_path": str(run_row["recipe_path"]),
            "started": str(run_row["started_at"]),
            "ended": str(run_row["ended_at"] or ""),
            "success": run_row["success"] if run_row["success"] is not None else None,
            "duration_ms": int(run_row["duration_ms"] or 0),
            "steps": [],
            "variables": {},
            "hosts": load_run_hosts(self.conn, job_id),
            "storages": load_run_storages(self.conn, job_id),
            "recent_events": [],
        }

        for entry in self.read_execution(job_id):
            event = entry.get("event")
            if event == "execution_start":
                summary["variables"] = entry.get("variables", {}) or {}
            elif event == "execution_end":
                final_variables = entry.get("final_variables", {}) or {}
                if final_variables:
                    summary["variables"] = final_variables
            elif event == "step_end":
                summary["steps"].append(
                    {
                        "step_num": entry.get("step_num", 0),
                        "success": entry.get("success"),
                        "duration_ms": entry.get("duration_ms", 0),
                        "result": entry.get("output", ""),
                        "error": entry.get("error", ""),
                    }
                )

        summary["recent_events"] = self.list_recent_events(job_id, limit=10)
        return summary

    def get_full_log(self, job_id: str) -> List[dict]:
        return self.read_execution(job_id)

    def list_recent_events(
        self,
        job_id: str,
        *,
        limit: int = 10,
        exclude_events: Optional[set[str]] = None,
    ) -> List[dict]:
        excluded = set(exclude_events or {"step_output", "wait_poll"})
        rows = self.conn.execute(
            """
            SELECT event_name, step_num, payload_json, ts
            FROM recipe_events
            WHERE run_id=?
            ORDER BY event_id DESC
            LIMIT ?
            """,
            (job_id, max(int(limit) * 5, int(limit))),
        ).fetchall()
        events: List[dict] = []
        for row in rows:
            event_name = str(row["event_name"])
            if event_name in excluded:
                continue
            payload = json_loads(row["payload_json"], {})
            entry = {
                "event": event_name,
                "step_num": row["step_num"],
                "ts": str(row["ts"]),
            }
            if isinstance(payload, dict):
                entry.update(payload)
            else:
                entry["payload"] = payload
            events.append(entry)
            if len(events) >= limit:
                break
        events.reverse()
        return events

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "ExecutionLogReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def __del__(self):
        if hasattr(self, "conn"):
            self.close()


__all__ = ["ExecutionLogReader", "ExecutionLogger"]
