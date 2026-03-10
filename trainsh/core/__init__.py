"""Lazy exports for scheduling/runtime core helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple


_EXPORTS: Dict[str, Tuple[str, str]] = {
    "DagExecutor": (".dag_executor", "DagExecutor"),
    "DagExecutionResult": (".dag_executor", "DagExecutionResult"),
    "DagProcessor": (".dag_processor", "DagProcessor"),
    "DagSchedule": (".dag_processor", "DagSchedule"),
    "DagRunRecord": (".scheduler", "DagRunRecord"),
    "DagRunState": (".scheduler", "DagRunState"),
    "DagScheduler": (".scheduler", "DagScheduler"),
    "ParsedDag": (".dag_processor", "ParsedDag"),
    "dag_id_from_path": (".dag_processor", "dag_id_from_path"),
    "parse_schedule": (".dag_processor", "parse_schedule"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
