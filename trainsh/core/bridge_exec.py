# tmux-trainsh bridge execution helpers
# Encapsulates local tmux bridge behavior to keep DSLExecutor focused on orchestration.

import re
import subprocess
import time
from typing import Any, Callable, Dict, Iterable, Optional


class BridgeExecutionHelper:
    """Bridge-pane attach, command execution, and idle wait."""

    def __init__(
        self,
        tmux_bridge: Any,
        prefer_bridge_exec: bool,
        bridge_remote_status: str,
        get_tmux_client: Callable[[str], Any],
        log: Callable[[str], None],
        log_detail: Callable[[str, str, Dict[str, Any]], None],
        format_duration: Callable[[float], str],
    ):
        self.tmux_bridge = tmux_bridge
        self.prefer_bridge_exec = prefer_bridge_exec
        self.bridge_remote_status = bridge_remote_status
        self.get_tmux_client = get_tmux_client
        self.log = log
        self.log_detail = log_detail
        self.format_duration = format_duration

    def build_bridge_attach_command(self, window: Any) -> str:
        """Build local shell command used by bridge pane to attach a window."""
        if not window.remote_session:
            return "bash -l"

        session = window.remote_session
        if window.host == "local":
            # Force a nested local tmux client inside the split pane so the bridge
            # always displays and executes within the recipe session itself.
            return self.tmux_bridge.tmux.build_attach_command(session, nested=True)

        remote_client = self.get_tmux_client(window.host)
        return remote_client.build_attach_command(session, status_mode=self.bridge_remote_status)

    def ensure_bridge_window(self, window: Any) -> None:
        """Ensure bridge pane exists for a window (best effort)."""
        if not window.remote_session:
            return

        attach_cmd = self.build_bridge_attach_command(window)
        ok, msg = self.tmux_bridge.connect(window.name, attach_cmd)
        if ok:
            self.log(f"  Bridge @{window.name}: {msg}")
            return
        self.log_detail(
            "tmux_bridge_skip",
            f"Bridge skipped for {window.name}: {msg}",
            {"window": window.name, "host": window.host},
        )

    def restore_tmux_bridge(self, windows: Iterable[Any]) -> None:
        """Rebuild bridge panes for restored windows."""
        for window in windows:
            self.ensure_bridge_window(window)

    def _tmux_send_keys_local_target(self, target: str, text: str) -> None:
        """Send literal text + Enter to local tmux target."""
        self.tmux_bridge.tmux.send_keys(target, text, enter=True, literal=True)

    def _get_bridge_pane_recent_output(self, pane_id: str, lines: int = 5) -> str:
        """Capture recent output from local bridge pane."""
        result = self.tmux_bridge.tmux.capture_pane(pane_id, start=f"-{lines * 20}")
        if result.returncode != 0:
            return ""
        output_lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
        return "\n".join(output_lines[-lines:]) if output_lines else ""

    def _get_local_pane_pid(self, pane_id: str) -> str:
        """Get pane PID from local tmux."""
        result = self.tmux_bridge.tmux.display_message(pane_id, "#{pane_pid}")
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _is_bridge_pane_idle(self, pane_id: str) -> bool:
        """Check if bridge pane shell is idle and has no child processes."""
        current = self.tmux_bridge.tmux.display_message(pane_id, "#{pane_current_command}")
        if current.returncode != 0:
            return False
        current_cmd = current.stdout.strip()
        if current_cmd not in {"bash", "zsh", "sh", "fish", "tcsh", "csh", "dash", "ksh"}:
            return False

        pane_pid = self._get_local_pane_pid(pane_id)
        if not pane_pid:
            return False

        child = subprocess.run(
            f"(pgrep -P {pane_pid} 2>/dev/null || true) | wc -l",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if child.returncode != 0:
            return False
        try:
            return int(child.stdout.strip()) == 0
        except ValueError:
            return False

    def _get_bridge_pane_process_info(self, pane_id: str) -> tuple[str, str]:
        """Get current command and process tree for bridge pane."""
        current = self.tmux_bridge.tmux.display_message(pane_id, "#{pane_current_command}")
        current_cmd = current.stdout.strip() if current.returncode == 0 else "unknown"

        pane_pid = self._get_local_pane_pid(pane_id)
        if not pane_pid:
            return current_cmd, ""

        ps_tree = subprocess.run(
            f"ps -o pid,ppid,stat,time,command -ax | awk '$2=={pane_pid}' | head -10",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if ps_tree.returncode == 0 and ps_tree.stdout.strip():
            return current_cmd, ps_tree.stdout.strip()
        return current_cmd, ""

    def wait_for_bridge_idle(self, window_name: str, pane_id: str, timeout: int) -> tuple[bool, str]:
        """Wait for bridge pane to become idle with confirmation checks."""
        start = time.time()
        poll_interval = 30
        confirm_count = 3
        confirm_interval = min(10, max(1, timeout // (confirm_count + 2)))
        consecutive_idle = 0

        if timeout > 3600:
            self.log(f"  Long wait ({self.format_duration(timeout)})")
            self.log("  If you disconnect, run 'recipe resume' to continue later")

        time.sleep(5)

        while time.time() - start < timeout:
            remaining = int(timeout - (time.time() - start))

            try:
                if self._is_bridge_pane_idle(pane_id):
                    consecutive_idle += 1
                    if consecutive_idle >= confirm_count:
                        return True, "Pane is idle (confirmed)"
                    self.log(f"  Idle detected, confirming... ({consecutive_idle}/{confirm_count})")
                    time.sleep(confirm_interval)
                    continue
                if consecutive_idle > 0:
                    self.log("  Not idle, resetting confirmation counter")
                consecutive_idle = 0
            except Exception as e:
                self.log(f"  Idle check failed: {e}")
                consecutive_idle = 0

            current_cmd, process_tree = self._get_bridge_pane_process_info(pane_id)
            self.log(f"  Waiting for @{window_name}... ({self.format_duration(remaining)} remaining)")
            self.log(f"    Current command: {current_cmd}")
            if process_tree:
                self.log("    Running processes:")
                for line in process_tree.split("\n")[:5]:
                    self.log(f"      {line[:100]}")

            output = self._get_bridge_pane_recent_output(pane_id, lines=2)
            if output:
                self.log("    Recent output:")
                for line in output.split("\n"):
                    self.log(f"      {line[:80]}")

            time.sleep(poll_interval)

        return False, f"Timeout after {self.format_duration(timeout)}"

    def _wait_bridge_marker(self, pane_id: str, marker: str, timeout: int) -> tuple[bool, Optional[int]]:
        """Wait until marker+exitcode appears in bridge pane output."""
        start = time.time()
        pattern = re.compile(re.escape(marker) + r"(-?\d+)")
        while time.time() - start < timeout:
            result = self.tmux_bridge.tmux.capture_pane(pane_id, start="-300")
            if result.returncode == 0:
                matches = pattern.findall(result.stdout or "")
                if matches:
                    try:
                        return True, int(matches[-1])
                    except ValueError:
                        return True, None
            time.sleep(1)
        return False, None

    def exec_via_bridge(
        self,
        window: Any,
        commands: str,
        timeout: int,
        background: bool,
        start_time: float,
    ) -> Optional[tuple[bool, str]]:
        """Execute command through local bridge pane when available."""
        if not self.prefer_bridge_exec or not window.remote_session:
            return None

        pane_id = self.tmux_bridge.get_pane(window.name)
        if not pane_id:
            return None

        try:
            if background:
                self._tmux_send_keys_local_target(pane_id, commands)
                return True, "Command sent (background via bridge)"

            import uuid
            marker = f"__train_done_{uuid.uuid4().hex[:8]}__"
            wrapped_cmd = f"( {commands} ); __train_rc=$?; echo {marker}$__train_rc"
            self._tmux_send_keys_local_target(pane_id, wrapped_cmd)

            found, exit_code = self._wait_bridge_marker(pane_id, marker, timeout)
            elapsed = int(time.time() - start_time)

            self.log_detail("bridge_exec", f"Bridge execute on {window.name}", {
                "window_name": window.name,
                "bridge_pane": pane_id,
                "elapsed_sec": elapsed,
                "found_marker": found,
                "exit_code": exit_code,
            })

            if not found:
                return False, f"Command timed out after {timeout}s"
            if exit_code == 0:
                return True, f"Command completed ({elapsed}s)"
            return False, f"Command failed with exit code {exit_code}"

        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {timeout}s"
        except Exception as e:
            self.log_detail("bridge_exec_error", f"Bridge execute failed: {e}", {
                "window_name": window.name,
            })
            return None

