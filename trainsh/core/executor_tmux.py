# tmux-trainsh tmux control helpers
# Keeps tmux.open/tmux.close/tmux.config logic out of DSLExecutor.

import os
from pathlib import Path
from typing import Any, List, Type

from ..config import get_default_config, load_config


class TmuxControlHelper:
    """Helper for tmux control steps."""

    def __init__(
        self,
        executor: Any,
        window_cls: Type[Any],
    ):
        self.executor = executor
        self.window_cls = window_cls

    def cmd_tmux_open(self, args: List[str]) -> tuple[bool, str]:
        """Handle: tmux.open @host as name"""
        if len(args) < 3 or args[1] != "as":
            return False, "Usage: tmux.open @host as name"

        host_ref = args[0]
        window_name = args[2]

        host = self.executor._resolve_host(host_ref)
        remote_session_name = self.executor.allocate_window_session_name()

        if self.executor.logger:
            self.executor.logger.log_detail("tmux_open", f"Creating remote tmux session {window_name}", {
                "host_ref": host_ref,
                "resolved_host": host,
                "window_name": window_name,
                "remote_session": remote_session_name,
            })

        window_info = self.window_cls(
            name=window_name,
            host=host,
            remote_session=remote_session_name,
        )

        if host == "local":
            try:
                if not self.executor.local_tmux.has_session(remote_session_name):
                    result = self.executor.local_tmux.new_session(
                        remote_session_name,
                        detached=True,
                    )
                    if result.returncode != 0:
                        return False, f"Failed to create local tmux session: {result.stderr}"
                self.executor.ctx.windows[window_name] = window_info
                self.executor.log(f"  Local tmux session: {remote_session_name}")
                self.executor.log(f"  Attach with: tmux attach -t {remote_session_name}")
                self.executor._ensure_bridge_window(window_info)
                return True, f"Created local tmux session: {remote_session_name}"
            except Exception as e:
                return False, str(e)

        remote_tmux = self.executor.get_tmux_client(host)
        try:
            if not remote_tmux.has_session(remote_session_name):
                result = remote_tmux.new_session(remote_session_name, detached=True)
                if result.returncode != 0:
                    return False, f"Failed to create remote tmux session: {result.stderr}"

            self.executor.ctx.windows[window_name] = window_info
            attach_cmd = remote_tmux.build_attach_command(remote_session_name, status_mode="keep")
            self.executor.log(f"  Remote tmux session: {remote_session_name}")
            self.executor.log(f"  Attach with: {attach_cmd}")
            self.executor._ensure_bridge_window(window_info)

            if self.executor.logger:
                self.executor.logger.log_detail("window_registered", f"Window {window_name} registered", {
                    "window_name": window_name,
                    "host": host,
                    "remote_session": remote_session_name,
                })

            return True, f"Created remote tmux session: {remote_session_name}"

        except Exception as e:
            if self.executor.logger:
                self.executor.logger.log_detail("tmux_error", f"Failed to create session: {e}", {})
            return False, str(e)

    def cmd_tmux_close(self, args: List[str]) -> tuple[bool, str]:
        """Handle: tmux.close @session"""
        if not args:
            return False, "Usage: tmux.close @session"

        window_name = args[0]
        if not window_name.startswith("@"):
            return False, "Usage: tmux.close @session"
        window_name = window_name[1:]
        window = self.executor.ctx.windows.get(window_name)
        if not window:
            return False, f"Unknown window: {window_name}"

        if not window.remote_session:
            self.executor.tmux_bridge.disconnect(window_name)
            self.executor.ctx.windows.pop(window_name, None)
            return True, f"Unregistered window: {window_name}"

        if window.host == "local":
            try:
                self.executor.local_tmux.kill_session(window.remote_session)
                self.executor.tmux_bridge.disconnect(window_name)
                self.executor.ctx.windows.pop(window_name, None)
                return True, f"Killed local tmux session: {window.remote_session}"
            except Exception as e:
                return False, str(e)

        try:
            self.executor.get_tmux_client(window.host).kill_session(window.remote_session)
            if self.executor.logger:
                self.executor.logger.log_detail("tmux_close", f"Killed remote session {window.remote_session}", {
                    "window_name": window_name,
                    "remote_session": window.remote_session,
                })
            self.executor.tmux_bridge.disconnect(window_name)
            self.executor.ctx.windows.pop(window_name, None)
            return True, f"Killed remote session: {window.remote_session}"
        except Exception as e:
            return False, str(e)

    def cmd_tmux_config(self, args: List[str]) -> tuple[bool, str]:
        """Handle: tmux.config @host"""
        if not args:
            return False, "Usage: tmux.config @host"

        host_ref = args[0]
        host = self.executor._resolve_host(host_ref)

        config = load_config()
        tmux_config = config.get("tmux", {})
        tmux_options = tmux_config.get("options", [])
        if not tmux_options:
            tmux_options = get_default_config().get("tmux", {}).get("options", [])

        lines = [
            "# Generated by tmux-trainsh",
            "# Applied via: tmux.config @host",
            "",
        ]
        lines.extend(tmux_options)
        tmux_conf_content = "\n".join(lines)

        if self.executor.logger:
            self.executor.logger.log_detail("tmux_config", f"Applying tmux config to {host}", {
                "host_ref": host_ref,
                "resolved_host": host,
                "options_count": len(tmux_options),
            })

        if host == "local":
            tmux_conf_path = Path(os.path.expanduser("~/.tmux.conf"))
            tmux_conf_path.write_text(tmux_conf_content)
            try:
                self.executor.local_tmux.run("source-file", str(tmux_conf_path), timeout=10)
            except Exception:
                pass
            return True, "Applied tmux config to local ~/.tmux.conf"

        try:
            remote_tmux = self.executor.get_tmux_client(host)
            write_result = remote_tmux.write_text("~/.tmux.conf", tmux_conf_content)
            if write_result.returncode != 0:
                return False, f"Failed to write ~/.tmux.conf: {write_result.stderr}"

            source_result = remote_tmux.run("source-file", "~/.tmux.conf", timeout=30)
            if source_result.returncode != 0:
                if remote_tmux.list_sessions("#{session_name}"):
                    return False, f"Failed to source ~/.tmux.conf: {source_result.stderr}"
                return True, f"Applied tmux config file to {host} (no active tmux server to reload)"

            return True, f"Applied tmux config to {host}"
        except Exception as e:
            return False, str(e)
