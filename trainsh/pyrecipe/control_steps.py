"""Control helpers (tmux, sleep and other non-provider primitives)."""

from __future__ import annotations

from typing import Iterable, Optional, Dict, Any

from ..core.recipe_models import RecipeStepModel, StepType
from .models import PythonRecipeError


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
        instance_id: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for vast provider start."""
        if instance_id is None or not str(instance_id).strip():
            raise PythonRecipeError("vast_start requires an explicit Vast host or instance id")
        params: Dict[str, Any] = {"instance_id": instance_id}
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
        instance_id: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for vast provider stop."""
        if instance_id is None or not str(instance_id).strip():
            raise PythonRecipeError("vast_stop requires an explicit Vast host or instance id")
        params: Dict[str, Any] = {"instance_id": instance_id}
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
        auto_select: bool = False,
        create_if_missing: bool = False,
        image: Optional[str] = None,
        disk_gb: Optional[Any] = None,
        label: Optional[str] = None,
        direct: Optional[bool] = None,
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
        params["auto_select"] = bool(auto_select)
        params["create_if_missing"] = bool(create_if_missing)
        if image is not None:
            params["image"] = image
        if disk_gb is not None:
            params["disk_gb"] = disk_gb
        if label is not None:
            params["label"] = label
        if direct is not None:
            params["direct"] = bool(direct)
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
        instance_id: Any,
        *,
        timeout: Any = "10m",
        poll_interval: Any = "10s",
        stop_on_fail: bool = True,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for vast provider wait."""
        if instance_id is None or not str(instance_id).strip():
            raise PythonRecipeError("vast_wait requires an explicit Vast host or instance id")
        params: Dict[str, Any] = {
            "instance_id": instance_id,
            "timeout": timeout,
            "poll_interval": poll_interval,
            "stop_on_fail": stop_on_fail,
        }
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
        instance_id: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for vast provider cost."""
        if instance_id is None or not str(instance_id).strip():
            raise PythonRecipeError("vast_cost requires an explicit Vast host or instance id")
        params: Dict[str, Any] = {"instance_id": instance_id}
        return self.provider(
            "vast",
            "cost",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def runpod_start(
        self,
        pod_id: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for runpod provider start."""
        if pod_id is None or not str(pod_id).strip():
            raise PythonRecipeError("runpod_start requires an explicit RunPod host or Pod id")
        return self.provider(
            "runpod",
            "start",
            params={"pod_id": pod_id},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def runpod_stop(
        self,
        pod_id: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for runpod provider stop."""
        if pod_id is None or not str(pod_id).strip():
            raise PythonRecipeError("runpod_stop requires an explicit RunPod host or Pod id")
        return self.provider(
            "runpod",
            "stop",
            params={"pod_id": pod_id},
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def runpod_pick(
        self,
        host: str = "gpu",
        *,
        gpu_name: Optional[str] = None,
        num_gpus: Optional[int] = None,
        min_gpu_ram: Optional[Any] = None,
        max_dph: Optional[Any] = None,
        limit: Optional[int] = None,
        skip_if_set: bool = True,
        auto_select: bool = False,
        create_if_missing: bool = False,
        image: Optional[str] = None,
        disk_gb: Optional[Any] = None,
        volume_gb: Optional[Any] = None,
        label: Optional[str] = None,
        cloud_type: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for runpod provider pick."""
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
        params["auto_select"] = bool(auto_select)
        params["create_if_missing"] = bool(create_if_missing)
        if image is not None:
            params["image"] = image
        if disk_gb is not None:
            params["disk_gb"] = disk_gb
        if volume_gb is not None:
            params["volume_gb"] = volume_gb
        if label is not None:
            params["label"] = label
        if cloud_type is not None:
            params["cloud_type"] = cloud_type
        return self.provider(
            "runpod",
            "pick",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def runpod_wait(
        self,
        pod_id: Any,
        *,
        timeout: Any = "10m",
        poll_interval: Any = "10s",
        stop_on_fail: bool = True,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for runpod provider wait."""
        if pod_id is None or not str(pod_id).strip():
            raise PythonRecipeError("runpod_wait requires an explicit RunPod host or Pod id")
        return self.provider(
            "runpod",
            "wait",
            params={
                "pod_id": pod_id,
                "timeout": timeout,
                "poll_interval": poll_interval,
                "stop_on_fail": stop_on_fail,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def runpod_cost(
        self,
        pod_id: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Alias for runpod provider cost."""
        if pod_id is None or not str(pod_id).strip():
            raise PythonRecipeError("runpod_cost requires an explicit RunPod host or Pod id")
        return self.provider(
            "runpod",
            "cost",
            params={"pod_id": pod_id},
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
