"""State and runtime helpers for managed vLLM services."""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..constants import STATE_DIR
from ..core.models import Host
from ..core.remote_tmux import RemoteTmuxClient
from .ssh import SSHClient


def _now_iso() -> str:
    return datetime.now().isoformat()


def sanitize_service_name(value: str) -> str:
    """Normalize arbitrary service names into CLI-safe identifiers."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower())
    text = text.strip("-.")
    return text or "vllm"


def default_service_name(model: str) -> str:
    """Derive a stable service name from the model identifier."""
    cleaned = str(model or "").strip().rstrip("/")
    return sanitize_service_name(cleaned.rsplit("/", 1)[-1] or cleaned)


def parse_duration(value: Any, *, default: int = 600) -> int:
    """Parse compact duration strings like 10s/5m/1h."""
    if value is None:
        return int(default)
    if isinstance(value, bool):
        return int(default)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower()
    if not text:
        return int(default)
    if text.endswith("h"):
        return max(0, int(float(text[:-1]) * 3600))
    if text.endswith("m"):
        return max(0, int(float(text[:-1]) * 60))
    if text.endswith("s"):
        return max(0, int(float(text[:-1])))
    return max(0, int(float(text)))


def normalize_gpu_selection(value: Any) -> tuple[str, int]:
    """Normalize a GPU selection into CUDA_VISIBLE_DEVICES text plus count."""
    if value is None:
        return "", 0
    if isinstance(value, bool):
        raise ValueError("gpus must be an integer, string, or iterable of integers")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("gpus must be non-negative")
        return str(value), 1
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("gpus cannot be empty")
        parts = [item.strip() for item in text.split(",") if item.strip()]
        if not parts:
            raise ValueError("gpus cannot be empty")
        normalized: list[str] = []
        for part in parts:
            parsed = int(part)
            if parsed < 0:
                raise ValueError("gpus must be non-negative")
            normalized.append(str(parsed))
        return ",".join(normalized), len(normalized)
    if isinstance(value, (list, tuple, set)):
        normalized = []
        for item in value:
            parsed = int(item)
            if parsed < 0:
                raise ValueError("gpus must be non-negative")
            normalized.append(str(parsed))
        if not normalized:
            raise ValueError("gpus cannot be empty")
        return ",".join(normalized), len(normalized)
    raise ValueError("gpus must be an integer, string, or iterable of integers")


def _services_dir() -> Path:
    root = STATE_DIR / "vllm" / "services"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class VllmServiceRecord:
    """Persisted metadata for one managed vLLM service."""

    name: str
    host_name: str
    host: Dict[str, Any]
    model: str
    port: int = 8000
    bind_host: str = "127.0.0.1"
    workdir: str = ""
    session_name: str = ""
    command: str = ""
    status: str = "starting"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.name = sanitize_service_name(self.name)
        self.host_name = str(self.host_name or "").strip()
        self.model = str(self.model or "").strip()
        self.bind_host = str(self.bind_host or "127.0.0.1").strip() or "127.0.0.1"
        self.workdir = str(self.workdir or "").strip()
        self.session_name = str(self.session_name or "").strip()
        self.command = str(self.command or "").strip()
        self.status = str(self.status or "starting").strip() or "starting"
        self.port = max(1, int(self.port or 8000))
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def direct_base_url(self) -> str:
        """Best-effort direct base URL from the stored host snapshot."""
        snapshot = self.host or {}
        hostname = str(snapshot.get("hostname", "")).strip()
        if not hostname:
            return ""
        return f"http://{hostname}:{self.port}/v1"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VllmServiceRecord":
        return cls(**dict(data or {}))


def service_path(name: str) -> Path:
    """Resolve the on-disk path for one service record."""
    return _services_dir() / f"{sanitize_service_name(name)}.json"


def save_service(record: VllmServiceRecord) -> None:
    """Persist one service record."""
    record.updated_at = _now_iso()
    target = service_path(record.name)
    target.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_service(name: str) -> Optional[VllmServiceRecord]:
    """Load one service record by name."""
    target = service_path(name)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return VllmServiceRecord.from_dict(payload)


def delete_service(name: str) -> None:
    """Delete one persisted service record."""
    target = service_path(name)
    try:
        target.unlink()
    except FileNotFoundError:
        return


def list_services() -> list[VllmServiceRecord]:
    """List all persisted service records."""
    records: list[VllmServiceRecord] = []
    for path in sorted(_services_dir().glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            records.append(VllmServiceRecord.from_dict(payload))
    records.sort(key=lambda item: (item.updated_at, item.name), reverse=True)
    return records


def resolve_service_host(record: VllmServiceRecord) -> Host:
    """Resolve one service host from config or stored snapshot."""
    try:
        from ..commands.host import load_hosts

        host = load_hosts().get(record.host_name)
        if host is not None:
            return Host.from_dict(host.to_dict())
    except Exception:
        pass
    return Host.from_dict(record.host)


def build_ssh_args_for_host(
    host: Host,
    command: Optional[str] = None,
    *,
    tty: bool = False,
    set_term: bool = False,
) -> list[str]:
    """Build SSH args from a Host snapshot."""
    resolved_command = command
    if set_term:
        env_prefix = "TERM=xterm-256color LC_ALL=en_US.UTF-8"
        if command:
            resolved_command = f"{env_prefix} {command}"
        else:
            resolved_command = f"{env_prefix} exec bash -l"
    client = SSHClient.from_host(host)
    args = client._build_ssh_args(resolved_command, interactive=tty)
    if tty and "ssh" in args:
        ssh_index = args.index("ssh")
        if "-t" not in args[ssh_index + 1 :]:
            args = [*args[: ssh_index + 1], "-t", *args[ssh_index + 1 :]]
    return args


def tmux_client_for_host(host: Host) -> RemoteTmuxClient:
    """Build a RemoteTmuxClient using one Host snapshot."""
    return RemoteTmuxClient(
        host.name or host.hostname or "host",
        lambda _spec, command=None, tty=False, set_term=False: build_ssh_args_for_host(
            host,
            command,
            tty=tty,
            set_term=set_term,
        ),
    )


def service_is_running(record: VllmServiceRecord) -> bool:
    """Check whether the stored tmux session still exists."""
    try:
        host = resolve_service_host(record)
        if not record.session_name:
            return False
        return tmux_client_for_host(host).has_session(record.session_name)
    except Exception:
        return False


def service_is_ready(record: VllmServiceRecord, *, timeout: int = 5) -> bool:
    """Probe the managed vLLM endpoint over SSH from the target host."""
    host = resolve_service_host(record)
    script = (
        "import sys, urllib.request\n"
        f"urls = ['http://127.0.0.1:{int(record.port)}/health', 'http://127.0.0.1:{int(record.port)}/v1/models']\n"
        "for url in urls:\n"
        "    try:\n"
        "        with urllib.request.urlopen(url, timeout=3) as resp:\n"
        "            status = int(getattr(resp, 'status', 0) or 0)\n"
        "            if 200 <= status < 400:\n"
        "                print(url)\n"
        "                raise SystemExit(0)\n"
        "    except Exception:\n"
        "        pass\n"
        "raise SystemExit(1)\n"
    )
    command = f"python3 - <<'PY'\n{script}PY"
    result = SSHClient.from_host(host).run(command, timeout=max(1, int(timeout)))
    return bool(result.success)


def build_vllm_serve_command(
    *,
    model: str,
    port: int,
    bind_host: str,
    workdir: str = "",
    env: Optional[Dict[str, Any]] = None,
    extra_args: Optional[list[str]] = None,
) -> str:
    """Build the shell command sent into the remote tmux session."""
    parts: list[str] = []
    if workdir:
        parts.append(f"cd {shlex.quote(os.path.expanduser(workdir))}")
    for key, value in dict(env or {}).items():
        cleaned_key = str(key).strip()
        if not cleaned_key:
            continue
        parts.append(f"export {cleaned_key}={shlex.quote('' if value is None else str(value))}")
    command = [
        "vllm",
        "serve",
        str(model),
        "--host",
        str(bind_host),
        "--port",
        str(int(port)),
        *(extra_args or []),
    ]
    parts.append(shlex.join(command))
    return f"bash -lc {shlex.quote('; '.join(parts))}"


def _arg_flag_name(value: Any) -> str:
    """Extract the leading option name from one CLI argument token."""
    text = str(value or "").strip()
    if not text.startswith("--"):
        return ""
    if "=" in text:
        text = text.split("=", 1)[0]
    return text


def apply_serve_tuning_defaults(
    extra_args: Optional[list[str]] = None,
    *,
    gpu_memory_utilization: Any = None,
) -> list[str]:
    """Add throughput-oriented defaults unless the caller already set them."""
    args = [str(item).strip() for item in (extra_args or []) if str(item).strip()]
    present_flags = {_arg_flag_name(item) for item in args}

    if "--gpu-memory-utilization" not in present_flags:
        value = "0.95" if gpu_memory_utilization is None else str(gpu_memory_utilization).strip()
        if value:
            args.append(f"--gpu-memory-utilization={value}")
            present_flags.add("--gpu-memory-utilization")
    if "--max-num-batched-tokens" not in present_flags:
        args.append("--max-num-batched-tokens=16384")
        present_flags.add("--max-num-batched-tokens")
    if "--max-num-seqs" not in present_flags:
        args.append("--max-num-seqs=64")
    return args
