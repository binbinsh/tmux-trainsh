# tmux-trainsh remote tmux adapter
# Remote tmux client over SSH using tmux CLI only (no remote Python/libtmux dependency).

from __future__ import annotations

import shlex
import subprocess
import uuid
from typing import Callable, Optional

from .local_tmux import TmuxCmdResult


class RemoteTmuxClient:
    """Remote tmux client over SSH, backed by tmux CLI on remote host."""

    def __init__(self, host: str, build_ssh_args: Callable[..., list[str]]):
        self.host = host
        self._build_ssh_args = build_ssh_args

    def _ssh_args(self, command: str, tty: bool = False, set_term: bool = False) -> list[str]:
        return self._build_ssh_args(self.host, command=command, tty=tty, set_term=set_term)

    def _run_shell(self, command: str, timeout: Optional[int] = None) -> TmuxCmdResult:
        ssh_args = self._ssh_args(command, tty=False, set_term=False)
        try:
            cp = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return TmuxCmdResult(124, "", "remote tmux command timed out")
        except Exception as e:
            return TmuxCmdResult(1, "", str(e))

        return TmuxCmdResult(cp.returncode, cp.stdout or "", cp.stderr or "")

    def _run_tmux(self, args: list[str], timeout: Optional[int] = None) -> TmuxCmdResult:
        cmd = "tmux " + " ".join(shlex.quote(a) for a in args)
        return self._run_shell(cmd, timeout=timeout)

    def build_shell_command(
        self,
        command: str,
        tty: bool = False,
        set_term: bool = False,
        force_extra_tty: bool = False,
    ) -> str:
        ssh_args = self._ssh_args(command, tty=tty, set_term=set_term)
        if force_extra_tty and ssh_args and ssh_args[0] == "ssh":
            ssh_args = [ssh_args[0], "-t", *ssh_args[1:]]
        return " ".join(shlex.quote(arg) for arg in ssh_args)

    def build_attach_command(self, session: str, status_mode: str = "off") -> str:
        attach_core = (
            f"tmux attach -t {shlex.quote(session)} "
            f"|| tmux new-session -A -s {shlex.quote(session)}"
        )

        if status_mode == "keep":
            remote_attach = attach_core
        elif status_mode == "bottom":
            remote_attach = (
                "orig_status=$(tmux show-options -gv status 2>/dev/null || echo on); "
                "orig_pos=$(tmux show-options -gv status-position 2>/dev/null || echo top); "
                "tmux set-option -gq status on; "
                "tmux set-option -gq status-position bottom; "
                f"{attach_core}; "
                "__rc=$?; "
                "tmux set-option -gq status \"$orig_status\" >/dev/null 2>&1 || true; "
                "tmux set-option -gq status-position \"$orig_pos\" >/dev/null 2>&1 || true; "
                "exit $__rc"
            )
        else:
            remote_attach = (
                "orig_status=$(tmux show-options -gv status 2>/dev/null || echo on); "
                "tmux set-option -gq status off; "
                f"{attach_core}; "
                "__rc=$?; "
                "tmux set-option -gq status \"$orig_status\" >/dev/null 2>&1 || true; "
                "exit $__rc"
            )

        return self.build_shell_command(
            remote_attach,
            tty=True,
            set_term=True,
            force_extra_tty=True,
        )

    def run(self, *args: str, timeout: Optional[int] = None) -> TmuxCmdResult:
        return self._run_tmux(list(args), timeout=timeout)

    def run_line(self, command_line: str, timeout: Optional[int] = None) -> TmuxCmdResult:
        command_line = command_line.strip()
        if command_line.startswith("tmux "):
            command_line = command_line[5:]
        return self.run(*shlex.split(command_line), timeout=timeout)

    def has_session(self, name: str) -> bool:
        result = self._run_tmux(["has-session", "-t", name])
        return result.returncode == 0

    def new_session(
        self,
        name: str,
        detached: bool = True,
        window_name: Optional[str] = None,
        command: Optional[str] = None,
    ) -> TmuxCmdResult:
        args = ["new-session", "-s", name]
        if detached:
            args.append("-d")
        if window_name:
            args.extend(["-n", window_name])
        if command:
            args.append(command)
        return self._run_tmux(args)

    def kill_session(self, name: str) -> TmuxCmdResult:
        return self._run_tmux(["kill-session", "-t", name])

    def list_sessions(self, fmt: str = "#{session_name}") -> list[str]:
        result = self._run_tmux(["list-sessions", "-F", fmt])
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_windows(self, target: str, fmt: str = "#{window_name}") -> list[str]:
        result = self._run_tmux(["list-windows", "-t", target, "-F", fmt])
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_panes(self, target: str, fmt: str = "#{pane_id}") -> list[str]:
        result = self._run_tmux(["list-panes", "-t", target, "-F", fmt])
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def display_message(self, target: str, fmt: str) -> TmuxCmdResult:
        return self._run_tmux(["display-message", "-p", "-t", target, fmt])

    def split_window(self, target: str, command: str, horizontal: bool) -> TmuxCmdResult:
        split_flag = "-h" if horizontal else "-v"
        return self._run_tmux(
            [
                "split-window",
                split_flag,
                "-P",
                "-F",
                "#{pane_id}",
                "-t",
                target,
                command,
            ]
        )

    def set_pane_title(self, pane_id: str, title: str) -> TmuxCmdResult:
        return self._run_tmux(["select-pane", "-t", pane_id, "-T", title])

    def select_layout(self, target: str, layout: str) -> TmuxCmdResult:
        return self._run_tmux(["select-layout", "-t", target, layout])

    def kill_pane(self, pane_id: str) -> TmuxCmdResult:
        return self._run_tmux(["kill-pane", "-t", pane_id])

    def send_keys(self, target: str, text: str, enter: bool = True, literal: bool = True) -> TmuxCmdResult:
        if literal:
            result = self._run_tmux(["send-keys", "-t", target, "-l", text])
        else:
            result = self._run_tmux(["send-keys", "-t", target, text])
        if result.returncode != 0:
            return result
        if enter:
            return self._run_tmux(["send-keys", "-t", target, "Enter"])
        return result

    def capture_pane(self, target: str, start: Optional[str] = None, end: Optional[str] = None) -> TmuxCmdResult:
        args = ["capture-pane", "-t", target, "-p"]
        if start is not None:
            args.extend(["-S", str(start)])
        if end is not None:
            args.extend(["-E", str(end)])
        return self._run_tmux(args)

    def wait_for(self, signal: str, timeout: Optional[int] = None) -> TmuxCmdResult:
        return self._run_tmux(["wait-for", signal], timeout=timeout)

    def write_text(self, path: str, content: str) -> TmuxCmdResult:
        delimiter = f"TRAINSH_EOF_{uuid.uuid4().hex}"
        while delimiter in content:
            delimiter = f"TRAINSH_EOF_{uuid.uuid4().hex}"

        if path == "~":
            target = '"$HOME"'
        elif path.startswith("~/"):
            safe_tail = path[2:].replace('"', '\\"')
            target = f'"$HOME/{safe_tail}"'
        else:
            target = shlex.quote(path)

        cmd = (
            f"cat > {target} <<'{delimiter}'\n"
            f"{content}\n"
            f"{delimiter}\n"
        )
        return self._run_shell(cmd)
