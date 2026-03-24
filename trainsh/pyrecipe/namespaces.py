"""Small bound namespaces for the explicit Python recipe API."""

from __future__ import annotations

from typing import Any, Iterable, Optional, TYPE_CHECKING

from .models import Host, RunpodHost, VastHost
from .models import PythonRecipeError
from ..services.vllm_service import (
    apply_serve_tuning_defaults,
    build_vllm_serve_command,
    default_service_name,
    normalize_gpu_selection,
)

if TYPE_CHECKING:
    from .base import RecipeSpecCore


class VastNamespace:
    """Recipe-bound Vast helpers."""

    def __init__(self, recipe: "RecipeSpecCore"):
        self._recipe = recipe

    def _instance_id(self, target: Any) -> Optional[str]:
        if target is None:
            return None
        if isinstance(target, VastHost):
            return target.instance_id
        if isinstance(target, Host):
            spec = target.spec.strip()
            if spec.startswith("vast:"):
                return spec.split(":", 1)[1]
            if target.name:
                return str(target.name).strip()
            return spec
        return str(target).strip()

    def start(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.vast.start(...) requires an explicit Vast host or alias")
        return self._recipe.vast_start(self._instance_id(target), **kwargs)

    def stop(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.vast.stop(...) requires an explicit Vast host or alias")
        return self._recipe.vast_stop(self._instance_id(target), **kwargs)

    def wait(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.vast.wait(...) requires an explicit Vast host or alias")
        return self._recipe.vast_wait(self._instance_id(target), **kwargs)

    def wait_ready(self, target: Any = None, **kwargs: Any) -> str:
        return self.wait(target, **kwargs)

    def pick(self, **kwargs: Any) -> str:
        payload = dict(kwargs)
        if "host" in payload:
            payload["host"] = self._recipe.resolve_host(payload["host"])
        return self._recipe.vast_pick(**payload)

    def cost(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.vast.cost(...) requires an explicit Vast host or alias")
        return self._recipe.vast_cost(self._instance_id(target), **kwargs)


class RunpodNamespace:
    """Recipe-bound RunPod helpers."""

    def __init__(self, recipe: "RecipeSpecCore"):
        self._recipe = recipe

    def _pod_id(self, target: Any) -> Optional[str]:
        if target is None:
            return None
        if isinstance(target, RunpodHost):
            return target.pod_id
        if isinstance(target, Host):
            spec = target.spec.strip()
            if spec.startswith("runpod:"):
                return spec.split(":", 1)[1]
            if target.name:
                return str(target.name).strip()
            return spec
        return str(target).strip()

    def start(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.runpod.start(...) requires an explicit RunPod host or alias")
        return self._recipe.runpod_start(self._pod_id(target), **kwargs)

    def stop(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.runpod.stop(...) requires an explicit RunPod host or alias")
        return self._recipe.runpod_stop(self._pod_id(target), **kwargs)

    def wait(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.runpod.wait(...) requires an explicit RunPod host or alias")
        return self._recipe.runpod_wait(self._pod_id(target), **kwargs)

    def wait_ready(self, target: Any = None, **kwargs: Any) -> str:
        return self.wait(target, **kwargs)

    def pick(self, **kwargs: Any) -> str:
        payload = dict(kwargs)
        if "host" in payload:
            payload["host"] = self._recipe.resolve_host(payload["host"])
        return self._recipe.runpod_pick(**payload)

    def cost(self, target: Any = None, **kwargs: Any) -> str:
        if target is None:
            raise PythonRecipeError("recipe.runpod.cost(...) requires an explicit RunPod host or alias")
        return self._recipe.runpod_cost(self._pod_id(target), **kwargs)


class NotifyNamespace:
    """Recipe-bound notification helpers."""

    def __init__(self, recipe: "RecipeSpecCore"):
        self._recipe = recipe

    def __call__(self, message: str, **kwargs: Any) -> str:
        return self._recipe.notice(message, **kwargs)

    def notice(self, message: str, **kwargs: Any) -> str:
        return self._recipe.notice(message, **kwargs)

    def email(self, message: str, **kwargs: Any) -> str:
        return self._recipe.email_send(message, **kwargs)

    def slack(self, message: str, **kwargs: Any) -> str:
        return self._recipe.slack(message, **kwargs)

    def telegram(self, message: str, **kwargs: Any) -> str:
        return self._recipe.telegram(message, **kwargs)

    def discord(self, message: str, **kwargs: Any) -> str:
        return self._recipe.discord(message, **kwargs)

    def webhook(self, message: str, **kwargs: Any) -> str:
        return self._recipe.webhook(message, **kwargs)


class VllmNamespace:
    """Recipe-bound vLLM convenience helpers."""

    def __init__(self, recipe: "RecipeSpecCore"):
        self._recipe = recipe

    def serve(
        self,
        host: Any,
        model: str,
        *,
        name: Optional[str] = None,
        port: int = 8000,
        bind_host: str = "127.0.0.1",
        workdir: Optional[str] = None,
        env: Optional[dict[str, Any]] = None,
        args: Optional[Iterable[Any]] = None,
        gpus: Optional[Any] = None,
        tp: Optional[int] = None,
        gpu_memory_utilization: Optional[Any] = None,
        wait: bool = True,
        timeout: Any = "10m",
        poll_interval: Any = "5s",
        id: Optional[str] = None,
        wait_id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[dict[str, Any]] = None,
        close: bool = False,
        close_step_options: Optional[dict[str, Any]] = None,
    ):
        """Start one vLLM server in tmux and optionally wait for readiness.

        Returns a tmux session ref whose future steps depend on the start step
        or the readiness wait step when ``wait=True``.
        """
        model_text = str(model or "").strip()
        if not model_text:
            raise PythonRecipeError("recipe.vllm.serve(...) requires a non-empty model")

        service_name = str(name or default_service_name(model_text)).strip() or default_service_name(model_text)
        extra_args = [str(item) for item in (args or []) if str(item).strip()]
        merged_env = dict(env or {})
        tp_explicit = tp is not None or any(
            str(item).startswith("--tensor-parallel-size")
            for item in extra_args
        )
        if gpus is not None:
            try:
                gpu_text, gpu_count = normalize_gpu_selection(gpus)
            except ValueError as exc:
                raise PythonRecipeError(str(exc)) from exc
            merged_env["CUDA_VISIBLE_DEVICES"] = gpu_text
            if gpu_count > 1 and not tp_explicit:
                tp = gpu_count
        if tp is not None:
            extra_args.append(f"--tensor-parallel-size={int(tp)}")
        extra_args = apply_serve_tuning_defaults(
            extra_args,
            gpu_memory_utilization=gpu_memory_utilization,
        )

        session = self._recipe._tmux_ref(
            service_name,
            host=host,
            cwd=workdir,
            env=merged_env or None,
            id=id,
            depends_on=depends_on,
            close=close,
            close_step_options=close_step_options,
        )
        start_step = session.bg(
            build_vllm_serve_command(
                model=model_text,
                port=int(port),
                bind_host=str(bind_host or "127.0.0.1"),
                extra_args=extra_args,
            ),
            step_options=step_options,
        )
        if not wait:
            return session.after(start_step)

        host_ref = str(session.host_ref or "").strip()
        if not host_ref:
            raise PythonRecipeError("recipe.vllm.serve(...) could not resolve a host reference")
        wait_step = self._recipe.wait_for_port(
            int(port),
            host=host_ref,
            host_name=str(bind_host or "127.0.0.1"),
            timeout=timeout,
            poll_interval=poll_interval,
            id=wait_id,
            depends_on=[start_step],
            step_options=step_options,
        )
        return session.after(wait_step)


__all__ = ["NotifyNamespace", "RunpodNamespace", "VastNamespace", "VllmNamespace"]
