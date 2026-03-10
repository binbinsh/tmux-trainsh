"""Core provider-backed step helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from .models import PythonRecipeError, ProviderStep


class RecipeProviderBasicMixin:
    """Generic provider helpers and basic command-style operations."""

    def provider(
        self,
        provider: str,
        operation: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a generic provider step."""
        if not provider or not operation:
            raise PythonRecipeError("provider and operation must be non-empty")

        return self._add_step(
            ProviderStep(
                provider=str(provider).strip(),
                operation=str(operation).strip(),
                params=dict(params or {}),
                id="",
            ),
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def shell(
        self,
        command: str,
        *,
        timeout: Any = 0,
        host: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Run shell command."""
        params: Dict[str, Any] = {
            "command": str(command),
            "timeout": timeout,
        }
        if cwd is not None:
            params["cwd"] = cwd
        if env:
            params["env"] = env
        if host is not None:
            params["host"] = host
        if capture_var is not None:
            params["capture_var"] = capture_var
        return self.provider(
            "shell",
            "run",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def bash(
        self,
        command: str,
        *,
        timeout: Any = 0,
        host: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for :meth:`shell`."""
        return self.shell(
            command,
            timeout=timeout,
            host=host,
            cwd=cwd,
            env=env,
            capture_var=capture_var,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def python(
        self,
        code_or_command: str,
        *,
        script: Optional[str] = None,
        timeout: Any = 0,
        host: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
        capture_var: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Run python code or script."""
        value = str(code_or_command).strip()
        params: Dict[str, Any] = {
            "timeout": timeout,
        }
        if script is not None:
            params["script"] = str(script)
        elif value and "\n" in value:
            params["code"] = value
        else:
            params["command"] = value

        if cwd is not None:
            params["cwd"] = cwd
        if env:
            params["env"] = env
        if host is not None:
            params["host"] = host
        if capture_var is not None:
            params["capture_var"] = capture_var
        return self.provider(
            "python",
            "run",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def empty(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op step."""
        return self.provider(
            "util",
            "empty",
            params={},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def noop(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for :meth:`empty`."""
        return self.empty(id=id, depends_on=depends_on, step_options=step_options)

    def vast_start(
        self,
        instance_id: Optional[str] = None,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start/warm up a vast instance."""
        params: Dict[str, Any] = {}
        if instance_id is not None:
            params["instance_id"] = instance_id
        return self.provider(
            "vast",
            "start",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def vast_stop(
        self,
        instance_id: Optional[str] = None,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Stop a vast instance."""
        params: Dict[str, Any] = {}
        if instance_id is not None:
            params["instance_id"] = instance_id
        return self.provider(
            "vast",
            "stop",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def vast_pick(
        self,
        host: str = "gpu",
        *,
        gpu_name: Optional[str] = None,
        num_gpus: Optional[int] = None,
        min_gpu_ram: Optional[Any] = None,
        max_dph: Optional[Any] = None,
        limit: Optional[int] = None,
        skip_if_set: bool = True,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Pick vast instance by filter."""
        params: Dict[str, Any] = {
            "host": host,
            "skip_if_set": bool(skip_if_set),
        }
        if gpu_name is not None:
            params["gpu_name"] = gpu_name
        if num_gpus is not None:
            params["num_gpus"] = num_gpus
        if min_gpu_ram is not None:
            params["min_gpu_ram"] = min_gpu_ram
        if max_dph is not None:
            params["max_dph"] = max_dph
        if limit is not None:
            params["limit"] = limit
        return self.provider(
            "vast",
            "pick",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def vast_wait(
        self,
        instance_id: Optional[str] = None,
        *,
        timeout: Any = "10m",
        poll_interval: Any = "10s",
        stop_on_fail: bool = True,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Wait for vast instance ready."""
        params: Dict[str, Any] = {
            "timeout": timeout,
            "poll_interval": poll_interval,
            "stop_on_fail": stop_on_fail,
        }
        if instance_id is not None:
            params["instance_id"] = instance_id
        return self.provider(
            "vast",
            "wait",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def vast_cost(
        self,
        instance_id: Optional[str] = None,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Calculate vast instance usage estimate."""
        params: Dict[str, Any] = {}
        if instance_id is not None:
            params["instance_id"] = instance_id
        return self.provider(
            "vast",
            "cost",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def set_var(
        self,
        name: str,
        value: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Set recipe variable."""
        return self.provider(
            "util",
            "set_var",
            params={"name": name, "value": "" if value is None else str(value)},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )
