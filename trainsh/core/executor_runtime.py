"""Shared runtime dataclasses for the DSL executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .recipe_models import RecipeModel


@dataclass
class WindowInfo:
    """Tracks a remote tmux session."""

    name: str
    host: str
    remote_session: Optional[str] = None


@dataclass
class ExecutionContext:
    """Runtime context for recipe execution."""

    recipe: RecipeModel
    variables: Dict[str, str] = field(default_factory=dict)
    windows: Dict[str, WindowInfo] = field(default_factory=dict)
    exec_id: str = ""
    job_id: str = ""
    next_window_index: int = 0
    start_time: Optional[datetime] = None
    log_callback: Optional[Callable[[str], None]] = None


@dataclass
class _StepNode:
    """Runtime step node used for dependency scheduling."""

    step_num: int
    step_id: str
    step: object
    depends_on: List[str]
    retries: int = 0
    retry_delay: int = 0
    continue_on_failure: bool = False
    trigger_rule: str = "all_success"
    pool: str = "default"
    priority: int = 0
    execution_timeout: int = 0
    retry_exponential_backoff: float = 0.0
    on_success: list = field(default_factory=list)
    on_failure: list = field(default_factory=list)
    max_active_tis_per_dagrun: Optional[int] = None
    deferrable: bool = False


@dataclass
class _DeferredEvent:
    task_id: str
    started_at: float
