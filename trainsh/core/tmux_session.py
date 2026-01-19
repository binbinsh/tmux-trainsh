# tmux-trainsh tmux session management
# Simplified tmux wrapper leveraging native tmux features

import subprocess
import shlex
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable
from pathlib import Path


@dataclass
class PaneInfo:
    """Information about a tmux pane."""
    pane_id: str
    window_id: str
    window_name: str
    pane_index: int
    active: bool = False
    dead: bool = False
    pid: Optional[int] = None
    current_command: str = ""


class TmuxSession:
    """
    High-level tmux session manager.

    Uses tmux native features for:
    - Session/window/pane lifecycle management
    - Command execution with wait-for synchronization
    - Output capture and monitoring
    - Proper cleanup

    Example usage:
        session = TmuxSession("train-job123")

        # Create a pane with SSH connection
        pane_id = session.create_pane("gpu", ssh_host="root@vastai:22022")

        # Run command and wait for completion
        session.run_command(pane_id, "pip install torch")

        # Run command in background
        session.send_keys(pane_id, "python train.py &")

        # Wait for pattern in output
        session.wait_for_pattern(pane_id, "Training complete")

        # Capture output
        output = session.capture(pane_id)

        # Cleanup
        session.rm()
    """

    def __init__(self, name: str, create: bool = True):
        """
        Initialize tmux session.

        Args:
            name: Session name
            create: Create session if it doesn't exist
        """
        self.name = name
        self.panes: Dict[str, str] = {}  # name -> pane_id

        if create:
            self._ensure_session()

    def _run(self, *args, timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess:
        """Run tmux command."""
        cmd = ["tmux"] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"tmux command failed: {' '.join(cmd)}\n{result.stderr}")
        return result

    def _ensure_session(self) -> None:
        """Create session if it doesn't exist."""
        result = self._run("has-session", "-t", self.name)
        if result.returncode != 0:
            self._run("new-session", "-d", "-s", self.name, check=True)
            # Set larger scrollback buffer (default is 2000)
            self._run("set-option", "-t", self.name, "history-limit", "50000")

    @property
    def exists(self) -> bool:
        """Check if session exists."""
        return self._run("has-session", "-t", self.name).returncode == 0

    def rm(self) -> bool:
        """Remove the entire session."""
        result = self._run("kill-session", "-t", self.name)
        self.panes.clear()
        return result.returncode == 0

    # ==================== Pane Management ====================

    def create_pane(
        self,
        name: str,
        ssh_host: Optional[str] = None,
        command: Optional[str] = None,
        split: Optional[str] = None,  # "h" for horizontal, "v" for vertical
        target: Optional[str] = None,  # pane to split from
    ) -> str:
        """
        Create a new pane.

        Args:
            name: Logical name for this pane
            ssh_host: SSH host to connect to (e.g., "root@host -p 22")
            command: Command to run in the pane
            split: Split direction ("h" or "v"), None for new window
            target: Pane to split from (for split mode)

        Returns:
            Pane ID (e.g., %0)
        """
        # Build the command to run in the pane
        if ssh_host:
            # SSH connection with proper terminal setup
            ssh_parts = shlex.split(ssh_host) if isinstance(ssh_host, str) else ssh_host
            ssh_cmd = ["ssh", "-tt", "-o", "StrictHostKeyChecking=accept-new"]

            # Parse host and options
            host = None
            i = 0
            while i < len(ssh_parts):
                part = ssh_parts[i]
                if part.startswith("-"):
                    ssh_cmd.append(part)
                    if part in ("-p", "-i", "-J", "-o", "-F") and i + 1 < len(ssh_parts):
                        ssh_cmd.append(ssh_parts[i + 1])
                        i += 1
                elif host is None:
                    host = part
                i += 1

            if host:
                ssh_cmd.append(host)
            ssh_cmd.append("TERM=xterm-256color exec bash -l")
            pane_cmd = " ".join(shlex.quote(arg) for arg in ssh_cmd)
        elif command:
            pane_cmd = command
        else:
            pane_cmd = "bash -l"

        # Create pane
        if split:
            # Split existing pane
            split_target = self.panes.get(target, target) if target else self.name
            split_flag = "-h" if split == "h" else "-v"
            result = self._run(
                "split-window", split_flag,
                "-t", split_target,
                "-P", "-F", "#{pane_id}",
                pane_cmd,
                check=True,
            )
        else:
            # New window
            result = self._run(
                "new-window",
                "-t", self.name,
                "-n", name,
                "-P", "-F", "#{pane_id}",
                pane_cmd,
                check=True,
            )

        pane_id = result.stdout.strip()
        self.panes[name] = pane_id

        # Wait for pane to be ready
        time.sleep(0.3)

        return pane_id

    def get_pane(self, name: str) -> Optional[str]:
        """Get pane ID by name."""
        return self.panes.get(name)

    def kill_pane(self, name: str) -> bool:
        """Kill a pane by name."""
        pane_id = self.panes.pop(name, None)
        if pane_id:
            return self._run("kill-pane", "-t", pane_id).returncode == 0
        return False

    def list_panes(self) -> List[PaneInfo]:
        """List all panes in the session."""
        fmt = "#{pane_id}:#{window_id}:#{window_name}:#{pane_index}:#{pane_active}:#{pane_dead}:#{pane_pid}:#{pane_current_command}"
        result = self._run("list-panes", "-s", "-t", self.name, "-F", fmt)

        if result.returncode != 0:
            return []

        panes = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 8:
                panes.append(PaneInfo(
                    pane_id=parts[0],
                    window_id=parts[1],
                    window_name=parts[2],
                    pane_index=int(parts[3]) if parts[3].isdigit() else 0,
                    active=parts[4] == "1",
                    dead=parts[5] == "1",
                    pid=int(parts[6]) if parts[6].isdigit() else None,
                    current_command=parts[7],
                ))
        return panes

    # ==================== Command Execution ====================

    def send_keys(self, target: str, keys: str, enter: bool = True) -> bool:
        """
        Send keys to a pane.

        Args:
            target: Pane name or ID
            keys: Text/keys to send
            enter: Send Enter key after text
        """
        pane_id = self.panes.get(target, target)

        # Use -l for literal interpretation (no key lookup)
        args = ["send-keys", "-t", pane_id, "-l", keys]
        result = self._run(*args)

        if enter and result.returncode == 0:
            self._run("send-keys", "-t", pane_id, "Enter")

        return result.returncode == 0

    def run_command(
        self,
        target: str,
        command: str,
        timeout: int = 600,
        signal: Optional[str] = None,
    ) -> bool:
        """
        Run command and wait for completion using tmux wait-for.

        Args:
            target: Pane name or ID
            command: Command to run
            timeout: Timeout in seconds
            signal: Optional signal name (auto-generated if None)

        Returns:
            True if command completed successfully
        """
        import uuid
        pane_id = self.panes.get(target, target)
        signal = signal or f"train_{uuid.uuid4().hex[:8]}"

        # Wrap command: run command, then signal completion
        # Using ( ) to group command preserves exit code
        wrapped = f"( {command} ); tmux wait-for -S {signal}"

        # Send the wrapped command
        self.send_keys(pane_id, wrapped)

        # Wait for the signal
        result = self._run("wait-for", signal, timeout=timeout)
        return result.returncode == 0

    def run_background(self, target: str, command: str) -> bool:
        """Run command in background (don't wait for completion)."""
        return self.send_keys(target, command)

    # ==================== Output Capture ====================

    def capture(
        self,
        target: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> str:
        """
        Capture pane output.

        Args:
            target: Pane name or ID
            start: Start line (negative for history, e.g., -100)
            end: End line

        Returns:
            Captured text
        """
        pane_id = self.panes.get(target, target)

        args = ["capture-pane", "-t", pane_id, "-p"]
        if start is not None:
            args.extend(["-S", str(start)])
        if end is not None:
            args.extend(["-E", str(end)])

        result = self._run(*args)
        return result.stdout if result.returncode == 0 else ""

    def wait_for_pattern(
        self,
        target: str,
        pattern: str,
        timeout: int = 300,
        poll_interval: float = 1.0,
    ) -> bool:
        """
        Wait for a pattern to appear in pane output.

        Args:
            target: Pane name or ID
            pattern: Regex pattern to match
            timeout: Timeout in seconds
            poll_interval: How often to check

        Returns:
            True if pattern found
        """
        import re

        start_time = time.time()
        while time.time() - start_time < timeout:
            output = self.capture(target, start=-100)
            if re.search(pattern, output):
                return True
            time.sleep(poll_interval)

        return False

    # ==================== Utilities ====================

    def attach_command(self) -> str:
        """Get the command to attach to this session."""
        return f"tmux attach -t {self.name}"

    def select_pane(self, target: str) -> bool:
        """Select/focus a pane."""
        pane_id = self.panes.get(target, target)
        return self._run("select-pane", "-t", pane_id).returncode == 0


# ==================== Convenience Functions ====================

def session_exists(name: str) -> bool:
    """Check if a tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
    )
    return result.returncode == 0


def list_sessions() -> List[str]:
    """List all tmux sessions."""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]


def kill_session(name: str) -> bool:
    """Kill a tmux session."""
    result = subprocess.run(
        ["tmux", "kill-session", "-t", name],
        capture_output=True,
    )
    return result.returncode == 0
