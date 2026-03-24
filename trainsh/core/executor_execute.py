# tmux-trainsh execute helpers
# Encapsulates @session command execution.

import re
import os
import shlex
import subprocess
import time
from typing import Any, Callable, Optional


class ExecuteHelper:
    """Helper for execute steps."""

    def __init__(
        self,
        executor: Any,
        build_ssh_args: Callable[..., list[str]],
        window_cls: type[Any],
    ):
        self.executor = executor
        self.build_ssh_args = build_ssh_args
        self.window_cls = window_cls

    def _command_timeout(self, step: Any) -> Optional[int]:
        """Normalize execute-step timeout to subprocess/tmux semantics."""
        timeout = getattr(step, "timeout", 0)
        if timeout is None:
            return None
        try:
            timeout_secs = int(timeout)
        except Exception:
            return None
        return timeout_secs if timeout_secs > 0 else None

    def _read_captured_output(self, host: str, path: str) -> str:
        """Read one captured-output file from local or remote host."""
        target = str(path or "").strip()
        if not target:
            return ""
        if host == "local":
            try:
                with open(os.path.expanduser(target), "r", encoding="utf-8", errors="replace") as handle:
                    return handle.read()
            except OSError:
                return ""
        try:
            ssh_args = self.build_ssh_args(host, command=f"cat {shlex.quote(target)}", tty=False)
            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout or ""

    def _cleanup_captured_output(self, host: str, path: str) -> None:
        """Best-effort cleanup for one captured-output file."""
        target = str(path or "").strip()
        if not target:
            return
        if host == "local":
            try:
                os.remove(os.path.expanduser(target))
            except OSError:
                return
            return
        try:
            ssh_args = self.build_ssh_args(host, command=f"rm -f {shlex.quote(target)}", tty=False)
            subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return

    def _store_captured_output(self, step: Any, host: str) -> None:
        """Read captured output and persist it into runtime variables."""
        capture_var = str(getattr(step, "capture_var", "") or "").strip()
        capture_path = str(getattr(step, "capture_path", "") or "").strip()
        if not capture_var or not capture_path:
            return
        output = self._read_captured_output(host, capture_path)
        self.executor.ctx.variables[capture_var] = output.rstrip("\r\n")
        self._cleanup_captured_output(host, capture_path)

    def exec_execute(self, step: Any) -> tuple[bool, str]:
        """Execute command: @session > command."""
        window_name = step.host
        commands = self.executor._interpolate(step.commands)
        timeout = self._command_timeout(step)

        if self.executor.logger:
            self.executor.logger.log_detail("execute", f"Executing command on {window_name}", {
                "window_name": window_name,
                "commands": commands,
                "background": step.background,
            })

        window = self.executor._resolve_window(window_name)
        if not window:
            return False, f"Unknown window: {window_name}"

        bridge_result = self.executor._exec_via_bridge(
            window=window,
            commands=commands,
            timeout=timeout,
            background=step.background,
            start_time=time.time(),
        )
        if bridge_result is not None:
            return bridge_result

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
                self._store_captured_output(step, host)
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
            self._store_captured_output(step, host)
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
                    self._store_captured_output(step, "local")
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
                self._store_captured_output(step, host)
                return result.returncode == 0, result.stdout or result.stderr
            except subprocess.TimeoutExpired:
                return False, f"Command timed out after {timeout}s"

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
