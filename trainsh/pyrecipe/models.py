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


@dataclass(frozen=True)
class Storage:
    """Explicit storage resource used by the Python recipe API."""

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
