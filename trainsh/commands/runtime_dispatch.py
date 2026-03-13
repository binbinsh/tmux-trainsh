"""Helpers for routing manual recipe execution through the DAG stack."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Sequence

from ..core import DagExecutor, DagExecutionResult, DagProcessor


def load_recipe_dag(recipe_path: str):
    """Load one recipe file into the shared ParsedDag model."""
    path = Path(recipe_path).expanduser().resolve()
    return DagProcessor().process_dag_file(path)


def run_recipe_via_dag(
    recipe_path: str,
    *,
    job_id: Optional[str] = None,
    run_type: str = "manual",
    host_overrides: Optional[Dict[str, str]] = None,
    var_overrides: Optional[Dict[str, str]] = None,
    resume: bool = False,
    initial_session_index: int = 0,
    executor_name: Optional[str] = None,
    executor_kwargs: Optional[Dict[str, object]] = None,
    callbacks: Optional[Sequence[str]] = None,
    callback_sinks: Optional[Sequence] = None,
    log_callback=None,
) -> DagExecutionResult:
    """Execute one recipe by passing it through the DAG discovery/executor path."""
    dag = load_recipe_dag(recipe_path)
    executor = DagExecutor(
        executor_name=executor_name,
        executor_kwargs=executor_kwargs,
        callbacks=callbacks,
        callback_sinks=callback_sinks,
        prefer_runtime_options=executor_name is not None or bool(executor_kwargs),
        log_callback=log_callback,
    )
    return executor.run(
        dag,
        run_id=job_id,
        run_type=run_type,
        host_overrides=host_overrides,
        var_overrides=var_overrides,
        resume=resume,
        initial_session_index=initial_session_index,
    )


__all__ = ["load_recipe_dag", "run_recipe_via_dag"]
