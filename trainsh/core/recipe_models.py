"""Shared runtime recipe models used by Python and DSL entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class StepType(Enum):
    """Type of executable recipe step."""

    CONTROL = "control"
    EXECUTE = "execute"
    TRANSFER = "transfer"
    WAIT = "wait"


@dataclass
class RecipeStepModel:
    """Normalized runtime step model."""

    type: StepType
    line_num: int
    raw: str
    command: str = ""
    args: List[str] = field(default_factory=list)
    host: str = ""
    commands: str = ""
    background: bool = False
    timeout: int = 0
    source: str = ""
    dest: str = ""
    delete: bool = False
    operation: str = "copy"
    exclude: List[str] = field(default_factory=list)
    target: str = ""
    pattern: str = ""
    condition: str = ""


@dataclass
class RecipeModel:
    """Normalized runtime recipe model."""

    name: str = ""
    variables: Dict[str, str] = field(default_factory=dict)
    hosts: Dict[str, str] = field(default_factory=dict)
    storages: Dict[str, Any] = field(default_factory=dict)
    steps: List[RecipeStepModel] = field(default_factory=list)


__all__ = ["RecipeModel", "RecipeStepModel", "StepType"]
