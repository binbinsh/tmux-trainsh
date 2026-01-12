# tmux-trainsh execution log
# JSONL.GZ format for recipe execution logging
# Logs are stored in jobs/{job_id}.jsonl.gz alongside job state files

import gzip
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Any, Dict

from ..constants import CONFIG_DIR


# Jobs directory for both state and logs
JOBS_DIR = CONFIG_DIR / "jobs"


def get_jobs_dir() -> Path:
    """Get the jobs directory path (for both state and logs)."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return JOBS_DIR


class ExecutionLogger:
    """
    Execution logger using JSONL.GZ compressed storage.

    Features:
    - Real-time write (flush after each entry)
    - Compress to .gz after execution ends
    - Detailed logging by default
    - Stored in jobs/{job_id}.jsonl.gz alongside job state
    """

    def __init__(self, job_id: str, recipe_name: str):
        """
        Initialize execution logger.

        Args:
            job_id: Unique job ID (same as job state ID)
            recipe_name: Recipe name being executed
        """
        self.jobs_dir = get_jobs_dir()
        self.job_id = job_id
        self.recipe_name = recipe_name

        # Use uncompressed temp file during execution, compress at end
        # Store in jobs directory alongside job state: jobs/{timestamp}_{job_id}.jsonl.gz
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.file_prefix = f"{timestamp}_{job_id}"
        self.temp_file = self.jobs_dir / f"{self.file_prefix}.jsonl"
        self.final_file = self.jobs_dir / f"{self.file_prefix}.jsonl.gz"
        self._file = open(self.temp_file, "a", encoding="utf-8")
        self._closed = False
        self._step_count = 0

    def _write(self, event: str, **kwargs) -> None:
        """Write a log entry."""
        if self._closed:
            return

        entry = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "job_id": self.job_id,
            **kwargs
        }
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def start(self, recipe_name: str, variables: Dict[str, Any], hosts: Dict[str, str], recipe_path: str) -> None:
        """Log execution start with full context."""
        import platform
        import os
        self._write(
            "execution_start",
            recipe=recipe_name,
            recipe_path=recipe_path,
            variables=variables,
            hosts=hosts,
            environment={
                "platform": platform.system(),
                "python": platform.python_version(),
                "user": os.environ.get("USER", "unknown"),
                "cwd": os.getcwd(),
                "term": os.environ.get("TERM", "unknown"),
                "tmux": os.environ.get("TMUX", ""),
            }
        )

    def step_start(self, step_num: int, raw: str, step_type: str, details: Dict[str, Any]) -> None:
        """Log step start with full details."""
        self._step_count = step_num
        self._write(
            "step_start",
            step_num=step_num,
            raw=raw,
            step_type=step_type,
            details=details
        )

    def step_output(self, step_num: int, output: str, output_type: str = "result") -> None:
        """Log step output, chunking large outputs."""
        max_chunk = 50000  # Increased chunk size for more detail
        if len(output) > max_chunk:
            total_chunks = (len(output) + max_chunk - 1) // max_chunk
            for i in range(0, len(output), max_chunk):
                self._write(
                    "step_output",
                    step_num=step_num,
                    output_type=output_type,
                    output=output[i:i + max_chunk],
                    chunk=i // max_chunk,
                    total_chunks=total_chunks
                )
        else:
            self._write("step_output", step_num=step_num, output_type=output_type, output=output)

    def step_end(
        self,
        step_num: int,
        success: bool,
        duration_ms: int,
        result: str = "",
        error: str = ""
    ) -> None:
        """Log step end with full result."""
        self._write(
            "step_end",
            step_num=step_num,
            success=success,
            duration_ms=duration_ms,
            result=result,
            error=error
        )

    def log_detail(self, category: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log detailed information during execution."""
        entry = {
            "category": category,
            "message": message,
        }
        if data:
            entry["data"] = data
        self._write("detail", **entry)

    def log_ssh(self, host: str, command: str, returncode: int, stdout: str, stderr: str, duration_ms: int) -> None:
        """Log SSH command execution with full output."""
        self._write(
            "ssh_command",
            host=host,
            command=command,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms
        )

    def log_tmux(self, operation: str, target: str, args: Dict[str, Any], success: bool, result: str) -> None:
        """Log tmux terminal operation."""
        self._write(
            "tmux_operation",
            operation=operation,
            target=target,
            args=args,
            success=success,
            result=result
        )

    def log_vast(self, operation: str, instance_id: Optional[int], request: Dict[str, Any], response: Dict[str, Any], success: bool) -> None:
        """Log Vast.ai API operation."""
        self._write(
            "vast_api",
            operation=operation,
            instance_id=instance_id,
            request=request,
            response=response,
            success=success
        )

    def log_transfer(self, source: str, dest: str, method: str, bytes_transferred: int, duration_ms: int, success: bool, details: str) -> None:
        """Log file transfer operation."""
        self._write(
            "file_transfer",
            source=source,
            dest=dest,
            method=method,
            bytes_transferred=bytes_transferred,
            duration_ms=duration_ms,
            success=success,
            details=details
        )

    def log_wait(self, target: str, condition: str, elapsed_sec: int, remaining_sec: int, status: str) -> None:
        """Log wait/polling status."""
        self._write(
            "wait_poll",
            target=target,
            condition=condition,
            elapsed_sec=elapsed_sec,
            remaining_sec=remaining_sec,
            status=status
        )

    def log_variable(self, name: str, value: str, source: str) -> None:
        """Log variable set/change."""
        self._write(
            "variable_set",
            name=name,
            value=value,
            source=source
        )

    def end(self, success: bool, duration_ms: int, final_variables: Dict[str, str]) -> None:
        """Log execution end and compress the log file."""
        self._write(
            "execution_end",
            success=success,
            duration_ms=duration_ms,
            total_steps=self._step_count,
            final_variables=final_variables
        )
        self._file.close()
        self._closed = True
        self._compress()

    def _compress(self) -> None:
        """Compress the temp file to .gz."""
        try:
            with open(self.temp_file, "rb") as f_in:
                with gzip.open(self.final_file, "wb") as f_out:
                    f_out.writelines(f_in)
            self.temp_file.unlink()
        except Exception:
            # Keep the uncompressed file if compression fails
            pass

    def __del__(self):
        """Ensure file is closed on deletion."""
        if not self._closed and hasattr(self, '_file'):
            try:
                self._file.close()
            except Exception:
                pass


