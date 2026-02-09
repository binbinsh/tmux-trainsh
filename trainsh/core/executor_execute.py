# tmux-trainsh execute helpers
# Encapsulates @session command execution and sudo auth handling.

import getpass
import re
import subprocess
import time
from typing import Any, Callable, Optional


class ExecuteHelper:
    """Helper for execute steps and sudo auth."""

    def __init__(
        self,
        executor: Any,
        build_ssh_args: Callable[..., list[str]],
        window_cls: type[Any],
    ):
        self.executor = executor
        self.build_ssh_args = build_ssh_args
        self.window_cls = window_cls

    def exec_execute(self, step: Any) -> tuple[bool, str]:
        """Execute command: @session > command."""
        window_name = step.host
        commands = self.executor._interpolate(step.commands)

        if self.executor.logger:
            self.executor.logger.log_detail("execute", f"Executing command on {window_name}", {
                "window_name": window_name,
                "commands": commands,
                "background": step.background,
            })

        window = self.executor._resolve_window(window_name)
        if not window:
            return False, f"Unknown window: {window_name}"

        ok, msg = self.ensure_sudo_auth(window, commands)
        if not ok:
            return False, msg

        bridge_result = self.executor._exec_via_bridge(
            window=window,
            commands=commands,
            timeout=step.timeout or 600,
            background=step.background,
            start_time=time.time(),
        )
        if bridge_result is not None:
            return bridge_result

        timeout = step.timeout or 600
        start_time = time.time()
        host = window.host
        remote_session = window.remote_session

        if remote_session:
            tmux_client = self.executor.get_tmux_client(host)
            if step.background:
                result = tmux_client.send_keys(remote_session, commands, enter=True, literal=True)
                if self.executor.logger:
                    self.executor.logger.log_detail("send_keys", f"Sent to {window_name}", {
                        "commands": commands,
                        "remote_session": remote_session,
                        "background": True,
                        "success": result.returncode == 0,
                    })
                return result.returncode == 0, "Command sent (background)"

            if self.executor.is_resuming:
                result = tmux_client.send_keys(remote_session, commands, enter=True, literal=True)
                if result.returncode != 0:
                    return False, "Failed sending command to tmux session"
                time.sleep(0.5)
                window_info = self.window_cls(name=window_name, host=host, remote_session=remote_session)
                ok, msg = self.executor._wait_for_idle(window_info, timeout)
                elapsed = int(time.time() - start_time)
                if self.executor.logger:
                    self.executor.logger.log_detail("execute_complete", f"Command completed on {window_name}", {
                        "elapsed_sec": elapsed,
                        "remote_session": remote_session,
                    })
                return ok, msg

            import uuid
            signal = f"train_{uuid.uuid4().hex[:8]}"
            wrapped_cmd = f"( {commands} ); tmux wait-for -S {signal}"
            send_result = tmux_client.send_keys(remote_session, wrapped_cmd, enter=True, literal=True)
            if send_result.returncode != 0:
                return False, "Failed sending command to tmux session"

            wait_result = tmux_client.wait_for(signal, timeout=timeout)
            elapsed = int(time.time() - start_time)
            if self.executor.logger:
                self.executor.logger.log_detail("execute_complete", f"Command completed on {window_name}", {
                    "elapsed_sec": elapsed,
                    "remote_session": remote_session,
                    "wait_rc": wait_result.returncode,
                })
            if wait_result.returncode == 0:
                return True, f"Command completed ({elapsed}s)"
            return False, "Command failed or wait-for timed out"
        else:
            if host == "local":
                try:
                    result = subprocess.run(
                        commands,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    duration_ms = int((time.time() - start_time) * 1000)
                    if self.executor.logger:
                        self.executor.logger.log_ssh("local", commands, result.returncode, result.stdout, result.stderr, duration_ms)
                    return result.returncode == 0, result.stdout or result.stderr
                except subprocess.TimeoutExpired:
                    return False, f"Command timed out after {timeout}s"

            ssh_args = self.build_ssh_args(host, command=commands, tty=False)
            try:
                result = subprocess.run(
                    ssh_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                if self.executor.logger:
                    self.executor.logger.log_ssh(host, commands, result.returncode, result.stdout, result.stderr, duration_ms)
                return result.returncode == 0, result.stdout or result.stderr
            except subprocess.TimeoutExpired:
                return False, f"Command timed out after {timeout}s"

    def ensure_sudo_auth(self, window: Any, commands: str) -> tuple[bool, str]:
        """Ensure sudo auth is valid before running sudo commands."""
        if not re.search(r"\bsudo\b", commands):
            return True, ""

        if window.remote_session:
            bridge_pane = self.executor.tmux_bridge.get_pane(window.name)
            if bridge_pane:
                return self.ensure_sudo_auth_bridge(window, bridge_pane)
            return self.ensure_sudo_auth_tmux(window)

        host = window.host
        host_label = "local" if host == "local" else host

        now = time.time()
        last_prompt = self.executor._sudo_last_prompt.get(host_label, 0)
        prompt_log = now - last_prompt > 30

        if host == "local":
            check = subprocess.run(["sudo", "-n", "-v"], capture_output=True, text=True)
            if check.returncode == 0:
                return True, ""
            if prompt_log:
                self.executor.log("Sudo auth required for local commands. Please enter your password.")
                self.executor._sudo_last_prompt[host_label] = now
            try:
                auth = subprocess.run(["sudo", "-v"])
            except KeyboardInterrupt:
                return False, "Sudo authentication cancelled"
            if auth.returncode != 0:
                return False, "Sudo authentication failed"
            return True, ""

        if prompt_log:
            self.executor.log(f"Sudo auth required on {host_label}. Please enter your password.")
            self.executor._sudo_last_prompt[host_label] = now

        auth_args = self.build_ssh_args(host, command="sudo -v", tty=True)
        try:
            auth = subprocess.run(auth_args)
        except KeyboardInterrupt:
            return False, f"Sudo authentication cancelled for {host_label}"
        if auth.returncode != 0:
            return False, f"Sudo authentication failed for {host_label}"
        return True, ""

    def ensure_sudo_auth_tmux(self, window: Any) -> tuple[bool, str]:
        """Ensure sudo auth inside tmux session."""
        import uuid

        host = window.host
        session = window.remote_session
        host_label = "local" if host == "local" else host
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                if attempt == 0:
                    prompt_msg = f"Sudo password for {host_label}: "
                else:
                    prompt_msg = f"Sudo password for {host_label} (attempt {attempt + 1}/{max_attempts}): "
                password = getpass.getpass(prompt_msg)
            except (EOFError, KeyboardInterrupt):
                return False, f"Sudo authentication cancelled for {host_label}"
            if not password:
                return False, f"Sudo authentication cancelled for {host_label}"

            marker = f"__sudo_ok_{uuid.uuid4().hex[:8]}__"
            escaped_pw = password.replace("\\", "\\\\").replace("'", "'\"'\"'")
            sudo_cmd = f"printf '%s\\n' '{escaped_pw}' | sudo -S -v 2>/dev/null && echo {marker}"

            self.tmux_send_keys(host, session, sudo_cmd)
            time.sleep(1.5)
            output = self.executor._get_pane_recent_output(host, session, lines=5)

            if marker in output:
                self.executor._sudo_last_prompt[host_label] = time.time()
                return True, ""

        return False, f"Sudo authentication failed after {max_attempts} attempts for {host_label}"

    def ensure_sudo_auth_bridge(self, window: Any, pane_id: str) -> tuple[bool, str]:
        """Ensure sudo auth via bridge pane helper."""
        return self.executor.bridge_exec.ensure_sudo_auth_bridge(window, pane_id, self.executor._sudo_last_prompt)

    def tmux_send_keys(self, host: str, session: str, text: str) -> None:
        """Send literal text + Enter to tmux session locally or via SSH."""
        client = self.executor.get_tmux_client(host)
        client.send_keys(session, text, enter=True, literal=True)

    def tmux_wait_for_signal(self, host: str, signal: str, timeout: int = 1) -> bool:
        """Wait briefly for tmux signal."""
        try:
            result = self.executor.get_tmux_client(host).wait_for(signal, timeout=timeout)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
