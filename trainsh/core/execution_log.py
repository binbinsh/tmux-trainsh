# kitten-trainsh execution log
# JSONL.GZ format for recipe execution logging

import gzip
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List


def get_logs_dir() -> Path:
    """Get the logs directory path."""
    logs_dir = Path.home() / ".config" / "kitten-trainsh" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


class ExecutionLogger:
    """
    Execution logger using JSONL.GZ compressed storage.

    Features:
    - Real-time write (flush after each entry)
    - Compress to .gz after execution ends
    - Chunk large outputs
    """

    def __init__(self, exec_id: str, recipe_id: str):
        """
        Initialize execution logger.

        Args:
            exec_id: Unique execution ID
            recipe_id: Recipe ID being executed
        """
        self.logs_dir = get_logs_dir()
        self.exec_id = exec_id
        self.recipe_id = recipe_id

        # Use uncompressed temp file during execution, compress at end
        date_prefix = datetime.now().strftime("%Y-%m-%d")
        self.temp_file = self.logs_dir / f"{date_prefix}_{exec_id}.jsonl"
        self.final_file = self.logs_dir / f"{date_prefix}_{exec_id}.jsonl.gz"
        self._file = open(self.temp_file, "a", encoding="utf-8")
        self._closed = False

    def _write(self, event: str, **kwargs) -> None:
        """Write a log entry."""
        if self._closed:
            return

        entry = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "exec_id": self.exec_id,
            **kwargs
        }
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def start(self, recipe_name: str, variables: dict) -> None:
        """Log execution start."""
        self._write("execution_start", recipe=recipe_name, vars=variables)

    def step_start(self, step_id: str, name: str, operation: str) -> None:
        """Log step start."""
        self._write("step_start", step_id=step_id, name=name, op=operation)

    def step_output(self, step_id: str, output: str) -> None:
        """Log step output, chunking large outputs."""
        max_chunk = 10000
        if len(output) > max_chunk:
            for i in range(0, len(output), max_chunk):
                self._write(
                    "step_output",
                    step_id=step_id,
                    output=output[i:i + max_chunk],
                    chunk=i // max_chunk
                )
        else:
            self._write("step_output", step_id=step_id, output=output)

    def step_end(
        self,
        step_id: str,
        success: bool,
        duration_ms: int,
        error: str = ""
    ) -> None:
        """Log step end."""
        self._write(
            "step_end",
            step_id=step_id,
            ok=success,
            ms=duration_ms,
            error=error
        )

    def end(self, success: bool, duration_ms: int) -> None:
        """Log execution end and compress the log file."""
        self._write("execution_end", ok=success, ms=duration_ms)
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
    """Execution log reader supporting .gz compressed logs."""

    def __init__(self):
        self.logs_dir = get_logs_dir()

    def list_executions(self, limit: int = 20) -> List[dict]:
        """List recent execution records."""
        # Support both .jsonl and .jsonl.gz
        logs = list(self.logs_dir.glob("*.jsonl.gz")) + list(self.logs_dir.glob("*.jsonl"))
        logs = sorted(logs, key=lambda p: p.stat().st_mtime, reverse=True)

        results = []
        for log in logs[:limit]:
            try:
                first_line = self._read_first_line(log)
                if first_line:
                    first = json.loads(first_line)
                    # Get last entry for status
                    last = self._read_last_line(log)
                    last_data = json.loads(last) if last else {}

                    results.append({
                        "exec_id": first.get("exec_id", ""),
                        "recipe": first.get("recipe", ""),
                        "started": first.get("ts", ""),
                        "success": last_data.get("ok") if last_data.get("event") == "execution_end" else None,
                        "duration_ms": last_data.get("ms", 0) if last_data.get("event") == "execution_end" else 0,
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

    def read_execution(self, exec_id: str) -> List[dict]:
        """Read all entries for an execution."""
        # Find matching file
        for pattern in [f"*_{exec_id}.jsonl.gz", f"*_{exec_id}.jsonl"]:
            matches = list(self.logs_dir.glob(pattern))
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

    def get_step_output(self, exec_id: str, step_id: str) -> str:
        """Get complete output for a specific step (merge chunks)."""
        entries = self.read_execution(exec_id)
        chunks = []
        for entry in entries:
            if entry.get("event") == "step_output" and entry.get("step_id") == step_id:
                chunks.append((entry.get("chunk", 0), entry.get("output", "")))

        chunks.sort(key=lambda x: x[0])
        return "".join(output for _, output in chunks)

    def get_execution_summary(self, exec_id: str) -> Optional[dict]:
        """Get summary of an execution."""
        entries = self.read_execution(exec_id)
        if not entries:
            return None

        summary = {
            "exec_id": exec_id,
            "recipe": "",
            "started": "",
            "ended": "",
            "success": None,
            "duration_ms": 0,
            "steps": [],
        }

        for entry in entries:
            event = entry.get("event")
            if event == "execution_start":
                summary["recipe"] = entry.get("recipe", "")
                summary["started"] = entry.get("ts", "")
            elif event == "execution_end":
                summary["ended"] = entry.get("ts", "")
                summary["success"] = entry.get("ok")
                summary["duration_ms"] = entry.get("ms", 0)
            elif event == "step_end":
                summary["steps"].append({
                    "step_id": entry.get("step_id", ""),
                    "success": entry.get("ok"),
                    "duration_ms": entry.get("ms", 0),
                    "error": entry.get("error", ""),
                })

        return summary
