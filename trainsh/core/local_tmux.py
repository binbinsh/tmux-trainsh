# tmux-trainsh local tmux adapter
# Local tmux client backed by tmux CLI via subprocess.

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class TmuxCmdResult:
    """Normalized tmux command result."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class LocalTmuxClient:
    """Local tmux client backed by subprocess tmux CLI."""

    def __init__(self):
        self._tmux_binary_available = shutil.which("tmux") is not None
        self._backend = "subprocess" if self._tmux_binary_available else "unavailable"

    @property
    def available(self) -> bool:
        """Whether tmux binary is available."""
        return self._tmux_binary_available

    @property
    def backend(self) -> str:
        """Backend name for diagnostics."""
        return self._backend

    def _unavailable(self) -> TmuxCmdResult:
        return TmuxCmdResult(127, "", "tmux binary not found")

    def _tmux_env(self) -> dict[str, str]:
        env = os.environ.copy()
        term = env.get("TERM", "").strip().lower()
        if term in {"", "dumb", "unknown"}:
            env["TERM"] = "xterm-256color"
        return env

    def run(self, *args: str, timeout: Optional[int] = None) -> TmuxCmdResult:
        """Run tmux command through subprocess."""
        if not self._tmux_binary_available:
            return self._unavailable()
        try:
            cp = subprocess.run(
                ["tmux", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._tmux_env(),
            )
            return TmuxCmdResult(cp.returncode, cp.stdout or "", cp.stderr or "")
        except subprocess.TimeoutExpired:
            return TmuxCmdResult(124, "", "tmux command timed out")
        except Exception as e:
            return TmuxCmdResult(1, "", str(e))

    def run_line(self, command_line: str, timeout: Optional[int] = None) -> TmuxCmdResult:
        command_line = command_line.strip()
        if command_line.startswith("tmux "):
            command_line = command_line[5:]
        args = shlex.split(command_line)
        return self.run(*args, timeout=timeout)

    def has_session(self, name: str) -> bool:
        result = self.run("has-session", "-t", name)
        return result.returncode == 0

    def new_session(
        self,
        name: str,
        detached: bool = True,
        window_name: Optional[str] = None,
        command: Optional[str] = None,
    ) -> TmuxCmdResult:
        if not self._tmux_binary_available:
            return self._unavailable()

        args = ["new-session", "-s", name]
        if detached:
            args.append("-d")
        if window_name:
            args.extend(["-n", window_name])
        if command:
            args.append(command)

        # For interactive attach mode, inherit terminal so tmux can take control.
        if not detached:
            try:
                cp = subprocess.run(["tmux", *args], env=self._tmux_env())
                return TmuxCmdResult(cp.returncode, "", "")
            except Exception as e:
                return TmuxCmdResult(1, "", str(e))

        return self.run(*args)

    def kill_session(self, name: str) -> TmuxCmdResult:
        return self.run("kill-session", "-t", name)

    def list_sessions(self, fmt: str = "#{session_name}") -> list[str]:
        result = self.run("list-sessions", "-F", fmt)
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_windows(self, target: str, fmt: str = "#{window_name}") -> list[str]:
        result = self.run("list-windows", "-t", target, "-F", fmt)
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_panes(self, target: str, fmt: str = "#{pane_id}") -> list[str]:
        result = self.run("list-panes", "-t", target, "-F", fmt)
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def display_message(self, target: str, fmt: str) -> TmuxCmdResult:
        return self.run("display-message", "-p", "-t", target, fmt)

    def split_window(
        self,
        target: str,
        command: str,
        horizontal: bool,
    ) -> TmuxCmdResult:
        split_flag = "-h" if horizontal else "-v"
        return self.run(
            "split-window",
            split_flag,
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            target,
            command,
        )

    def set_pane_title(self, pane_id: str, title: str) -> TmuxCmdResult:
        return self.run("select-pane", "-t", pane_id, "-T", title)

    def select_layout(self, target: str, layout: str) -> TmuxCmdResult:
        return self.run("select-layout", "-t", target, layout)

    def kill_pane(self, pane_id: str) -> TmuxCmdResult:
        return self.run("kill-pane", "-t", pane_id)

    def send_keys(self, target: str, text: str, enter: bool = True, literal: bool = True) -> TmuxCmdResult:
        if literal:
            result = self.run("send-keys", "-t", target, "-l", text)
        else:
            result = self.run("send-keys", "-t", target, text)
        if result.returncode != 0:
            return result
        if enter:
            return self.run("send-keys", "-t", target, "Enter")
        return result

    def capture_pane(self, target: str, start: Optional[str] = None, end: Optional[str] = None) -> TmuxCmdResult:
        args = ["capture-pane", "-t", target, "-p"]
        if start is not None:
            args.extend(["-S", str(start)])
        if end is not None:
            args.extend(["-E", str(end)])
        return self.run(*args)

    def wait_for(self, signal: str, timeout: Optional[int] = None) -> TmuxCmdResult:
        return self.run("wait-for", signal, timeout=timeout)

    def build_attach_command(self, session: str, nested: bool = False) -> str:
        quoted = shlex.quote(session)
        if nested:
            return f"TMUX= tmux attach -t {quoted} || TMUX= tmux new-session -A -s {quoted}"
        return f"tmux attach -t {quoted} || tmux new-session -A -s {quoted}"
