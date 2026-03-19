# tmux-trainsh execution log
# Detailed execution logs are persisted in JSONL runtime state files.

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .runtime_store import RuntimeStore


class ExecutionLogger:
    """Detailed execution logger backed by JSONL events."""

    def __init__(self, job_id: str, recipe_name: str, db_path: Optional[str] = None):
        self.job_id = job_id
        self.recipe_name = recipe_name
        self.store = RuntimeStore(db_path)
        self._step_count = 0
        self._closed = False

    def _write(self, event: str, *, step_num: Optional[int] = None, **payload: Any) -> None:
        if self._closed:
            return
        self.store.append_event(
            {
                "run_id": self.job_id,
                "event": event,
                "event_name": event,
                "step_num": step_num,
                "payload": payload,
                "ts": datetime.now().isoformat(),
            }
        )

    def start(
        self,
        recipe_name: str,
        variables: Dict[str, Any],
        hosts: Optional[Dict[str, str]] = None,
        recipe_path: str = "",
    ) -> None:
        del recipe_name, variables, hosts, recipe_path

    def step_start(self, step_num: int, raw: str, step_type: str, details: Dict[str, Any]) -> None:
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
        self._write("variable_set", name=name, value=value, source=source)

    def end(
        self,
        success: bool,
        duration_ms: int,
        final_variables: Optional[Dict[str, str]] = None,
    ) -> None:
        del success, duration_ms, final_variables
        self.close()

    def close(self) -> None:
        self._closed = True

    def __del__(self):
        self.close()


class ExecutionLogReader:
    """Execution log reader backed by JSONL runtime state files."""

    def __init__(self, db_path: Optional[str] = None):
        self.store = RuntimeStore(db_path)

    def list_executions(self, limit: int = 20) -> List[dict]:
        rows = self.store.list_runs(limit=int(limit))
        return [
            {
                "job_id": str(row.get("run_id", "")),
                "recipe": str(row.get("recipe_name", "")),
                "recipe_path": str(row.get("recipe_path", "")),
                "started": str(row.get("started_at", "")),
                "success": row.get("success"),
                "duration_ms": int(row.get("duration_ms") or 0),
                "file": "",
                "host_count": len(row.get("hosts", {}) if isinstance(row.get("hosts"), dict) else {}),
                "storage_count": len(row.get("storages", {}) if isinstance(row.get("storages"), dict) else {}),
            }
            for row in rows
        ]

    def read_execution(self, job_id: str) -> List[dict]:
        entries: List[dict] = []
        for record in self.store.list_events(job_id):
            entry = {
                "event": str(record.get("event_name") or record.get("event") or ""),
                "job_id": job_id,
                "step_num": record.get("step_num"),
                "ts": str(record.get("ts", "")),
            }
            payload = record.get("payload", {})
            if isinstance(payload, dict):
                entry.update(payload)
            else:
                entry["payload"] = payload
            entries.append(entry)
        return entries

    def get_step_output(self, job_id: str, step_num: int) -> str:
        chunks = []
        for entry in self.read_execution(job_id):
            if entry.get("event") == "step_output" and entry.get("step_num") == step_num:
                chunks.append((entry.get("chunk", 0), entry.get("output", "")))
        chunks.sort(key=lambda item: item[0])
        return "".join(output for _, output in chunks)

    def get_execution_summary(self, job_id: str) -> Optional[dict]:
        run_row = self.store.get_run(job_id)
        if not run_row:
            return None

        summary = {
            "job_id": str(run_row.get("run_id", "")),
            "recipe": str(run_row.get("recipe_name", "")),
            "recipe_path": str(run_row.get("recipe_path", "")),
            "started": str(run_row.get("started_at", "")),
            "ended": str(run_row.get("ended_at", "")),
            "success": run_row.get("success"),
            "duration_ms": int(run_row.get("duration_ms") or 0),
            "steps": [],
            "variables": {},
            "hosts": run_row.get("hosts", {}) if isinstance(run_row.get("hosts"), dict) else {},
            "storages": run_row.get("storages", {}) if isinstance(run_row.get("storages"), dict) else {},
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
        events = []
        for entry in reversed(self.read_execution(job_id)):
            if entry.get("event") in excluded:
                continue
            events.append(entry)
            if len(events) >= limit:
                break
        events.reverse()
        return events

    def close(self) -> None:
        return None

    def __enter__(self) -> "ExecutionLogReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


__all__ = ["ExecutionLogReader", "ExecutionLogger"]
