# tmux-trainsh tmux service
# Unified local/remote tmux manager backed by tmux CLI.

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional

from ..core.local_tmux import LocalTmuxClient
from ..core.remote_tmux import RemoteTmuxClient
from .ssh import SSHClient


@dataclass
class TmuxResult:
    """Result of a tmux operation."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class TmuxManager:
    """Manage tmux sessions either locally or over SSH."""

    def __init__(self, ssh: Optional[SSHClient] = None):
        self.ssh = ssh
        self.local_tmux = LocalTmuxClient() if ssh is None else None
        self.remote_tmux = RemoteTmuxClient(self._remote_label(), self._build_ssh_args) if ssh else None

    def _remote_label(self) -> str:
        if not self.ssh:
            return "remote"
        if self.ssh.username:
            return f"{self.ssh.username}@{self.ssh.hostname}"
        return self.ssh.hostname

    def _build_ssh_args(
        self,
        _host: str,
        command: Optional[str] = None,
        tty: bool = False,
        set_term: bool = False,
    ) -> list[str]:
        """Adapter to reuse SSHClient connection settings."""
        if not self.ssh:
            return []
        cmd = command
        if set_term and cmd:
            cmd = f"TERM=xterm-256color {cmd}"
        args = self.ssh._build_ssh_args(cmd)
        if tty and args and args[0] == "ssh":
            args.insert(1, "-tt")
        return args

    def create_session(
        self,
        name: str,
        command: Optional[str] = None,
        workdir: Optional[str] = None,
    ) -> TmuxResult:
        """Create detached tmux session if absent."""
        if self.remote_tmux:
            if not self.remote_tmux.has_session(name):
                result = self.remote_tmux.new_session(name, detached=True)
                if result.returncode != 0:
                    return TmuxResult(result.returncode, result.stdout, result.stderr)
            if command:
                payload = command
                if workdir:
                    payload = f"cd {shlex.quote(workdir)} && {command}"
                send_result = self.remote_tmux.send_keys(name, payload, enter=True, literal=True)
                return TmuxResult(send_result.returncode, send_result.stdout, send_result.stderr)
            return TmuxResult(0, "", "")

        if not self.local_tmux:
            return TmuxResult(1, "", "local tmux client unavailable")

        if not self.local_tmux.available:
            return TmuxResult(127, "", "tmux binary not found")

        if self.local_tmux.has_session(name):
            if command:
                payload = command
                if workdir:
                    payload = f"cd {shlex.quote(workdir)} && {command}"
                send_result = self.local_tmux.send_keys(name, payload, enter=True, literal=True)
                return TmuxResult(send_result.returncode, send_result.stdout, send_result.stderr)
            return TmuxResult(0, "", "")

        payload = None
        if command:
            payload = command
            if workdir:
                payload = f"cd {shlex.quote(workdir)} && {command}"

        result = self.local_tmux.new_session(name, detached=True, command=payload)
        return TmuxResult(result.returncode, result.stdout, result.stderr)

    def send_keys(self, session_name: str, keys: str) -> TmuxResult:
        """Send literal keys + Enter to a tmux session."""
        if self.remote_tmux:
            result = self.remote_tmux.send_keys(session_name, keys, enter=True, literal=True)
            return TmuxResult(result.returncode, result.stdout, result.stderr)

        if not self.local_tmux:
            return TmuxResult(1, "", "local tmux client unavailable")
        result = self.local_tmux.send_keys(session_name, keys, enter=True, literal=True)
        return TmuxResult(result.returncode, result.stdout, result.stderr)

    def capture_pane(self, session_name: str, lines: Optional[int] = None) -> str:
        """Capture pane output from a session."""
        if self.remote_tmux:
            start = f"-{max(1, int(lines or 200))}"
            result = self.remote_tmux.capture_pane(session_name, start=start)
            return result.stdout if result.returncode == 0 else ""

        if not self.local_tmux:
            return ""

        start = f"-{max(1, int(lines or 200))}"
        result = self.local_tmux.capture_pane(session_name, start=start)
        return result.stdout if result.returncode == 0 else ""

    def kill_session(self, session_name: str) -> TmuxResult:
        """Kill a tmux session."""
        if self.remote_tmux:
            result = self.remote_tmux.kill_session(session_name)
            # Keep cleanup best-effort semantics for callers.
            if result.returncode != 0:
                return TmuxResult(0, result.stdout, result.stderr)
            return TmuxResult(result.returncode, result.stdout, result.stderr)

        if not self.local_tmux:
            return TmuxResult(1, "", "local tmux client unavailable")
        result = self.local_tmux.kill_session(session_name)
        # Keep cleanup best-effort semantics for callers.
        if result.returncode != 0:
            return TmuxResult(0, result.stdout, result.stderr)
        return TmuxResult(result.returncode, result.stdout, result.stderr)