class ExecutionLogReader:
    """Execution log reader supporting .gz compressed logs in jobs directory."""

    def __init__(self):
        self.jobs_dir = get_jobs_dir()

    def list_executions(self, limit: int = 20) -> List[dict]:
        """List recent execution records."""
        # Support both .jsonl and .jsonl.gz in jobs directory
        logs = list(self.jobs_dir.glob("*.jsonl.gz")) + list(self.jobs_dir.glob("*.jsonl"))
        logs = sorted(logs, key=lambda p: p.stat().st_mtime, reverse=True)

        results = []
        for log in logs[:limit]:
            try:
                first_line = self._read_first_line(log)
                if first_line:
                    first = json.loads(first_line)
                    if first.get("event") != "execution_start":
                        continue
                    # Get last entry for status
                    last = self._read_last_line(log)
                    last_data = json.loads(last) if last else {}

                    results.append({
                        "job_id": first.get("job_id", ""),
                        "recipe": first.get("recipe", ""),
                        "recipe_path": first.get("recipe_path", ""),
                        "started": first.get("ts", ""),
                        "success": last_data.get("success") if last_data.get("event") == "execution_end" else None,
                        "duration_ms": last_data.get("duration_ms", 0) if last_data.get("event") == "execution_end" else 0,
                        "file": str(log),
                    })
            except Exception:
                continue
        return results

    def _read_first_line(self, path: Path) -> Optional[str]:
        """Read first line of file (supports .gz)."""
        if path.suffix == ".gz" or path.name.endswith(".jsonl.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return f.readline()
        else:
            with open(path, "r", encoding="utf-8") as f:
                return f.readline()

    def _read_last_line(self, path: Path) -> Optional[str]:
        """Read last line of file (supports .gz)."""
        lines = self._read_all_lines(path)
        return lines[-1] if lines else None

    def _read_all_lines(self, path: Path) -> List[str]:
        """Read all lines from file."""
        if path.suffix == ".gz" or path.name.endswith(".jsonl.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        else:
            with open(path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]

    def read_execution(self, job_id: str) -> List[dict]:
        """Read all entries for an execution by job_id."""
        # Find matching file in jobs directory (with timestamp prefix)
        for pattern in [f"*_{job_id}.jsonl.gz", f"*_{job_id}.jsonl", f"{job_id}.jsonl.gz", f"{job_id}.jsonl"]:
            matches = list(self.jobs_dir.glob(pattern))
            if matches:
                return self._read_log_file(matches[0])
        return []

    def _read_log_file(self, path: Path) -> List[dict]:
        """Read all entries from a log file."""
        entries = []
        lines = self._read_all_lines(path)
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def get_step_output(self, job_id: str, step_num: int) -> str:
        """Get complete output for a specific step (merge chunks)."""
        entries = self.read_execution(job_id)
        chunks = []
        for entry in entries:
            if entry.get("event") == "step_output" and entry.get("step_num") == step_num:
                chunks.append((entry.get("chunk", 0), entry.get("output", "")))

        chunks.sort(key=lambda x: x[0])
        return "".join(output for _, output in chunks)

    def get_execution_summary(self, job_id: str) -> Optional[dict]:
        """Get summary of an execution."""
        entries = self.read_execution(job_id)
        if not entries:
            return None

        summary = {
            "job_id": job_id,
            "recipe": "",
            "recipe_path": "",
            "started": "",
            "ended": "",
            "success": None,
            "duration_ms": 0,
            "steps": [],
            "variables": {},
            "hosts": {},
        }

        for entry in entries:
            event = entry.get("event")
            if event == "execution_start":
                summary["recipe"] = entry.get("recipe", "")
                summary["recipe_path"] = entry.get("recipe_path", "")
                summary["started"] = entry.get("ts", "")
                summary["variables"] = entry.get("variables", {})
                summary["hosts"] = entry.get("hosts", {})
            elif event == "execution_end":
                summary["ended"] = entry.get("ts", "")
                summary["success"] = entry.get("success")
                summary["duration_ms"] = entry.get("duration_ms", 0)
            elif event == "step_end":
                summary["steps"].append({
                    "step_num": entry.get("step_num", 0),
                    "success": entry.get("success"),
                    "duration_ms": entry.get("duration_ms", 0),
                    "result": entry.get("result", ""),
                    "error": entry.get("error", ""),
                })

        return summary

    def get_full_log(self, job_id: str) -> List[dict]:
        """Get full detailed log for an execution."""
        return self.read_execution(job_id)
