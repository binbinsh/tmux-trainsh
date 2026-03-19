"""Core Python recipe model and builder helpers.

This module keeps the API compact and delegates feature-specific helpers to mixins.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from ..core.recipe_models import RecipeModel, RecipeStepModel
from ..core.models import Storage as RuntimeStorage

from .control_steps import RecipeControlMixin
from .models import Host, HostPath, PythonRecipeError, ProviderStep, RecipeStep, Storage, StoragePath
from .namespaces import (
    NotifyNamespace,
    VastNamespace,
)
from .provider_steps import RecipeProviderMixin
from .provider_misc_steps import RecipeProviderMiscMixin
from .condition_steps import RecipeProviderConditionMixin
from .transfer_steps import RecipeProviderTransferMixin
from .session_steps import RecipeSessionMixin
from .storage_steps import RecipeStorageMixin
from .network_steps import RecipeProviderNetworkMixin
from .references import wrap_step_handle


_ACTIVE_RECIPE: "RecipeSpecCore | None" = None


def get_active_recipe():
    """Return the most recently created recipe used for authoring."""
    return _ACTIVE_RECIPE


class RecipeSpecCore:
    """Shared recipe state and step registration helpers."""

    def __init__(
        self,
        name: str,
        *,
        schedule: Optional[str] = None,
        owner: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        paused: Optional[bool] = None,
        catchup: Optional[bool] = None,
        max_active_runs: Optional[int] = None,
        executor: str = "sequential",
        executor_kwargs: Optional[Dict[str, Any]] = None,
        workers: Optional[int] = None,
        callbacks: Optional[Iterable[str]] = None,
        **extra_executor_kwargs: Any,
    ):
        global _ACTIVE_RECIPE
        self.name = (name or "recipe").strip()
        if not self.name:
            raise PythonRecipeError("recipe name cannot be empty")

        self.variables: Dict[str, str] = {}
        self.steps: List[RecipeStep] = []
        self.hosts: Dict[str, str] = {}
        self.storages: Dict[str, Any] = {}
        self.vast = VastNamespace(self)
        self.notify = NotifyNamespace(self)
        if "".join(ch for ch in str(executor).lower() if ch.isalnum()) in {
            "k8s",
            "kubernetes",
            "kubernetesexecutor",
            "kubernetesexecutors",
            "kubeexecutor",
        }:
            raise PythonRecipeError("kubernetes executor is not supported in this runtime")
        self.executor = executor
        self.executor_kwargs = dict(executor_kwargs or {})
        if workers is not None and "max_workers" not in self.executor_kwargs:
            self.executor_kwargs["max_workers"] = workers
        self.executor_kwargs.update(extra_executor_kwargs)
        self.callbacks = list(callbacks) if callbacks is not None else ["console", "jsonl"]
        self.schedule = schedule
        self.owner = owner or "trainsh"
        self.tags = list(tags or [])
        self.is_paused = bool(paused) if paused is not None else False
        self.catchup = bool(catchup) if catchup is not None else False
        self.max_active_runs = max_active_runs

        self._step_seq = 0
        self._used_ids = set()
        self._task_defaults: Dict[str, Any] = {}
        self._linear_contexts: list[dict[str, Any]] = []
        self._resource_host_aliases: dict[Host, str] = {}
        self._resource_storage_aliases: dict[int, str] = {}
        self._session_registry: dict[str, dict[str, Any]] = {}
        _ACTIVE_RECIPE = self

    def __enter__(self) -> "RecipeSpecCore":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def set_executor(self, name: str, **kwargs: Any) -> None:
        """Change executor type and options."""
        if not name:
            raise PythonRecipeError("executor name cannot be empty")
        normalized = "".join(ch for ch in str(name).lower() if ch.isalnum())
        if normalized in {
            "k8s",
            "kubernetes",
            "kubernetesexecutor",
            "kubernetesexecutors",
            "kubeexecutor",
        }:
            raise PythonRecipeError("kubernetes executor is not supported in this runtime")
        self.executor = str(name)
        self.executor_kwargs.update(kwargs)

    @contextmanager
    def _linear(self, *, depends_on: Any = None):
        """Internal linear authoring context used by tmux-backed blocks."""
        from .authoring_support import normalize_after

        initial_depends = normalize_after(depends_on)
        state = {
            "last": None if initial_depends is not None else (
                self._linear_contexts[-1]["last"] if self._linear_contexts
                else (wrap_step_handle(self, self.steps[-1].id) if self.steps else None)
            ),
            "depends_on": initial_depends,
        }
        self._linear_contexts.append(state)
        try:
            yield self
        finally:
            completed = self._linear_contexts.pop()
            if self._linear_contexts:
                self._linear_contexts[-1]["last"] = completed.get("last")

    def defaults(
        self,
        *,
        retries: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_delay: Any = None,
        continue_on_failure: Optional[bool] = None,
        trigger_rule: Optional[str] = None,
        pool: Optional[str] = None,
        priority: Optional[int] = None,
        execution_timeout: Optional[Any] = None,
        retry_exponential_backoff: Optional[Any] = None,
        max_active_tis_per_dagrun: Optional[Any] = None,
        deferrable: Optional[Any] = None,
        on_success: Optional[Any] = None,
        on_failure: Optional[Any] = None,
    ) -> "RecipeSpecCore":
        """Set defaults applied to subsequent steps."""
        options: Dict[str, Any] = {}
        if retries is not None:
            options["retries"] = retries
        if max_retries is not None and retries is None:
            options["retries"] = max_retries
        if retry_delay is not None:
            options["retry_delay"] = retry_delay
        if continue_on_failure is not None:
            options["continue_on_failure"] = continue_on_failure
        if trigger_rule is not None:
            options["trigger_rule"] = trigger_rule
        if pool is not None:
            options["pool"] = pool
        if priority is not None:
            options["priority"] = priority
        if execution_timeout is not None:
            options["execution_timeout"] = execution_timeout
        if retry_exponential_backoff is not None:
            options["retry_exponential_backoff"] = retry_exponential_backoff
        if max_active_tis_per_dagrun is not None:
            options["max_active_tis_per_dagrun"] = max_active_tis_per_dagrun
        if deferrable is not None:
            options["deferrable"] = deferrable
        if on_success is not None:
            options["on_success"] = on_success
        if on_failure is not None:
            options["on_failure"] = on_failure

        if options:
            self._task_defaults = self._normalize_step_options(options, init=True)
        return self

    def _normalize_step_options(self, options: Dict[str, Any], init: bool = False) -> Dict[str, Any]:
        """Normalize options shared by all step types."""
        merged = {
            "retries": 0,
            "retry_delay": 0,
            "continue_on_failure": False,
            "trigger_rule": "all_success",
            "pool": "default",
            "priority": 0,
            "execution_timeout": 0,
            "retry_exponential_backoff": 0.0,
            "max_active_tis_per_dagrun": None,
            "deferrable": False,
            "on_success": [],
            "on_failure": [],
        }
        if not init and self._task_defaults:
            merged.update(self._task_defaults)
        if options:
            if "max_retries" in options and "retries" not in options:
                merged["retries"] = options["max_retries"]
            merged.update(options)

        retries = merged.get("retries", 0)
        if isinstance(retries, bool):
            retries = int(retries)
        if not isinstance(retries, (int, float)):
            try:
                retries = int(str(retries).strip() or 0)
            except Exception:
                raise PythonRecipeError(f"invalid retries: {retries!r}")
        merged["retries"] = max(0, int(retries))

        retry_delay = merged.get("retry_delay", 0)
        if retry_delay is None:
            merged["retry_delay"] = 0
        elif isinstance(retry_delay, bool):
            merged["retry_delay"] = int(retry_delay)
        elif isinstance(retry_delay, (int, float)):
            merged["retry_delay"] = int(retry_delay)
        else:
            text = str(retry_delay).strip().lower()
            if not text:
                merged["retry_delay"] = 0
            else:
                merged["retry_delay"] = self._normalize_timeout(text)

        continue_on_failure = merged.get("continue_on_failure", False)
        if not isinstance(continue_on_failure, bool):
            normalized = str(continue_on_failure).strip().lower()
            merged["continue_on_failure"] = normalized in {"1", "true", "yes", "y", "on"}
        else:
            merged["continue_on_failure"] = bool(continue_on_failure)

        trigger_rule = str(merged.get("trigger_rule", "all_success")).strip().lower()
        if trigger_rule not in {
            "all_success",
            "all_done",
            "all_failed",
            "one_success",
            "one_failed",
            "none_failed",
            "none_failed_or_skipped",
        }:
            raise PythonRecipeError(f"invalid trigger_rule: {trigger_rule!r}")
        merged["trigger_rule"] = trigger_rule

        merged["pool"] = str(merged.get("pool", "default")).strip() or "default"

        priority = merged.get("priority", 0)
        if isinstance(priority, bool):
            priority = int(priority)
        if not isinstance(priority, (int, float)):
            try:
                priority = int(str(priority).strip() or 0)
            except Exception:
                priority = 0
        merged["priority"] = int(priority)

        execution_timeout = merged.get("execution_timeout", 0)
        if isinstance(execution_timeout, bool):
            merged["execution_timeout"] = int(execution_timeout)
        elif isinstance(execution_timeout, (int, float)):
            merged["execution_timeout"] = max(0, int(execution_timeout))
        else:
            text = str(execution_timeout).strip().lower()
            if not text:
                merged["execution_timeout"] = 0
            else:
                merged["execution_timeout"] = self._normalize_timeout(text)

        retry_exponential_backoff = merged.get("retry_exponential_backoff", 0.0)
        if isinstance(retry_exponential_backoff, bool):
            factor = 2.0 if retry_exponential_backoff else 0.0
        else:
            try:
                factor = float(str(retry_exponential_backoff).strip())
            except Exception:
                factor = 0.0
        if factor < 0:
            factor = 0.0
        merged["retry_exponential_backoff"] = factor

        max_active_tis_per_dagrun = merged.get("max_active_tis_per_dagrun")
        if max_active_tis_per_dagrun is None:
            merged["max_active_tis_per_dagrun"] = None
        elif isinstance(max_active_tis_per_dagrun, bool):
            merged["max_active_tis_per_dagrun"] = None if not max_active_tis_per_dagrun else 1
        else:
            try:
                parsed_max_active_tis = int(max_active_tis_per_dagrun)
            except Exception:
                parsed_max_active_tis = 1
            merged["max_active_tis_per_dagrun"] = max(1, parsed_max_active_tis)

        merged["deferrable"] = self._normalize_bool(merged.get("deferrable", False), default=False)

        merged["on_success"] = self._normalize_step_callbacks(merged.get("on_success"))
        merged["on_failure"] = self._normalize_step_callbacks(merged.get("on_failure"))

        return merged

    def _normalize_step_callbacks(self, value: Any) -> List[Any]:
        """Normalize callback specs shared by step and default options."""
        if value is None:
            return []
        if callable(value):
            return [value]
        if isinstance(value, (str, bytes, dict, ProviderStep)):
            return [value]
        if isinstance(value, (list, tuple, set)):
            callbacks: List[Any] = []
            for item in value:
                if item is None:
                    continue
                if callable(item) or isinstance(item, (str, bytes, dict, ProviderStep)):
                    callbacks.append(item)
            return callbacks
        return []

    def _next_step_id(self, step_id: Optional[str] = None) -> str:
        """Generate a stable step id."""
        if step_id is not None:
            if step_id in self._used_ids:
                raise PythonRecipeError(f"duplicate step id: {step_id}")
            self._used_ids.add(step_id)
            return step_id

        self._step_seq += 1
        new_id = f"step_{self._step_seq:03d}"
        while new_id in self._used_ids:
            self._step_seq += 1
            new_id = f"step_{self._step_seq:03d}"
        self._used_ids.add(new_id)
        return new_id

    def _normalize_timeout(self, timeout: Any) -> int:
        """Parse timeout-like values into seconds."""
        if timeout is None:
            return 0
        if isinstance(timeout, (int, float)):
            return int(timeout)
        if isinstance(timeout, str):
            text = timeout.strip().lower()
            if not text:
                raise PythonRecipeError("timeout cannot be empty")
            if text.endswith("h"):
                return int(text[:-1]) * 3600
            if text.endswith("m"):
                return int(text[:-1]) * 60
            if text.endswith("s"):
                return int(text[:-1])
            return int(text)
        raise PythonRecipeError(f"invalid timeout: {timeout!r}")

    def _normalize_bool(self, value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return bool(value)
        if value is None:
            return bool(default)
        text = str(value).strip().lower()
        if not text:
            return bool(default)
        return text in {"1", "true", "yes", "y", "on", "t"}

    def _normalize_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        if not text:
            return []
        return [item.strip() for item in text.split(",") if item.strip()]

    def _clean_session(self, value: str) -> str:
        return value[1:] if value.startswith("@") else value

    def _add_step(
        self,
        step: object,
        id: Optional[str] = None,
        depends_on: Any = None,
        step_options: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
    ) -> str:
        from .authoring_support import normalize_after

        resolved_id = self._next_step_id(id if id is not None else step_id)
        options = self._normalize_step_options(step_options or {})
        implicit_depends = normalize_after(depends_on)
        if implicit_depends is None and self._linear_contexts:
            current_linear = self._linear_contexts[-1]
            if current_linear.get("last") is not None:
                implicit_depends = [current_linear["last"]]
            elif current_linear.get("depends_on"):
                implicit_depends = list(current_linear["depends_on"])
        if implicit_depends is None and self.steps:
            implicit_depends = [self.steps[-1].id]
        deps: List[str] = []
        for dependency in implicit_depends or []:
            dep_id = str(dependency).strip()
            if not dep_id:
                continue
            if dep_id not in self._used_ids:
                raise PythonRecipeError(f"unknown dependency step id: {dep_id}")
            deps.append(dep_id)

        if isinstance(step, RecipeStepModel):
            self.steps.append(
                RecipeStep(
                    id=resolved_id,
                    step_model=step,
                    depends_on=deps,
                    retries=options["retries"],
                    retry_delay=options["retry_delay"],
                    continue_on_failure=options["continue_on_failure"],
                    trigger_rule=options["trigger_rule"],
                    pool=options["pool"],
                    priority=options["priority"],
                    execution_timeout=options["execution_timeout"],
                    retry_exponential_backoff=options["retry_exponential_backoff"],
                    max_active_tis_per_dagrun=options["max_active_tis_per_dagrun"],
                    deferrable=options["deferrable"],
                    on_success=options["on_success"],
                    on_failure=options["on_failure"],
                )
            )
            handle = wrap_step_handle(self, resolved_id)
            if self._linear_contexts:
                self._linear_contexts[-1]["last"] = handle
            return handle

        if isinstance(step, ProviderStep):
            step.id = resolved_id
            step.depends_on = deps
            step.retries = options["retries"]
            step.retry_delay = options["retry_delay"]
            step.continue_on_failure = options["continue_on_failure"]
            step.trigger_rule = options["trigger_rule"]
            step.pool = options["pool"]
            step.priority = options["priority"]
            step.execution_timeout = options["execution_timeout"]
            step.retry_exponential_backoff = options["retry_exponential_backoff"]
            step.max_active_tis_per_dagrun = options["max_active_tis_per_dagrun"]
            step.deferrable = options["deferrable"]
            step.on_success = options["on_success"]
            step.on_failure = options["on_failure"]
            self.steps.append(step)
            handle = wrap_step_handle(self, resolved_id)
            if self._linear_contexts:
                self._linear_contexts[-1]["last"] = handle
            return handle

        raise PythonRecipeError(f"unsupported step type: {type(step)!r}")

    def _step_by_id(self, step_id: str) -> RecipeStep:
        resolved = str(step_id).strip()
        for step in self.steps:
            if step.id == resolved:
                return step
        raise PythonRecipeError(f"unknown dependency step id: {resolved}")

    def link_step_dependencies(self, step_id: str, dependencies: Any) -> None:
        """Attach dependencies to an existing step after it has been created."""
        from .authoring_support import normalize_after

        step = self._step_by_id(step_id)
        for dependency in normalize_after(dependencies) or []:
            if dependency == step.id:
                raise PythonRecipeError(f"step cannot depend on itself: {step.id}")
            if dependency not in self._used_ids:
                raise PythonRecipeError(f"unknown dependency step id: {dependency}")
            if dependency not in step.depends_on:
                step.depends_on.append(dependency)

    def current_linear_dependency(self) -> Any:
        if not self._linear_contexts:
            return None
        return self._linear_contexts[-1].get("last")

    def current_linear_seed_dependencies(self) -> list[str]:
        """Return the current linear block's seed dependencies, if any."""
        if not self._linear_contexts:
            return []
        current = self._linear_contexts[-1]
        if current.get("last") is not None:
            return [str(current["last"]).strip()]
        return [str(item).strip() for item in (current.get("depends_on") or []) if str(item).strip()]

    def last(self):
        """Return a handle to the most recently added step."""
        if not self.steps:
            raise PythonRecipeError("recipe has no steps yet")
        return wrap_step_handle(self, self.steps[-1].id)

    def last_step(self):
        """Alias for :meth:`last`."""
        return self.last()

    def remember_session(
        self,
        name: str,
        *,
        open_step_id: Optional[str],
        host_ref: Optional[str],
        cwd: Optional[str],
        env: Optional[Dict[str, Any]],
    ) -> None:
        """Persist reusable session metadata by session name."""
        session_name = self._clean_session(str(name))
        if not session_name:
            return
        self._session_registry[session_name] = {
            "open_step_id": open_step_id,
            "host_ref": host_ref,
            "cwd": cwd,
            "env": dict(env or {}),
        }

    def lookup_session(self, name: str) -> Optional[dict[str, Any]]:
        """Look up previously remembered session metadata."""
        return self._session_registry.get(self._clean_session(str(name)))

    def _host_alias_for(self, host: Host) -> str:
        cached = self._resource_host_aliases.get(host)
        if cached:
            return cached

        base = re.sub(r"[^A-Za-z0-9_]+", "_", (host.name or host.spec).strip()).strip("_") or "host"
        alias = base
        suffix = 1
        while alias in self.hosts and self.hosts[alias] != host.spec:
            suffix += 1
            alias = f"{base}_{suffix}"
        self.hosts[alias] = host.spec
        self._resource_host_aliases[host] = alias
        return alias

    def _storage_alias_for(self, storage: Storage) -> str:
        cache_key = id(storage)
        cached = self._resource_storage_aliases.get(cache_key)
        if cached:
            return cached

        raw = storage.spec
        if isinstance(raw, RuntimeStorage):
            base_text = raw.name or raw.type.value
            stored_value: Any = raw
        else:
            base_text = str(raw)
            stored_value = raw
        base = re.sub(r"[^A-Za-z0-9_]+", "_", (storage.name or base_text).strip()).strip("_") or "storage"
        alias = base
        suffix = 1
        while alias in self.storages and self.storages[alias] != stored_value:
            suffix += 1
            alias = f"{base}_{suffix}"
        self.storages[alias] = stored_value
        self._resource_storage_aliases[cache_key] = alias
        return alias

    def resolve_host(self, host: Any) -> str:
        if isinstance(host, Host):
            return self._host_alias_for(host)
        return str(host).strip()

    def resolve_storage(self, storage: Any) -> str:
        if isinstance(storage, StoragePath):
            storage = storage.storage
        if isinstance(storage, Storage):
            return self._storage_alias_for(storage)
        return self._clean_session(str(storage).strip())

    def resolve_endpoint(self, value: Any) -> str:
        if isinstance(value, HostPath):
            return f"@{self._host_alias_for(value.host)}:{value.path}"
        if isinstance(value, StoragePath):
            return f"@{self._storage_alias_for(value.storage)}:{value.path}"
        if isinstance(value, os.PathLike):
            return os.fspath(value)
        return str(value)

    def copy(self, source: Any, destination: Any, **kwargs: Any) -> str:
        return type(self).transfer(
            self,
            self.resolve_endpoint(source),
            self.resolve_endpoint(destination),
            operation="copy",
            **kwargs,
        )

    def move(self, source: Any, destination: Any, **kwargs: Any) -> str:
        return type(self).transfer(
            self,
            self.resolve_endpoint(source),
            self.resolve_endpoint(destination),
            operation="move",
            **kwargs,
        )

    def sync(self, source: Any, destination: Any, **kwargs: Any) -> str:
        return type(self).transfer(
            self,
            self.resolve_endpoint(source),
            self.resolve_endpoint(destination),
            operation="sync",
            **kwargs,
        )

    def to_recipe_model(self) -> RecipeModel:
        """Convert this recipe object into the normalized runtime model."""
        return RecipeModel(
            name=self.name,
            variables=dict(self.variables),
            hosts=dict(self.hosts.items()),
            storages=dict(self.storages.items()),
            steps=[item.to_step_model() for item in self.steps],
        )

    def step_count(self) -> int:
        return len(self.steps)


class RecipeSpec(
    RecipeSpecCore,
    RecipeProviderMixin,
    RecipeProviderMiscMixin,
    RecipeProviderConditionMixin,
    RecipeProviderNetworkMixin,
    RecipeProviderTransferMixin,
    RecipeStorageMixin,
    RecipeSessionMixin,
    RecipeControlMixin,
):
    """Complete recipe builder combining provider, storage, and control helpers."""


__all__ = ["RecipeSpec", "RecipeSpecCore", "get_active_recipe"]
