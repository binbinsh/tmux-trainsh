"""Core Python recipe model and builder helpers.

This module keeps the API compact and delegates feature-specific helpers to mixins.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..core.recipe_models import RecipeModel, RecipeStepModel
from ..core.models import Storage

from .control_steps import RecipeControlMixin
from .models import PythonRecipeError, ProviderStep, RecipeStep
from .provider_steps import RecipeProviderMixin
from .provider_misc_steps import RecipeProviderMiscMixin
from .provider_condition_steps import RecipeProviderConditionMixin
from .provider_transfer_steps import RecipeProviderTransferMixin
from .session_steps import RecipeSessionMixin
from .storage_steps import RecipeStorageMixin
from .provider_sqlite_steps import RecipeProviderSQLiteMixin
from .provider_network_steps import RecipeProviderNetworkMixin


class RecipeSpecCore:
    """Shared recipe state and step registration helpers."""

    def __init__(
        self,
        name: str,
        *,
        executor: str = "sequential",
        executor_kwargs: Optional[Dict[str, Any]] = None,
        callbacks: Optional[Iterable[str]] = None,
    ):
        self.name = (name or "recipe").strip()
        if not self.name:
            raise PythonRecipeError("recipe name cannot be empty")

        self.hosts: Dict[str, str] = {}
        self.storages: Dict[str, Any] = {}
        self.variables: Dict[str, str] = {}
        self.steps: List[RecipeStep] = []
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
        self.callbacks = list(callbacks) if callbacks is not None else ["console", "sqlite"]

        self._step_seq = 0
        self._used_ids = set()
        self._task_defaults: Dict[str, Any] = {}

    def var(self, name: str, value: Any) -> None:
        """Define a recipe variable."""
        if not name:
            raise PythonRecipeError("variable name cannot be empty")
        self.variables[name] = str(value)

    def host(self, name: str, spec: Any) -> None:
        """Define a host alias."""
        if not name:
            raise PythonRecipeError("host name cannot be empty")
        self.hosts[name] = str(spec)

    def storage(self, name: str, spec: Any) -> None:
        """Define a storage alias."""
        if not name:
            raise PythonRecipeError("storage name cannot be empty")
        if isinstance(spec, Storage):
            self.storages[name] = spec
        elif isinstance(spec, dict):
            self.storages[name] = Storage.from_dict(spec)
        else:
            self.storages[name] = str(spec)

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
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
    ) -> str:
        resolved_id = self._next_step_id(id if id is not None else step_id)
        options = self._normalize_step_options(step_options or {})
        deps: List[str] = []
        for dependency in depends_on or []:
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
            return resolved_id

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
            return resolved_id

        raise PythonRecipeError(f"unsupported step type: {type(step)!r}")

    def to_recipe_model(self) -> RecipeModel:
        """Convert this recipe object into the normalized runtime model."""
        return RecipeModel(
            name=self.name,
            variables=dict(self.variables),
            hosts=dict(self.hosts),
            storages=dict(self.storages),
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
    RecipeProviderSQLiteMixin,
    RecipeProviderTransferMixin,
    RecipeStorageMixin,
    RecipeSessionMixin,
    RecipeControlMixin,
):
    """Complete recipe builder combining provider, storage, and control helpers."""


__all__ = ["RecipeSpec", "RecipeSpecCore"]
