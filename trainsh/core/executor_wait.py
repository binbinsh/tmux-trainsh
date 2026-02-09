# tmux-trainsh wait helpers
# Encapsulates wait-related tmux polling and condition checks.

import os
import subprocess
import time
from typing import Any, Callable


class WaitHelper:
    """Helper for wait and tmux idle detection logic."""

    def __init__(
        self,
        executor: Any,
        build_ssh_args: Callable[..., list[str]],
        host_from_ssh_spec: Callable[[str], Any],
        format_duration: Callable[[float], str],
    ):
        self.executor = executor
        self.build_ssh_args = build_ssh_args
        self.host_from_ssh_spec = host_from_ssh_spec
        self.format_duration = format_duration

    def _run_remote_shell(self, host: str, cmd: str, timeout: int = 10) -> Any:
        """Run a shell command via SSH on remote host."""
        ssh_args = self.build_ssh_args(host, command=cmd, tty=False)
        return subprocess.run(ssh_args, capture_output=True, text=True, timeout=timeout)

    def get_pane_recent_output(self, host: str, session: str, lines: int = 5) -> str:
        """Get recent output from a tmux pane."""
        result = self.executor.get_tmux_client(host).capture_pane(session, start=f"-{lines * 10}")
        if result.returncode == 0:
            output_lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
            return '\n'.join(output_lines[-lines:]) if output_lines else ""
        return ""

    def is_pane_idle(self, host: str, session: str) -> bool:
        """Check if tmux pane is idle using current command + child process count."""
        tmux_client = self.executor.get_tmux_client(host)
        result = tmux_client.display_message(session, "#{pane_current_command}")
        if result.returncode != 0:
            return False
        current_cmd = result.stdout.strip()
        if current_cmd not in {"bash", "zsh", "sh", "fish", "tcsh", "csh", "dash", "ksh"}:
            return False

        pane_pids = tmux_client.list_panes(session, "#{pane_pid}")
        pane_pid = pane_pids[0] if pane_pids else ""
        if not pane_pid:
            return False

        child_cmd = (
            f"(pgrep -P {pane_pid} 2>/dev/null || true) | wc -l"
        )
        if host == "local":
            result = subprocess.run(child_cmd, shell=True, capture_output=True, text=True, timeout=10)
        else:
            result = self._run_remote_shell(host, child_cmd, timeout=10)
        if result.returncode != 0:
            return False
        try:
            return int(result.stdout.strip()) == 0
        except ValueError:
            return False

    def get_pane_process_info(self, host: str, session: str) -> tuple[str, str]:
        """Get current command and process tree for a tmux pane."""
        tmux_client = self.executor.get_tmux_client(host)
        result = tmux_client.display_message(session, "#{pane_current_command}")
        current_cmd = result.stdout.strip() if result.returncode == 0 else "unknown"

        pane_pids = tmux_client.list_panes(session, "#{pane_pid}")
        pane_pid = pane_pids[0] if pane_pids else ""
        if not pane_pid:
            return current_cmd, ""

        if host == "local":
            ps_cmd = f"ps -o pid,stat,time,command -ax | awk '$1=={pane_pid}' | head -10"
            result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=10)
        else:
            ps_cmd = f"ps --forest -o pid,stat,time,cmd --ppid {pane_pid} 2>/dev/null | head -10"
            result = self._run_remote_shell(host, ps_cmd, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return current_cmd, result.stdout.strip()

        return current_cmd, ""

    def wait_for_idle(self, window: Any, timeout: int) -> tuple[bool, str]:
        """Wait for remote/local tmux pane to become idle."""
        host = window.host
        session = window.remote_session
        start = time.time()
        poll_interval = 30
        confirm_count = 3
        confirm_interval = min(10, max(1, timeout // (confirm_count + 2)))

        if timeout > 3600:
            self.executor.log(f"  Long wait ({self.format_duration(timeout)})")
            self.executor.log("  If you disconnect, run 'recipe resume' to continue later")

        # Give commands a brief head start before polling for idle.
        time.sleep(min(5, max(1, timeout // 6)))
        consecutive_idle = 0

        while time.time() - start < timeout:
            remaining = int(timeout - (time.time() - start))
            try:
                if self.is_pane_idle(host, session):
                    consecutive_idle += 1
                    if consecutive_idle >= confirm_count:
                        return True, "Pane is idle (confirmed)"
                    self.executor.log(f"  Idle detected, confirming... ({consecutive_idle}/{confirm_count})")
                    time.sleep(confirm_interval)
                    continue
                if consecutive_idle > 0:
                    self.executor.log("  Not idle, resetting confirmation counter")
                consecutive_idle = 0
            except Exception as e:
                self.executor.log(f"  Idle check failed: {e}")
                consecutive_idle = 0

            current_cmd, process_tree = self.get_pane_process_info(host, session)
            self.executor.log(f"  Waiting for @{window.name}... ({self.format_duration(remaining)} remaining)")
            self.executor.log(f"    Current command: {current_cmd}")
            if process_tree:
                self.executor.log("    Running processes:")
                for line in process_tree.split('\n')[:5]:
                    self.executor.log(f"      {line[:100]}")
            try:
                output = self.get_pane_recent_output(host, session, lines=2)
                if output:
                    self.executor.log("    Recent output:")
                    for line in output.split('\n'):
                        self.executor.log(f"      {line[:80]}")
            except Exception:
                pass
            time.sleep(poll_interval)

        return False, f"Timeout after {self.format_duration(timeout)}"

    def exec_wait(self, step: Any) -> tuple[bool, str]:
        """Execute wait condition with SSH retry logic."""
        target = step.target
        pattern = step.pattern
        condition = step.condition
        timeout = step.timeout or 300

        wait_config = {
            "target": target,
            "pattern": pattern,
            "condition": condition,
            "timeout": timeout,
        }
        if self.executor.logger:
            self.executor.logger.log_detail("wait_start", f"Starting wait for {target}", wait_config)

        window = self.executor._resolve_window(target)
        if not window:
            return False, f"Unknown window: {target}"

        start = time.time()
        poll_interval = 30
        ssh_failures = 0
        poll_count = 0

        if timeout > 3600:
            self.executor.log(f"  Long wait ({self.format_duration(timeout)})")
            self.executor.log("  If you disconnect, run 'recipe resume' to continue later")

        while time.time() - start < timeout:
            poll_count += 1
            elapsed = int(time.time() - start)
            remaining = timeout - elapsed

            if self.executor.logger:
                self.executor.logger.log_wait(target or "", condition or pattern or "", elapsed, remaining, f"poll #{poll_count}")

            if condition and condition.startswith("file:"):
                filepath = self.executor._interpolate(condition[5:])
                if window.host != "local":
                    try:
                        check_cmd = f"test -f {filepath} && echo exists"
                        ssh_args = self.build_ssh_args(window.host, command=check_cmd, tty=False)
                        ssh_start = time.time()
                        result = subprocess.run(
                            ssh_args,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        ssh_duration = int((time.time() - ssh_start) * 1000)

                        if self.executor.logger:
                            self.executor.logger.log_ssh(window.host, check_cmd, result.returncode, result.stdout, result.stderr, ssh_duration)

                        if "exists" in result.stdout:
                            if self.executor.logger:
                                self.executor.logger.log_detail("wait_file_found", f"File found: {filepath}", {"elapsed_sec": elapsed})
                            return True, f"File found: {filepath}"

                        ssh_failures = 0
                    except (subprocess.TimeoutExpired, OSError) as e:
                        ssh_failures += 1
                        self.executor.log(f"  SSH check failed ({ssh_failures}/{self.executor.ssh_max_retries}): {e}")
                        if self.executor.logger:
                            self.executor.logger.log_detail("wait_ssh_failure", "SSH check failed", {
                                "failure_count": ssh_failures,
                                "max_retries": self.executor.ssh_max_retries,
                                "error": str(e),
                            })
                        if ssh_failures >= self.executor.ssh_max_retries:
                            return False, f"Too many SSH failures: {e}"
                        backoff = min(
                            self.executor.ssh_retry_base_interval * (2 ** (ssh_failures - 1)),
                            self.executor.ssh_retry_max_interval
                        )
                        self.executor.log(f"  Retrying in {backoff}s...")
                        time.sleep(backoff)
                        continue
                else:
                    if os.path.exists(os.path.expanduser(filepath)):
                        if self.executor.logger:
                            self.executor.logger.log_detail("wait_file_found", f"Local file found: {filepath}", {"elapsed_sec": elapsed})
                        return True, f"File found: {filepath}"

            if condition and condition.startswith("port:"):
                port = int(condition[5:])
                host = "localhost"
                if window.host != "local":
                    host = self.host_from_ssh_spec(window.host).hostname
                try:
                    result = subprocess.run(
                        ["nc", "-z", host, str(port)],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        if self.executor.logger:
                            self.executor.logger.log_detail("wait_port_open", f"Port {port} is open on {host}", {"elapsed_sec": elapsed})
                        return True, f"Port {port} is open"
                except (subprocess.TimeoutExpired, OSError):
                    pass

            if condition == "idle":
                bridge_pane = self.executor.tmux_bridge.get_pane(window.name)
                # For local windows, check the actual target tmux session directly.
                # Local bridge panes now run nested tmux clients, which are not a
                # reliable signal for pane-idle detection.
                if bridge_pane and window.host != "local":
                    return self.executor._wait_for_bridge_idle(window.name, bridge_pane, remaining)
                if not window.remote_session:
                    return False, f"Window {target} has no tmux session"
                return self.wait_for_idle(window, remaining)

            remaining_str = self.format_duration(remaining)
            timeout_str = self.format_duration(timeout)
            self.executor.log(f"  Waiting... ({remaining_str} remaining of {timeout_str})")
            time.sleep(poll_interval)

        return False, f"Timeout after {self.format_duration(timeout)}"
