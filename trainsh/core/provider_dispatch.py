"""Provider metadata parsing and top-level dispatch."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple


class ExecutorProviderDispatchMixin:
    def _extract_provider_metadata(self, step: object) -> Tuple[str, str, Dict[str, Any]]:
        """Extract provider metadata from either ProviderStep or provider-control DSL fallback."""
        provider = str(getattr(step, "provider", "")).strip()
        operation = str(getattr(step, "operation", "")).strip()
        params = getattr(step, "params", None)

        if not provider and getattr(step, "command", "") == "provider":
            raw = str(getattr(step, "raw", "")).strip()
            if raw.startswith("provider "):
                remain = raw[len("provider "):].strip()
                op_text, _, json_text = remain.partition(" ")
                if "." in op_text:
                    provider, operation = [part.strip() for part in op_text.split(".", 1)]
                else:
                    if op_text:
                        provider = op_text
                if json_text:
                    try:
                        parsed_params = json.loads(json_text)
                        if isinstance(parsed_params, dict):
                            params = parsed_params
                    except Exception:
                        params = None

        provider = provider.lower()
        operation = operation.lower()
        if not isinstance(params, dict):
            params = {}
        return provider, operation, params

    def _normalize_provider_timeout(self, value: Any, *, allow_zero: bool = True) -> Optional[int]:
        """Normalize provider timeout values."""
        if value is None:
            return 0 if allow_zero else None

        if isinstance(value, bool):
            value = int(value)
        if isinstance(value, (int, float)):
            timeout = int(value)
            if timeout < 0:
                return None
            if timeout == 0:
                return 0 if allow_zero else None
            return timeout

        text = str(value).strip()
        if not text:
            return 0 if allow_zero else None

        try:
            timeout = self._parse_duration(text)
        except Exception:
            return None

        if timeout < 0:
            return None
        if timeout == 0:
            return 0 if allow_zero else None
        return timeout

    def _positive_provider_timeout(
        self,
        value: Any,
        *,
        default: int = 300,
    ) -> int:
        """Normalize timeout values and always return a positive integer."""
        timeout = self._normalize_provider_timeout(value, allow_zero=False)
        if timeout is None or timeout <= 0:
            return default
        return timeout

    def _provider_host(self, value: Any) -> str:
        """Resolve provider host shorthand."""
        host = str(value).strip() if value is not None else ""
        if not host:
            return "local"
        if host.startswith("@"):
            return self._resolve_host(host)
        return self._resolve_host(f"@{host}")

    def _exec_provider(self, step) -> tuple[bool, str]:
        """Execute provider style step."""
        provider, operation, params = self._extract_provider_metadata(step)
        if not provider:
            return False, "Provider step missing provider name"
        if not operation:
            return False, f"Provider {provider} missing operation"

        if provider == "shell" and operation in {"run", "execute", "exec", "command"}:
            return self._exec_provider_shell(params)
        if provider == "bash" and operation in {
            "run",
            "execute",
            "exec",
            "command",
            "bash",
        }:
            return self._exec_provider_shell(params)
        if provider == "python" and operation in {
            "run",
            "exec",
            "execute",
            "python",
        }:
            return self._exec_provider_python(params)
        if provider in {"bash", "python"} and operation in {
            "local",
            "local_run",
        }:
            return self._exec_provider_shell(params)
        if provider == "cloud":
            storage_params = dict(params)
            storage_name = str(
                storage_params.get("storage")
                or storage_params.get("cloud")
                or storage_params.get("bucket")
                or storage_params.get("name")
                or ""
            ).strip()
            if not storage_name:
                return False, "Provider cloud requires 'storage' (or 'cloud'/'bucket' alias)"
            storage_params["storage"] = storage_name.lstrip("@")

            if operation in {"upload", "put", "write", "publish", "send"}:
                return self._exec_provider_storage_upload(storage_params)
            if operation in {"download", "get", "fetch", "retrieve"}:
                return self._exec_provider_storage_download(storage_params)
            if operation in {"list", "ls", "list_files"}:
                return self._exec_provider_storage_list(storage_params)
            if operation in {"exists", "check", "test"}:
                return self._exec_provider_storage_exists(storage_params)
            if operation in {"count", "count_entries"}:
                return self._exec_provider_storage_count(storage_params)
            if operation in {"read", "read_text", "cat"}:
                return self._exec_provider_storage_read_text(storage_params)
            if operation in {"info", "stat"}:
                return self._exec_provider_storage_info(storage_params)
            if operation in {"wait", "wait_for", "wait_for_key"}:
                return self._exec_provider_storage_wait(storage_params)
            if operation in {"wait_count", "wait_for_count"}:
                return self._exec_provider_storage_wait_count(storage_params)
            if operation == "mkdir":
                return self._exec_provider_storage_mkdir(storage_params)
            if operation in {"ensure_bucket", "ensure_container"}:
                return self._exec_provider_storage_ensure_bucket(storage_params)
            if operation in {"delete", "remove", "rm"}:
                return self._exec_provider_storage_delete(storage_params)
            if operation in {"rename", "move", "mv"}:
                return self._exec_provider_storage_rename(storage_params)
            if operation == "transfer":
                return self._exec_provider_transfer(storage_params)
            return False, f"Unsupported cloud operation: {provider}.{operation}"
        if provider == "http" and operation in {
            "request",
            "get",
            "post",
            "put",
            "delete",
            "head",
            "patch",
            "options",
            "request_json",
            "json_request",
            "json",
        }:
            mapped = dict(params)
            if operation in {"request_json", "json_request", "json"}:
                if "body" not in mapped and "json_body" in mapped:
                    mapped["body"] = mapped["json_body"]
                if "method" not in mapped:
                    mapped["method"] = "POST"
            elif operation != "request" and "method" not in mapped:
                mapped["method"] = operation.upper()
            return self._exec_provider_http_request(mapped)
        if provider == "http" and operation in {
            "wait_for_status",
            "wait_status",
            "wait_for_response",
            "http_sensor",
            "sensor",
            "wait",
        }:
            return self._exec_provider_http_wait(params)
        if provider == "http" and operation in {"http"}:
            mapped = dict(params)
            if "method" not in mapped:
                mapped["method"] = "GET"
            return self._exec_provider_http_request(mapped)
        if provider in {"util", "utils"} and operation == "hf_download":
            return self._exec_provider_hf_download(params)
        if provider in {"util", "utils"} and operation == "fetch_exchange_rates":
            return self._exec_provider_fetch_exchange_rates(params)
        if provider in {"util", "utils"} and operation == "calculate_cost":
            return self._exec_provider_calculate_cost(params)
        if provider == "util" and operation == "wait_condition":
            return self._exec_provider_wait_condition(params)
        if provider == "util" and operation == "ssh_command":
            return self._exec_provider_ssh_command(params)
        if provider == "util" and operation == "uv_run":
            return self._exec_provider_uv_run(params)
        if provider == "storage" and operation == "test":
            return self._exec_provider_storage_test(params)
        if provider == "storage" and operation in {"list", "ls"}:
            return self._exec_provider_storage_list(params)
        if provider == "storage" and operation in {"exists", "check", "test"}:
            return self._exec_provider_storage_exists(params)
        if provider == "storage" and operation in {"count", "count_entries"}:
            return self._exec_provider_storage_count(params)
        if provider == "storage" and operation in {"info", "stat"}:
            return self._exec_provider_storage_info(params)
        if provider == "storage" and operation in {"read_text", "read", "cat"}:
            return self._exec_provider_storage_read_text(params)
        if provider == "storage" and operation == "wait":
            return self._exec_provider_storage_wait(params)
        if provider == "storage" and operation in {"wait_count", "wait_for_count"}:
            return self._exec_provider_storage_wait_count(params)
        if provider == "storage" and operation == "mkdir":
            return self._exec_provider_storage_mkdir(params)
        if provider == "storage" and operation in {"ensure_bucket", "ensure_container"}:
            return self._exec_provider_storage_ensure_bucket(params)
        if provider == "storage" and operation == "delete":
            return self._exec_provider_storage_delete(params)
        if provider == "storage" and operation == "rename":
            return self._exec_provider_storage_rename(params)
        if provider == "storage" and operation in {"copy", "sync", "move"}:
            return self._exec_provider_transfer(params)
        if provider == "storage" and operation == "upload":
            return self._exec_provider_storage_upload(params)
        if provider == "storage" and operation == "download":
            return self._exec_provider_storage_download(params)
        if provider in {"transfer", "storage"} and operation in {"copy", "cp", "sync", "move", "mirror"}:
            return self._exec_provider_transfer(params)
        if provider == "util" and operation == "set_var":
            return self._exec_provider_set_var(params)
        step_task_id = str(getattr(step, "id", "")).strip()
        if provider == "util" and operation == "xcom_push":
            mapped = dict(params)
            if step_task_id and "task_id" not in mapped:
                mapped["task_id"] = step_task_id
            return self._exec_provider_xcom_push(mapped)
        if provider == "util" and operation == "xcom_pull":
            mapped = dict(params)
            if step_task_id and "task_id" not in mapped:
                mapped["task_id"] = step_task_id
            return self._exec_provider_xcom_pull(mapped)
        if provider in {
            "util",
            "email",
            "webhook",
            "slack",
            "telegram",
            "discord",
        } and operation in {"notice", "notify", "send", "send_notice", "send_notification"}:
            return self._exec_provider_notice(params)
        if provider == "util" and operation == "branch":
            return self._exec_provider_branch(params)
        if provider == "util" and operation in {"short_circuit", "skip_if", "skip_if_not"}:
            return self._exec_provider_short_circuit(params)
        if provider == "util" and operation == "fail":
            return self._exec_provider_fail(params)
        if provider == "util" and operation == "latest_only":
            return self._exec_provider_latest_only(params)
        if provider == "util" and operation == "sleep":
            return self._cmd_sleep([str(params.get("duration", params.get("duration_secs", "0")))])
        if provider in {"shell", "bash"} and operation in {
            "local",
            "local_run",
        }:
            return self._exec_provider_shell(params)
        if provider == "util" and operation in {"empty", "noop"}:
            return self._exec_provider_empty(params)
        if provider in {"vast", "vasts"} and operation in {"start", "stop", "pick", "wait", "cost"}:
            return self._exec_provider_vast(operation, params)
        if provider in {"runpod", "runpods"} and operation in {"start", "stop", "pick", "wait", "cost"}:
            return self._exec_provider_runpod(operation, params)
        if provider == "git" and operation == "clone":
            return self._exec_provider_git_clone(params)
        if provider == "git" and operation == "pull":
            return self._exec_provider_git_pull(params)
        if provider == "host" and operation in {"test", "connect", "verify"}:
            return self._exec_provider_host_test(params)
        if provider == "util" and operation == "assert":
            return self._exec_provider_assert(params)
        if provider == "util" and operation == "get_value":
            return self._exec_provider_get_value(params)
        if provider == "util" and operation == "set_env":
            return self._exec_provider_set_env(params)
        if provider == "util" and operation == "wait_file":
            return self._exec_provider_wait_for_file(params)
        if provider == "util" and operation == "wait_port":
            return self._exec_provider_wait_for_port(params)
        if provider in {
            "email",
            "webhook",
            "slack",
            "telegram",
            "discord",
        } and operation in {
            "send",
            "notice",
        }:
            return self._exec_provider_notice(params)

        return False, f"Unsupported provider step: {provider}.{operation}"
