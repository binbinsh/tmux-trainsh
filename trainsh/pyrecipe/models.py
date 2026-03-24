"""Shared data structures for the Python recipe DSL."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.models import Storage as RuntimeStorage
from ..core.recipe_models import RecipeStepModel, StepType


class PythonRecipeError(ValueError):
    """Raised when a python recipe definition is invalid."""


@dataclass(frozen=True)
class StoragePath:
    """Typed storage path bound to one storage resource."""

    storage: "Storage"
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", os.fspath(self.path))


@dataclass(frozen=True)
class HostPath:
    """Typed remote path bound to one host resource."""

    host: "Host"
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", os.fspath(self.path))


@dataclass(frozen=True)
class Host:
    """Explicit host resource used by the Python recipe API."""

    spec: str
    name: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "spec", str(self.spec).strip())
        if not self.spec:
            raise PythonRecipeError("host spec cannot be empty")

    def path(self, value: os.PathLike[str] | str) -> HostPath:
        return HostPath(self, os.fspath(value))

    def tmux(self, name: str = "main", **kwargs: Any):
        """Open or reuse a tmux-backed context on this host for the active recipe."""
        from .base import get_active_recipe

        recipe = get_active_recipe()
        if recipe is None:
            raise PythonRecipeError("no active Recipe is available for host.tmux(...)")
        if "close" not in kwargs:
            kwargs["close"] = True
        return recipe._tmux_ref(name, host=self, **kwargs)

    def vllm(self, model: str, **kwargs: Any):
        """Start or describe one vLLM service bound to this host."""
        return self._active_recipe().vllm.serve(self, model, **kwargs)

    def _active_recipe(self):
        from .base import get_active_recipe

        recipe = get_active_recipe()
        if recipe is None:
            raise PythonRecipeError("no active Recipe is available for host lifecycle helpers")
        return recipe

    def _provider_namespace(self):
        recipe = self._active_recipe()
        spec = str(self.spec).strip().lower()
        if spec.startswith("runpod:"):
            return recipe.runpod
        alias_key = str(self.name or self.spec).strip()
        resolved = str(recipe.hosts.get(alias_key, "")).strip().lower()
        if resolved.startswith("runpod:"):
            return recipe.runpod
        return recipe.vast

    def _vast_target(self) -> str:
        if self.name:
            return str(self.name).strip()
        return self.spec

    def pick(self, **kwargs: Any) -> str:
        """Pick or create a provider-managed instance for this host alias."""
        return self._provider_namespace().pick(host=self, **kwargs)

    def start(self, **kwargs: Any) -> str:
        """Start the provider-managed instance bound to this host."""
        return self._provider_namespace().start(self, **kwargs)

    def stop(self, **kwargs: Any) -> str:
        """Stop the provider-managed instance bound to this host."""
        return self._provider_namespace().stop(self, **kwargs)

    def wait_ready(self, **kwargs: Any) -> str:
        """Wait for the provider-managed instance bound to this host to become ready."""
        return self._provider_namespace().wait_ready(self, **kwargs)

    def cost(self, **kwargs: Any) -> str:
        """Report cost for the provider-managed instance bound to this host."""
        return self._provider_namespace().cost(self, **kwargs)


@dataclass(frozen=True)
class Storage:
    """Explicit storage resource used by the Python recipe API.

    Typical specs:
    - ``Storage("hf:team/checkpoints")``
    - ``Storage("r2:artifacts")``
    - ``Storage({"type": "hf", "config": {"bucket": "team/checkpoints"}})``
    """

    spec: Any
    name: Optional[str] = None

    def __post_init__(self) -> None:
        value = self.spec
        if isinstance(value, RuntimeStorage):
            normalized = value
        elif isinstance(value, dict):
            normalized = RuntimeStorage.from_dict(value)
        else:
            normalized = str(value).strip()
            if not normalized:
                raise PythonRecipeError("storage spec cannot be empty")
        object.__setattr__(self, "spec", normalized)

    def path(self, value: os.PathLike[str] | str) -> StoragePath:
        return StoragePath(self, os.fspath(value))


@dataclass(frozen=True)
class VastHost(Host):
    """Typed Vast.ai host resource."""

    instance_id: str = field(default="")

    def __init__(self, instance_id: Any, *, name: Optional[str] = None):
        resolved = str(instance_id).strip()
        if not resolved:
            raise PythonRecipeError("vast instance id cannot be empty")
        object.__setattr__(self, "instance_id", resolved)
        object.__setattr__(self, "spec", f"vast:{resolved}")
        object.__setattr__(self, "name", name)


@dataclass(frozen=True)
class RunpodHost(Host):
    """Typed RunPod host resource."""

    pod_id: str = field(default="")

    def __init__(self, pod_id: Any, *, name: Optional[str] = None):
        resolved = str(pod_id).strip()
        if not resolved:
            raise PythonRecipeError("runpod pod id cannot be empty")
        object.__setattr__(self, "pod_id", resolved)
        object.__setattr__(self, "spec", f"runpod:{resolved}")
        object.__setattr__(self, "name", name)


local = Host("local", name="local")


@dataclass
class RecipeStep:
    """Single Python-defined step before execution."""

    id: str
    step_model: RecipeStepModel
    depends_on: List[str] = field(default_factory=list)
    retries: int = 0
    retry_delay: Any = 0
    continue_on_failure: bool = False
    trigger_rule: str = "all_success"
    pool: str = "default"
    priority: int = 0
    execution_timeout: int = 0
    retry_exponential_backoff: float = 0.0
    max_active_tis_per_dagrun: Optional[int] = None
    deferrable: bool = False
    on_success: list = field(default_factory=list)
    on_failure: list = field(default_factory=list)

    @property
    def raw(self) -> str:
        return self.step_model.raw

    @property
    def type(self) -> StepType:
        return self.step_model.type

    @property
    def command(self) -> str:
        return self.step_model.command

    @property
    def args(self) -> List[str]:
        return self.step_model.args

    @property
    def host(self) -> str:
        return self.step_model.host

    @property
    def commands(self) -> str:
        return self.step_model.commands

    @property
    def background(self) -> bool:
        return self.step_model.background

    @property
    def timeout(self) -> int:
        return self.step_model.timeout

    @property
    def capture_var(self) -> str:
        return self.step_model.capture_var

    @property
    def capture_path(self) -> str:
        return self.step_model.capture_path

    @property
    def source(self) -> str:
        return self.step_model.source

    @property
    def dest(self) -> str:
        return self.step_model.dest

    @property
    def target(self) -> str:
        return self.step_model.target

    @property
    def pattern(self) -> str:
        return self.step_model.pattern

    @property
    def condition(self) -> str:
        return self.step_model.condition

    def to_step_model(self) -> RecipeStepModel:
        return self.step_model


@dataclass
class ProviderStep:
    """Single provider-backed step for the Python recipe API."""

    provider: str
    operation: str
    params: Dict[str, Any]
    id: str
    depends_on: List[str] = field(default_factory=list)
    retries: int = 0
    retry_delay: Any = 0
    continue_on_failure: bool = False
    trigger_rule: str = "all_success"
    pool: str = "default"
    priority: int = 0
    execution_timeout: int = 0
    retry_exponential_backoff: float = 0.0
    max_active_tis_per_dagrun: Optional[int] = None
    deferrable: bool = False
    on_success: list = field(default_factory=list)
    on_failure: list = field(default_factory=list)

    @property
    def raw(self) -> str:
        return f"provider {self.provider}.{self.operation} {json.dumps(self.params, ensure_ascii=False)}"

    @property
    def type(self):
        return StepType.CONTROL

    @property
    def command(self) -> str:
        return "provider"

    @property
    def args(self) -> List[str]:
        return [self.provider, self.operation]

    def to_step_model(self) -> RecipeStepModel:
        return RecipeStepModel(
            type=StepType.CONTROL,
            line_num=0,
            raw=self.raw,
            command="provider",
            args=[self.provider, self.operation],
        )
