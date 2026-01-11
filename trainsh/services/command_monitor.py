# kitten-trainsh command monitor service
# Command execution with live output streaming

import time
import uuid
from dataclasses import dataclass
from typing import Optional, Callable, List
from datetime import datetime

from .ssh import SSHClient, SSHResult
from .tmux import TmuxManager
from ..core.session_registry import RecipeSession, SessionRegistry, get_current_kitty_window_id


@dataclass
class CommandResult:
    """Result of a monitored command execution."""
    exit_code: int
    output: str
    session_id: Optional[str] = None
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class CommandMonitor:
    """
    Command execution with live output monitoring.

    Supports:
    - Running commands in tmux for durability
    - Streaming output via callbacks
    - Session registration for terminal<->recipe mapping
    """

    def __init__(
        self,
        ssh: Optional[SSHClient] = None,
        tmux: Optional[TmuxManager] = None,
        registry: Optional[SessionRegistry] = None,
    ):
        """
        Initialize the command monitor.

        Args:
            ssh: SSH client for remote execution (None for local)
            tmux: TmuxManager instance (created if None)
            registry: SessionRegistry for tracking (created if None)
        """
        self.ssh = ssh
        self.tmux = tmux or TmuxManager(ssh)
        self.registry = registry or SessionRegistry()

    def run_with_monitoring(
        self,
        command: str,
        recipe_name: Optional[str] = None,
        use_tmux: bool = True,
        output_callback: Optional[Callable[[str], None]] = None,
        poll_interval: float = 0.5,
        timeout: Optional[int] = None,
    ) -> CommandResult:
        """
        Run a command with live output monitoring.

        Args:
            command: Command to execute
            recipe_name: Optional recipe name for session registration
            use_tmux: Whether to use tmux for durability
            output_callback: Callback for each new line of output
            poll_interval: How often to poll for new output (seconds)
            timeout: Maximum execution time in seconds

        Returns:
            CommandResult with exit code and output
        """
        start_time = time.time()
        session_id = uuid.uuid4().hex[:12]
        tmux_session_name = f"trainsh-{session_id}"

        if use_tmux:
            # Create tmux session with the command
            result = self.tmux.create_session(tmux_session_name, command)
            if not result.success:
                return CommandResult(
                    exit_code=-1,
                    output=f"Failed to create tmux session: {result.stderr}",
                )

            # Register session for terminal<->recipe mapping
            if recipe_name:
                session = RecipeSession(
                    session_id=session_id,
                    recipe_name=recipe_name,
                    recipe_path=None,
                    host_id=self.ssh.hostname if self.ssh else "local",
                    tmux_session=tmux_session_name,
                    kitty_window_id=get_current_kitty_window_id(),
                    started_at=datetime.now().isoformat(),
                    status="running",
                )
                self.registry.register(session)

            # Stream output from tmux
            output = self._stream_tmux_output(
                tmux_session_name,
                output_callback,
                poll_interval,
                timeout,
                start_time,
            )

            # Get exit code from tmux
            exit_code = self._get_tmux_exit_code(tmux_session_name)

            # Update session status
            if recipe_name:
                status = "completed" if exit_code == 0 else "failed"
                self.registry.update_status(session_id, status)

            duration = time.time() - start_time

            return CommandResult(
                exit_code=exit_code,
                output=output,
                session_id=session_id,
                duration_seconds=duration,
            )
        else:
            # Direct execution without tmux
            if self.ssh:
                result = self.ssh.run(command, timeout=timeout)
                if output_callback and result.stdout:
                    for line in result.stdout.split("\n"):
                        output_callback(line)
                return CommandResult(
                    exit_code=result.exit_code,
                    output=result.stdout,
                    duration_seconds=time.time() - start_time,
                )
            else:
                import subprocess
                try:
                    proc = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    if output_callback and proc.stdout:
                        for line in proc.stdout.split("\n"):
                            output_callback(line)
                    return CommandResult(
                        exit_code=proc.returncode,
                        output=proc.stdout,
                        duration_seconds=time.time() - start_time,
                    )
                except subprocess.TimeoutExpired:
                    return CommandResult(
                        exit_code=-1,
                        output="Command timed out",
                        duration_seconds=time.time() - start_time,
                    )

    def _stream_tmux_output(
        self,
        session_name: str,
        callback: Optional[Callable[[str], None]],
        poll_interval: float,
        timeout: Optional[int],
        start_time: float,
    ) -> str:
        """Stream output from a tmux session until it exits."""
        all_output: List[str] = []
        last_line_count = 0

        while True:
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                break

            # Capture current pane content
            output = self.tmux.capture_pane(session_name, lines=1000)
            lines = output.split("\n")

            # Send new lines to callback
            if len(lines) > last_line_count:
                new_lines = lines[last_line_count:]
                for line in new_lines:
                    if callback:
                        callback(line)
                    all_output.append(line)
                last_line_count = len(lines)

            # Check if session still exists
            if not self.tmux.session_exists(session_name):
                # Capture final output
                final_output = self.tmux.capture_pane(session_name, lines=1000)
                final_lines = final_output.split("\n")
                if len(final_lines) > last_line_count:
                    for line in final_lines[last_line_count:]:
                        if callback:
                            callback(line)
                        all_output.append(line)
                break

            time.sleep(poll_interval)

        return "\n".join(all_output)

    def _get_tmux_exit_code(self, session_name: str) -> int:
        """Get the exit code of the command that ran in a tmux session."""
        # This is tricky - tmux doesn't directly expose the exit code
        # We can try to capture it from the pane if available
        # For now, return 0 if session exited normally
        if not self.tmux.session_exists(session_name):
            return 0
        return -1

    def attach_to_session(self, session_id: str) -> Optional[str]:
        """
        Get the command to attach to a session.

        Args:
            session_id: Session ID

        Returns:
            Attach command string or None if session not found
        """
        session = self.registry.get(session_id)
        if not session:
            return None

        return self.tmux.attach_command(session.tmux_session)

    def list_running_sessions(self) -> List[RecipeSession]:
        """
        List all running sessions.

        Returns:
            List of running RecipeSession objects
        """
        return self.registry.list_running()

    def kill_session(self, session_id: str) -> bool:
        """
        Kill a running session.

        Args:
            session_id: Session ID to kill

        Returns:
            True if killed successfully
        """
        session = self.registry.get(session_id)
        if not session:
            return False

        result = self.tmux.kill_session(session.tmux_session)
        if result.success:
            self.registry.update_status(session_id, "cancelled")
            return True
        return False
