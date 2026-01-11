# kitten-trainsh tmux service
# Tmux session management for remote hosts

import subprocess
from typing import Optional, List
from dataclasses import dataclass

from .ssh import SSHClient, SSHResult


@dataclass
class TmuxSession:
    """Represents a tmux session."""
    name: str
    windows: int = 0
    created: Optional[str] = None
    attached: bool = False


class TmuxManager:
    """
    Tmux session manager for local or remote hosts.

    Supports creating, attaching, sending keys, and capturing output
    from tmux sessions.
    """

    def __init__(self, ssh_client: Optional[SSHClient] = None):
        """
        Initialize the tmux manager.

        Args:
            ssh_client: Optional SSH client for remote tmux operations.
                       If None, operates on local tmux.
        """
        self.ssh = ssh_client

    def _run(self, command: str) -> SSHResult:
        """Run a command locally or remotely."""
        if self.ssh:
            return self.ssh.run(command)
        else:
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                return SSHResult(
                    exit_code=result.returncode,
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                )
            except Exception as e:
                return SSHResult(exit_code=-1, stdout="", stderr=str(e))

    def list_sessions(self) -> List[TmuxSession]:
        """
        List all tmux sessions.

        Returns:
            List of TmuxSession objects
        """
        result = self._run("tmux list-sessions -F '#{session_name}:#{session_windows}:#{session_attached}' 2>/dev/null")

        if not result.success:
            return []

        sessions = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                sessions.append(TmuxSession(
                    name=parts[0],
                    windows=int(parts[1]) if parts[1].isdigit() else 0,
                    attached=parts[2] == "1",
                ))

        return sessions

    def session_exists(self, name: str) -> bool:
        """
        Check if a tmux session exists.

        Args:
            name: Session name

        Returns:
            True if session exists
        """
        result = self._run(f"tmux has-session -t {name} 2>/dev/null")
        return result.success

    def create_session(
        self,
        name: str,
        command: Optional[str] = None,
        workdir: Optional[str] = None,
        detached: bool = True,
    ) -> SSHResult:
        """
        Create a new tmux session.

        Args:
            name: Session name
            command: Optional command to run in the session
            workdir: Optional working directory
            detached: Create in detached mode

        Returns:
            SSHResult with exit code
        """
        cmd_parts = ["tmux", "new-session"]

        if detached:
            cmd_parts.append("-d")

        cmd_parts.extend(["-s", name])

        if workdir:
            cmd_parts.extend(["-c", workdir])

        if command:
            cmd_parts.append(command)

        return self._run(" ".join(cmd_parts))

    def kill_session(self, name: str) -> SSHResult:
        """
        Kill a tmux session.

        Args:
            name: Session name

        Returns:
            SSHResult with exit code
        """
        return self._run(f"tmux kill-session -t {name}")

    def send_keys(
        self,
        session: str,
        keys: str,
        enter: bool = True,
    ) -> SSHResult:
        """
        Send keys to a tmux session.

        Args:
            session: Session name
            keys: Keys to send
            enter: Whether to send Enter key after

        Returns:
            SSHResult with exit code
        """
        # Escape single quotes in keys
        escaped = keys.replace("'", "'\\''")
        cmd = f"tmux send-keys -t {session} '{escaped}'"

        if enter:
            cmd += " Enter"

        return self._run(cmd)

    def capture_pane(
        self,
        session: str,
        lines: Optional[int] = None,
        start_line: Optional[int] = None,
    ) -> str:
        """
        Capture the contents of a tmux pane.

        Args:
            session: Session name
            lines: Number of lines to capture (from end)
            start_line: Starting line number

        Returns:
            Captured text
        """
        cmd = f"tmux capture-pane -t {session} -p"

        if start_line is not None:
            cmd += f" -S {start_line}"

        if lines is not None:
            cmd += f" -E -{lines}"

        result = self._run(cmd)
        return result.stdout if result.success else ""

    def get_pane_pid(self, session: str) -> Optional[int]:
        """
        Get the PID of the process running in a tmux pane.

        Args:
            session: Session name

        Returns:
            PID or None
        """
        result = self._run(f"tmux list-panes -t {session} -F '#{{pane_pid}}'")
        if result.success and result.stdout.strip():
            try:
                return int(result.stdout.strip().split("\n")[0])
            except ValueError:
                pass
        return None

    def wait_for_output(
        self,
        session: str,
        pattern: str,
        timeout: int = 60,
        poll_interval: float = 1.0,
    ) -> bool:
        """
        Wait for a pattern to appear in tmux output.

        Args:
            session: Session name
            pattern: Pattern to wait for
            timeout: Timeout in seconds
            poll_interval: How often to check

        Returns:
            True if pattern found before timeout
        """
        import time
        import re

        start = time.time()
        while time.time() - start < timeout:
            output = self.capture_pane(session, lines=100)
            if re.search(pattern, output):
                return True
            time.sleep(poll_interval)

        return False

    def attach_command(self, session: str) -> str:
        """
        Get the command to attach to a session.

        Args:
            session: Session name

        Returns:
            Attach command string
        """
        if self.ssh:
            ssh_cmd = self.ssh.get_ssh_command()
            return f"{ssh_cmd} -t 'tmux attach -t {session}'"
        else:
            return f"tmux attach -t {session}"
