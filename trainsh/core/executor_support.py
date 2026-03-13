"""Bridge, delegation, and interpolation helpers for the DSL executor."""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from typing import Any, Dict, List, Optional

from .executor_runtime import WindowInfo
from .executor_utils import _resolve_vast_host
from .models import Host
from .runtime_db import to_jsonable


class ExecutorSupportMixin:
    def _log_detail(self, event: str, message: str, data: Dict[str, object]) -> None:
        """Safe logger detail helper for composed helpers."""
        if self.logger:
            with self._thread_lock:
                self.logger.log_detail(event, message, data)

    def _build_bridge_attach_command(self, window: WindowInfo) -> str:
        """Build attach command for a bridge pane."""
        return self.bridge_exec.build_bridge_attach_command(window)

    def _ensure_bridge_window(self, window: WindowInfo) -> None:
        """Ensure bridge pane exists for window."""
        self.bridge_exec.ensure_bridge_window(window)

    def restore_tmux_bridge(self) -> None:
        """Rebuild bridge panes for restored windows on resume."""
        self.bridge_exec.restore_tmux_bridge(self.ctx.windows.values())

    def _wait_for_bridge_idle(self, window_name: str, pane_id: str, timeout: int) -> tuple[bool, str]:
        """Delegate bridge idle wait to helper."""
        return self.bridge_exec.wait_for_bridge_idle(window_name, pane_id, timeout)

    def _exec_via_bridge(
        self,
        window: WindowInfo,
        commands: str,
        timeout: int,
        background: bool,
        start_time: float,
    ) -> Optional[tuple[bool, str]]:
        """Delegate bridge command execution to helper."""
        return self.bridge_exec.exec_via_bridge(window, commands, timeout, background, start_time)

    def _cmd_tmux_open(self, args: List[str]) -> tuple[bool, str]:
        """Handle tmux.open via helper."""
        return self.tmux_control.cmd_tmux_open(args)

    def _cmd_tmux_close(self, args: List[str]) -> tuple[bool, str]:
        """Handle tmux.close via helper."""
        return self.tmux_control.cmd_tmux_close(args)

    def _cmd_tmux_config(self, args: List[str]) -> tuple[bool, str]:
        """Handle tmux.config via helper."""
        return self.tmux_control.cmd_tmux_config(args)

    def _cmd_notify(self, args: List[str]) -> tuple[bool, str]:
        """
        Handle notifications with simple syntax:
            notify "message"
            notify training complete
        """
        if not self.notify_enabled:
            return True, "Notification skipped (notifications.enabled=false)"

        message = self._interpolate(" ".join(args)).strip()
        if not message:
            return False, 'Usage: notify "message"'

        ok, summary = self.notifier.notify(
            title=self.notify_app_name,
            message=message,
            level="info",
            channels=self.notify_default_channels,
            webhook_url=self.notify_default_webhook,
            command=self.notify_default_command,
            timeout_secs=self.notify_default_timeout,
            fail_on_error=self.notify_default_fail_on_error,
        )
        return ok, summary

    def _cmd_vast_start(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.start via helper."""
        return self.vast_control.cmd_vast_start(args)

    def _cmd_vast_stop(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.stop via helper."""
        return self.vast_control.cmd_vast_stop(args)

    def _cmd_vast_pick(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.pick via helper."""
        return self.vast_control.cmd_vast_pick(args)

    def _cmd_vast_wait(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.wait via helper."""
        return self.vast_control.cmd_vast_wait(args)

    def _verify_ssh_connection(self, ssh_spec: str, timeout: int = 10) -> bool:
        """Verify SSH connectivity via helper."""
        return self.vast_control.verify_ssh_connection(ssh_spec, timeout=timeout)

    def _ensure_ssh_key_attached(self, client, ssh_key_path: str) -> None:
        """Ensure SSH key is attached via helper."""
        self.vast_control.ensure_ssh_key_attached(client, ssh_key_path)

    def _cmd_vast_cost(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.cost via helper."""
        return self.vast_control.cmd_vast_cost(args)

    def _cmd_sleep(self, args: List[str]) -> tuple[bool, str]:
        """Handle: sleep duration"""
        if not args:
            return False, "Usage: sleep 10s/5m/1h"

        # Interpolate the duration argument
        duration_str = self._interpolate(args[0])
        duration = self._parse_duration(duration_str)
        time.sleep(duration)
        return True, f"Slept for {duration}s"

    def _exec_execute(self, step: RecipeStepModel) -> tuple[bool, str]:
        """Execute command via helper."""
        return self.execute_helper.exec_execute(step)

    def _tmux_send_keys(self, host: str, session: str, text: str) -> None:
        """Send tmux keys via helper."""
        self.execute_helper.tmux_send_keys(host, session, text)

    def _tmux_wait_for_signal(self, host: str, signal: str, timeout: int = 1) -> bool:
        """Wait for tmux signal via helper."""
        return self.execute_helper.tmux_wait_for_signal(host, signal, timeout=timeout)

    def _exec_transfer(self, step: RecipeStepModel) -> tuple[bool, str]:
        """Execute transfer via helper."""
        return self.transfer_helper.exec_transfer(step)

    def _run_tmux_cmd(self, host: str, cmd: str, timeout: int = 10) -> subprocess.CompletedProcess:
        """Run tmux command via helper."""
        return self.wait_helper.run_tmux_cmd(host, cmd, timeout=timeout)

    def _get_pane_recent_output(self, host: str, session: str, lines: int = 5) -> str:
        """Get pane output via helper."""
        return self.wait_helper.get_pane_recent_output(host, session, lines=lines)

    def _is_pane_idle(self, host: str, session: str) -> bool:
        """Check pane idle via helper."""
        return self.wait_helper.is_pane_idle(host, session)

    def _get_pane_process_info(self, host: str, session: str) -> tuple[str, str]:
        """Get pane process info via helper."""
        return self.wait_helper.get_pane_process_info(host, session)

    def _wait_for_idle(self, window: 'WindowInfo', timeout: int) -> tuple[bool, str]:
        """Wait for idle via helper."""
        return self.wait_helper.wait_for_idle(window, timeout)

    def _exec_wait(self, step: RecipeStepModel) -> tuple[bool, str]:
        """Execute wait via helper."""
        return self.wait_helper.exec_wait(step)

    def _resolve_host(self, host_ref: str) -> str:
        """Resolve @host reference to actual host."""
        if host_ref.startswith('@'):
            name = host_ref[1:]
            host = self.recipe.hosts.get(name, name)
        else:
            host = host_ref

        if host.startswith("vast:"):
            return _resolve_vast_host(host[5:])
        return host

    def _resolve_window(self, name: str) -> Optional[WindowInfo]:
        """Resolve a window name to an existing tmux session or host fallback."""
        window = self.ctx.windows.get(name)
        if window:
            return window
        if not self.allow_host_execute:
            return None
        host = self._resolve_host(f"@{name}")
        return WindowInfo(name=name, host=host, remote_session=None)

    def _interpolate(self, text: str) -> str:
        """Interpolate variables and secrets.

        Runs multiple passes so chained references resolve correctly:
        e.g. var TOKEN = ${secret:GH}  →  var REPO = https://${TOKEN}@…
        """
        for _ in range(10):  # guard against infinite loops
            prev = text

            # Handle ${VAR} and ${secret:NAME}
            def replace_braced(match):
                ref = match.group(1)
                if ref.startswith('secret:'):
                    secret_name = ref[7:]
                    return self.secrets.get(secret_name) or ""
                return self.ctx.variables.get(ref, match.group(0))

            text = re.sub(r'\$\{([^}]+)\}', replace_braced, text)

            # Handle $VAR shorthand in control command arguments
            def replace_simple(match):
                name = match.group(1)
                return self.ctx.variables.get(name, match.group(0))

            text = re.sub(r'\$(\w+)', replace_simple, text)

            if text == prev:
                break  # nothing changed, fully resolved

        return text

    def _parse_endpoint(self, spec: str) -> 'TransferEndpoint':
        """Parse transfer endpoint via helper."""
        return self.transfer_helper.parse_endpoint(spec)

    def _build_transfer_hosts(self) -> Dict[str, Host]:
        """Build transfer hosts via helper."""
        return self.transfer_helper.build_transfer_hosts()

    def _build_transfer_storages(self) -> Dict[str, 'Storage']:
        """Build transfer storages via helper."""
        return self.transfer_helper.build_transfer_storages()

    def _storage_snapshot(self) -> Dict[str, Any]:
        """Build a JSON-safe storage snapshot for runtime persistence."""
        return {
            str(name): to_jsonable(spec)
            for name, spec in dict(self.recipe.storages or {}).items()
            if str(name).strip()
        }

    def _parse_duration(self, value: str) -> int:
        """Parse duration: 10s, 5m, 1h"""
        value = value.strip().lower()
        if value.endswith('h'):
            return int(value[:-1]) * 3600
        elif value.endswith('m'):
            return int(value[:-1]) * 60
        elif value.endswith('s'):
            return int(value[:-1])
        return int(value)
