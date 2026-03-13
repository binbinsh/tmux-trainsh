"""Scheduler facade for the DSL executor."""

from __future__ import annotations

from .executor_dependencies import ExecutorDependencyMixin
from .executor_steps import ExecutorStepRuntimeMixin


class ExecutorSchedulingMixin(ExecutorDependencyMixin, ExecutorStepRuntimeMixin):
    pass
