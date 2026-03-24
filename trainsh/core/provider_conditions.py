"""Condition, retry gate, and lightweight command helpers for providers."""

from __future__ import annotations

import shlex
import time
from typing import Any, Dict


class ExecutorProviderConditionsMixin:
    def _exec_provider_wait_condition(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait until a condition is satisfied."""
        if not isinstance(params, dict):
            return False, "Provider util.wait_condition params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.wait_condition requires 'condition'"

        host = self._provider_host(params.get("host", "local"))
        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            allow_zero=True,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        poll_interval = self._normalize_provider_timeout(
            params.get("poll_interval", params.get("interval", params.get("poll_interval_secs", 5))),
            allow_zero=True,
        )
        if poll_interval is None:
            return False, f"Invalid poll_interval value: {params.get('poll_interval')!r}"
        if poll_interval <= 0:
            poll_interval = 5
        capture_output = self._coerce_bool(params.get("capture", False), default=False)

        deadline = time.time() + timeout if timeout else 0
        while True:
            ok, message = self._eval_condition(condition, host=host)
            if ok:
                if capture_output:
                    return True, message
                return True, f"Condition met: {condition}"

            if timeout and time.time() >= deadline:
                return False, f"Timeout waiting for condition: {condition}"

            time.sleep(poll_interval)

    def _exec_provider_branch(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Evaluate a condition and store branch result variable."""
        if not isinstance(params, dict):
            return False, "Provider util.branch params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.branch requires 'condition'"

        true_value = self._interpolate(str(params.get("true_value", "true")))
        false_value = self._interpolate(str(params.get("false_value", "false")))
        variable = str(params.get("variable", "branch")).strip()
        host = self._provider_host(params.get("host", "local"))

        ok, message = self._eval_condition(condition, host=host)
        branch_value = true_value if ok else false_value
        if variable:
            self.ctx.variables[variable] = branch_value

        return True, f"branch={branch_value}; {message}"

    def _exec_provider_short_circuit(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Fail step when condition check does not pass."""
        if not isinstance(params, dict):
            return False, "Provider util.short_circuit params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.short_circuit requires 'condition'"

        host = self._provider_host(params.get("host", "local"))
        invert = self._coerce_bool(params.get("invert", params.get("not", False)), default=False)
        message = str(params.get("message", "condition not met"))

        ok, detail = self._eval_condition(condition, host=host)
        if invert:
            ok = not ok
        if ok:
            return True, f"Condition passed: {detail}"
        return False, f"Condition blocked: {message}"

    def _exec_provider_latest_only(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Keep only the newest run for this recipe when runtime state is available."""
        if not isinstance(params, dict):
            return False, "Provider util.latest_only params must be an object"

        enabled = self._coerce_bool(params.get("enabled", True), default=True)
        if not enabled:
            return True, "latest_only disabled"

        message = str(params.get("message", "Skipped by latest_only"))
        fail_if_unknown = self._coerce_bool(params.get("fail_if_unknown", False), default=False)

        from ..constants import RUNTIME_STATE_DIR
        from ..core.runtime_store import RuntimeStore

        runtime_state = str(params.get("runtime_state", "")).strip()
        if not runtime_state:
            runtime_state = str(RUNTIME_STATE_DIR)

        import os
        from pathlib import Path

        runtime_path = Path(runtime_state).expanduser()
        if runtime_path.suffix:
            runtime_path = runtime_path.with_suffix("")

        if not os.path.exists(runtime_path):
            if fail_if_unknown:
                return False, "latest_only cannot determine state: runtime state not found"
            return (
                True,
                "latest_only passed (runtime state not found; install the jsonl callback or set fail_if_unknown=False)",
            )

        current_run_id = self.ctx.job_id
        recipe_name = self.recipe.name
        dag_id = self.recipe_path or self.recipe.name
        current_started_at = self.ctx.start_time.isoformat() if self.ctx.start_time else ""
        if not current_started_at:
            if fail_if_unknown:
                return False, "latest_only cannot determine current run start time"
            return True, "latest_only passed (current run start time unavailable)"

        try:
            store = RuntimeStore(runtime_path)
            row = None
            for record in store.list_runs():
                if str(record.get("run_id", "")) == current_run_id:
                    continue
                started_at = str(record.get("started_at", "") or "")
                if not started_at or started_at <= current_started_at:
                    continue
                if str(record.get("recipe_name", "")) == recipe_name or str(record.get("dag_id", "")) == dag_id:
                    row = record
                    break
        except Exception as exc:
            if fail_if_unknown:
                return False, f"latest_only runtime-state check failed: {exc}"
            return True, f"latest_only passed (runtime-state check failed: {exc})"

        if row:
            return False, message
        return True, "latest_only check passed"

    def _exec_provider_fail(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Explicitly fail this step."""
        if not isinstance(params, dict):
            return False, "Provider util.fail params must be an object"

        message = str(params.get("message", "Failed by recipe.")).strip()
        if not message:
            message = "Failed by recipe."

        exit_code = params.get("exit_code", 1)
        try:
            exit_code = int(exit_code)
        except Exception:
            exit_code = 1
        if exit_code == 0:
            exit_code = 1

        return False, f"{message} (exit_code={exit_code})"

    def _exec_provider_ssh_command(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute SSH-style command from provider."""
        if not isinstance(params, dict):
            return False, "Provider util.ssh_command params must be an object"

        command = str(params.get("command", "")).strip()
        if not command:
            return False, "Provider util.ssh_command requires 'command'"

        return self._exec_provider_shell(
            {
                "command": command,
                "host": self._provider_host(params.get("host", "local")),
                "timeout": self._normalize_provider_timeout(
                    params.get("timeout", params.get("timeout_secs", 0)),
                    allow_zero=True,
                ),
            }
        )

    def _exec_provider_uv_run(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Run commands using uv."""
        if not isinstance(params, dict):
            return False, "Provider util.uv_run params must be an object"

        command = self._interpolate(str(params.get("command", ""))).strip()
        if not command:
            return False, "Provider util.uv_run requires 'command'"

        packages = params.get("packages", params.get("with", []))
        if isinstance(packages, str):
            packages = [packages]

        uv_parts = ["uv", "run"]
        for pkg in packages or []:
            if not str(pkg).strip():
                continue
            uv_parts.append("--with")
            uv_parts.append(str(pkg))
        uv_parts.append(command)

        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 0)),
            allow_zero=False,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"

        return self._exec_provider_shell(
            {
                "command": " ".join(shlex.quote(part) for part in uv_parts),
                "host": self._provider_host(params.get("host", "local")),
                "timeout": timeout,
            }
        )
