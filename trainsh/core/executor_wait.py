# tmux-trainsh wait helpers
# Encapsulates wait-related tmux polling and condition checks.

import os
import re
import subprocess
import time
from typing import Any, Callable, Optional


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

    def run_tmux_cmd(self, host: str, cmd: str, timeout: int = 10) -> Any:
        """Run a raw tmux command on the target host."""
        tmux_client = self.executor.get_tmux_client(host)
        return tmux_client.run_line(cmd, timeout=timeout)

    def _build_wait_ssh_args(self, host: str, command: str) -> list[str]:
        """Build SSH args for lightweight polling with fail-fast connection options."""
        ssh_args = self.build_ssh_args(host, command=command, tty=False)
        return [
            ssh_args[0],
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
            *ssh_args[1:],
        ]

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

    def wait_for_idle(self, window: Any, timeout: Optional[int]) -> tuple[bool, str]:
        """Wait for remote/local tmux pane to become idle."""
        host = window.host
        session = window.remote_session
        start = time.time()
        poll_interval = 30
        confirm_count = 3
        timeout_secs = None if timeout is None else max(0, int(timeout))
        confirm_interval = 10 if timeout_secs is None else min(10, max(1, timeout_secs // (confirm_count + 2)))

        if timeout_secs is not None and timeout_secs > 3600:
            self.executor.log(f"  Long wait ({self.format_duration(timeout_secs)})")
            self.executor.log("  If you disconnect, run 'train recipe resume <name>' to continue later")

        # Give commands a brief head start before polling for idle.
        head_start = 5 if timeout_secs is None else min(5, max(1, timeout_secs // 6))
        time.sleep(head_start)
        consecutive_idle = 0

        while True:
            elapsed = time.time() - start
            if timeout_secs is not None and elapsed >= timeout_secs:
                break
            remaining = None if timeout_secs is None else max(0, int(timeout_secs - elapsed))
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
            if remaining is None:
                self.executor.log(f"  Waiting for @{window.name}... (timeout disabled)")
            else:
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

        return False, f"Timeout after {self.format_duration(timeout_secs)}"

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
        poll_interval = 1 if pattern else 30
        ssh_failures = 0
        last_ssh_error = ""
        ssh_failure_notice_logged = False
        poll_count = 0

        if timeout > 3600:
            self.executor.log(f"  Long wait ({self.format_duration(timeout)})")
            self.executor.log("  If you disconnect, run 'train recipe resume <name>' to continue later")

        while time.time() - start < timeout:
            poll_count += 1
            elapsed = int(time.time() - start)
            remaining = timeout - elapsed

            if self.executor.logger:
                self.executor.logger.log_wait(target or "", condition or pattern or "", elapsed, remaining, f"poll #{poll_count}")

            if pattern:
                if not window.remote_session:
                    return False, f"Window {target} has no tmux session"
                try:
                    pane = self.executor.get_tmux_client(window.host).capture_pane(
                        window.remote_session,
                        start="-400",
                    )
                    output = pane.stdout or ""
                    if pane.returncode == 0 and re.search(pattern, output):
                        if self.executor.logger:
                            self.executor.logger.log_detail(
                                "wait_pattern_found",
                                f"Pattern matched in @{target}",
                                {"pattern": pattern, "elapsed_sec": elapsed},
                            )
                        return True, f"Pattern found: {pattern}"
                except re.error as exc:
                    return False, f"Invalid wait pattern: {exc}"

            if condition and condition.startswith("file:"):
                filepath = self.executor._interpolate(condition[5:])
                if window.host != "local":
                    try:
                        check_cmd = f"test -f {filepath} && echo exists"
                        ssh_args = self._build_wait_ssh_args(window.host, check_cmd)
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

                        if result.returncode == 255:
                            raise OSError(result.stderr.strip() or "ssh transport exited 255")

                        ssh_failures = 0
                        last_ssh_error = ""
                        ssh_failure_notice_logged = False
                    except (subprocess.TimeoutExpired, OSError) as e:
                        ssh_failures += 1
                        last_ssh_error = str(e)
                        self.executor.log(f"  SSH check failed (transient #{ssh_failures}): {e}")
                        if self.executor.logger:
                            self.executor.logger.log_detail("wait_ssh_failure", "SSH check failed", {
                                "failure_count": ssh_failures,
                                "max_retries": self.executor.ssh_max_retries,
                                "error": str(e),
                            })
                        if ssh_failures >= self.executor.ssh_max_retries and not ssh_failure_notice_logged:
                            ssh_failure_notice_logged = True
                            self.executor.log(
                                "  SSH polling is unstable; continuing until the overall wait timeout instead of failing early"
                            )
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

        timeout_msg = f"Timeout after {self.format_duration(timeout)}"
        if last_ssh_error:
            timeout_msg += f" (last SSH error: {last_ssh_error})"
        return False, timeout_msg
