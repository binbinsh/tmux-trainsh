"""Notification and misc provider tail operations."""

from __future__ import annotations

import shlex
from typing import Any, Dict, List

from ..utils.notifier import normalize_channels, parse_bool


class ExecutorProviderNotifyMixin:
    def _exec_provider_set_var(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Set recipe variable via provider."""
        if not isinstance(params, dict):
            return False, "Provider util.set_var params must be an object"

        name = params.get("name")
        if not name:
            return False, "Provider util.set_var requires 'name'"
        value = params.get("value", "")
        value_text = "" if value is None else str(value)
        self.ctx.variables[str(name)] = value_text
        return True, f"Set {name}={value_text}"

    def _exec_provider_notice(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Send notification via provider."""
        if not self.notify_enabled:
            return True, "Notification skipped (notifications.enabled=false)"

        if not isinstance(params, dict):
            return False, "Provider util.notice params must be an object"

        message = self._interpolate(str(params.get("message", ""))).strip()
        if not message:
            message = self._interpolate(str(params.get("body", params.get("text", "")))).strip()
        if not message and isinstance(params.get("content"), str):
            message = self._interpolate(str(params.get("content", ""))).strip()
        if not message:
            return False, "Provider util.notice requires 'message'"

        title = self._interpolate(str(params.get("title", params.get("subject", self.notify_app_name)))).strip()
        try:
            channels = normalize_channels(
                params.get("channels"),
                self.notify_default_channels,
            )
        except ValueError as exc:
            return False, str(exc)

        level = str(params.get("level", "info"))
        webhook_url = str(
            self._interpolate(
                str(params.get("webhook") or params.get("webhook_url") or self.notify_default_webhook or "")
            )
        ).strip() or None
        command = str(
            self._interpolate(
                str(params.get("command") or params.get("cmd") or self.notify_default_command or "")
            )
        ).strip() or None

        timeout = self._normalize_provider_timeout(
            params.get("timeout_secs", params.get("timeout", self.notify_default_timeout)),
            allow_zero=True,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout_secs')!r}"
        if timeout <= 0:
            timeout = self.notify_default_timeout

        try:
            fail_on_error = parse_bool(params.get("fail_on_error", self.notify_default_fail_on_error))
        except ValueError as exc:
            return False, str(exc)
        ok, summary = self.notifier.notify(
            title=title,
            message=message,
            level=level,
            channels=channels,
            webhook_url=webhook_url,
            command=command,
            timeout_secs=timeout,
            fail_on_error=fail_on_error,
        )
        return ok, summary

    def _exec_provider_empty(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """No-op provider operation."""
        return True, "noop"

    def _exec_provider_python(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute Python code as a provider operation."""
        if not isinstance(params, dict):
            return False, "Provider python params must be an object"

        command = self._interpolate(str(params.get("command", ""))).strip()
        code = self._interpolate(str(params.get("code", ""))).strip()
        script = self._interpolate(str(params.get("script", ""))).strip()

        if not any((command, code, script)):
            return False, "Provider python requires 'command', 'code', or 'script'"

        if code:
            shell_command = "python - <<'PY'\n" + code + "\nPY"
        elif script:
            shell_command = f"python {shlex.quote(script)}"
        else:
            shell_command = f"python -c {shlex.quote(command)}"

        shell_params = dict(params)
        shell_params["command"] = shell_command
        return self._exec_provider_shell(shell_params)

    def _exec_provider_vast(self, operation: str, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute vast provider operations."""
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return False, "Provider vast params must be an object"

        args: List[str] = []
        op = operation.strip().lower()

        if "args" in params and isinstance(params.get("args"), (list, tuple)):
            args.extend([str(item).strip() for item in params["args"] if str(item).strip()])
        else:
            direct_id = self._interpolate(str(params.get("instance_id", params.get("id", "")))).strip()
            if direct_id:
                args.append(direct_id)

        if op == "pick":
            host_name = self._interpolate(str(params.get("host", params.get("host_name", "")))).strip()
            if host_name.startswith("@"):
                host_name = host_name[1:]
            if host_name:
                args.append(host_name)

        if op == "wait":
            if direct_timeout := str(params.get("timeout", "")).strip():
                args.append(f"timeout={self._interpolate(direct_timeout)}")
            if direct_poll := str(params.get("poll", params.get("poll_interval", ""))).strip():
                args.append(f"poll={self._interpolate(direct_poll)}")
            if "stop_on_fail" in params:
                stop_on_fail = self._interpolate(str(params.get("stop_on_fail")))
                args.append(f"stop_on_fail={stop_on_fail}")

        if op == "pick":
            mapping = {
                "gpu_name": "gpu_name",
                "gpu": "gpu_name",
                "num_gpus": "num_gpus",
                "gpus": "num_gpus",
                "min_gpu_ram": "min_gpu_ram",
                "min_vram_gb": "min_gpu_ram",
                "max_dph": "max_dph",
                "max_price": "max_dph",
                "limit": "limit",
                "skip_if_set": "skip_if_set",
                "auto_select": "auto_select",
                "create_if_missing": "create_if_missing",
                "image": "image",
                "disk_gb": "disk_gb",
                "disk": "disk_gb",
                "label": "label",
                "direct": "direct",
            }
            for key, param_key in mapping.items():
                value = params.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                args.append(f"{param_key}={self._interpolate(text)}")

        if op == "cost":
            # cost currently only uses positional instance id
            pass

        if op not in {"start", "stop", "pick", "wait", "cost"}:
            return False, f"Unsupported vast operation: {operation!r}"

        if op == "start":
            return self._cmd_vast_start(args)
        if op == "stop":
            return self._cmd_vast_stop(args)
        if op == "pick":
            return self._cmd_vast_pick(args)
        if op == "wait":
            return self._cmd_vast_wait(args)
        return self._cmd_vast_cost(args)
