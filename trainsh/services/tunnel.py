"""Helpers for local SSH port-forward tunnels."""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from ..core.models import Host
from .ssh import SSHClient


@dataclass(frozen=True)
class TunnelSpec:
    """One local SSH tunnel specification."""

    local_port: int
    remote_port: int
    bind_host: str = "127.0.0.1"
    remote_host: str = "127.0.0.1"

    def forward_target(self) -> str:
        return f"{self.bind_host}:{self.local_port}:{self.remote_host}:{self.remote_port}"


def find_free_local_port(bind_host: str = "127.0.0.1") -> int:
    """Allocate one free local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((bind_host, 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def build_local_tunnel_args(host: Host, spec: TunnelSpec) -> list[str]:
    """Build ssh args for one local port-forward tunnel."""
    client = SSHClient.from_host(host)
    base = client._build_ssh_args(target=client.connection_targets[0], interactive=False)
    destination = base[-1]
    return [
        *base[:-1],
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-N",
        "-L",
        spec.forward_target(),
        destination,
    ]


def is_local_port_open(bind_host: str, port: int, timeout: float = 0.5) -> bool:
    """Check whether a local TCP port accepts connections."""
    try:
        with socket.create_connection((bind_host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_local_tunnel(
    process: subprocess.Popen,
    *,
    bind_host: str,
    local_port: int,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Wait until the tunnel accepts local connections or exits."""
    deadline = time.time() + max(0.1, float(timeout))
    while time.time() < deadline:
        if process.poll() is not None:
            stderr = ""
            if process.stderr is not None:
                try:
                    stderr = process.stderr.read() or ""
                except Exception:
                    stderr = ""
            stderr = stderr.strip()
            return False, stderr or f"ssh exited with code {process.returncode}"
        if is_local_port_open(bind_host, local_port):
            return True, ""
        time.sleep(0.2)
    return False, f"Timed out waiting for local tunnel on {bind_host}:{local_port}"


def start_local_tunnel(
    host: Host,
    spec: TunnelSpec,
    *,
    wait_timeout: float = 10.0,
) -> subprocess.Popen:
    """Start one background local tunnel and wait until it is ready."""
    args = build_local_tunnel_args(host, spec)
    process = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    ok, message = wait_for_local_tunnel(
        process,
        bind_host=spec.bind_host,
        local_port=spec.local_port,
        timeout=wait_timeout,
    )
    if ok:
        return process
    try:
        process.terminate()
    except Exception:
        pass
    raise RuntimeError(message)


def stop_process(process: Optional[subprocess.Popen]) -> None:
    """Best-effort stop for one background subprocess."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
        return
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        return
