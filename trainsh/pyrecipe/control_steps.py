"""Control helpers (tmux, sleep and other non-provider primitives)."""

from __future__ import annotations

from typing import Iterable, Optional, Dict, Any

from ..core.recipe_models import RecipeStepModel, StepType


class RecipeControlMixin:
    """DSL control step helpers for tmux/sleep-like actions."""

    def _control_step(
        self,
        command: str,
        args: Iterable[str],
        raw: str,
    ) -> RecipeStepModel:
        args = list(args)
        return RecipeStepModel(
            type=StepType.CONTROL,
            line_num=0,
            raw=raw,
            command=command,
            args=args,
        )

    def tmux_open(
        self,
        host: str,
        *,
        as_: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Open a tmux session bound to host."""
        host_ref = f"@{self._clean_session(host)}" if host else ""
        session_name = as_ or "main"
        raw = f"tmux.open {host_ref} as {session_name}"
        return self._add_step(
            self._control_step("tmux.open", [host_ref, "as", session_name], raw),
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def tmux_close(
        self,
        session: str,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Close a tmux window/session."""
        session_ref = f"@{self._clean_session(session)}"
        raw = f"tmux.close {session_ref}"
        return self._add_step(
            self._control_step("tmux.close", [session_ref], raw),
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def tmux_config(
        self,
        host: str,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Apply configured tmux options to host."""
        host_ref = f"@{self._clean_session(host)}" if host else ""
        raw = f"tmux.config {host_ref}"
        return self._add_step(
            self._control_step("tmux.config", [host_ref], raw),
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def sleep(
        self,
        duration: str,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Sleep for duration (control-style wait)."""
        raw = f"sleep {duration}"
        return self._add_step(
            self._control_step("sleep", [str(duration)], raw),
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def notice(
        self,
        message: str,
        *,
        level: str = "info",
        channels: Optional[Iterable[str]] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compatibility control wrapper for notice-style steps."""
        params: Dict[str, Any] = {
            "message": message,
            "level": level,
        }
        if channels is not None:
            params["channels"] = list(channels)
        return self.provider(
            "util",
            "notice",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def vast_start(
        self,
        instance_id: Optional[str] = None,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for vast provider start."""
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
        """Alias for vast provider stop."""
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
        """Alias for vast provider pick."""
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
        """Alias for vast provider wait."""
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
        """Alias for vast provider cost."""
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

    def join(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Join branch flows with Airflow-like all-done trigger semantics."""
        options = dict(step_options or {})
        options.setdefault("trigger_rule", "all_done")
        return self.empty(
            id=id,
            depends_on=depends_on,
            step_options=options,
        )

    def on_all_success(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op join point that follows Airflow `all_success`."""
        options = dict(step_options or {})
        options.setdefault("trigger_rule", "all_success")
        return self.empty(id=id, depends_on=depends_on, step_options=options)

    def on_all_done(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op join point that follows Airflow `all_done`."""
        return self.join(
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def on_all_failed(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op join point that follows Airflow `all_failed`."""
        options = dict(step_options or {})
        options.setdefault("trigger_rule", "all_failed")
        return self.empty(id=id, depends_on=depends_on, step_options=options)

    def on_one_success(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op join point that follows Airflow `one_success`."""
        options = dict(step_options or {})
        options.setdefault("trigger_rule", "one_success")
        return self.empty(id=id, depends_on=depends_on, step_options=options)

    def on_one_failed(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op join point that follows Airflow `one_failed`."""
        options = dict(step_options or {})
        options.setdefault("trigger_rule", "one_failed")
        return self.empty(id=id, depends_on=depends_on, step_options=options)

    def on_none_failed(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op join point that follows Airflow `none_failed`."""
        options = dict(step_options or {})
        options.setdefault("trigger_rule", "none_failed")
        return self.empty(id=id, depends_on=depends_on, step_options=options)

    def on_none_failed_or_skipped(
        self,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """No-op join point that follows Airflow `none_failed_or_skipped`."""
        options = dict(step_options or {})
        options.setdefault("trigger_rule", "none_failed_or_skipped")
        return self.empty(id=id, depends_on=depends_on, step_options=options)
