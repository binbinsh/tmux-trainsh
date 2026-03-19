"""Executor bridge for DAG runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from .executor_main import run_recipe
from .dag_processor import ParsedDag


@dataclass
class DagExecutionResult:
    dag_id: str
    run_id: str
    recipe_path: str
    state: str
    success: bool
    started_at: datetime
    ended_at: datetime
    message: str
    error: Optional[str] = None
    output: Optional[Any] = None


class DagExecutor:
    """Run one ParsedDag through existing recipe executor."""

    def __init__(
        self,
        *,
        executor_name: Optional[str] = "thread_pool",
        executor_kwargs: Optional[Dict[str, Any]] = None,
        callbacks: Optional[Sequence[str]] = None,
        callback_sinks: Optional[Sequence[Any]] = None,
        default_callbacks: Optional[Sequence[str]] = None,
        prefer_runtime_options: bool = False,
        log_callback=None,
    ):
        self.executor_name = executor_name
        self.executor_kwargs = dict(executor_kwargs or {})
        self.callbacks = list(callbacks or [])
        self.callback_sinks = list(callback_sinks or [])
        self.default_callbacks = list(default_callbacks or ["console", "jsonl"])
        self.prefer_runtime_options = bool(prefer_runtime_options)
        self.log_callback = log_callback

    def run(
        self,
        dag: ParsedDag,
        *,
        run_id: Optional[str] = None,
        run_type: str = "manual",
        host_overrides: Optional[Dict[str, str]] = None,
        var_overrides: Optional[Dict[str, str]] = None,
        resume: bool = False,
        initial_session_index: int = 0,
    ) -> DagExecutionResult:
        run_id = run_id or uuid4().hex
        run_type = str(run_type or "manual").strip().lower() or "manual"
        started_at = datetime.now(timezone.utc)
        callbacks = self._select_callbacks(dag.callbacks)

        try:
            selected_executor = self._select_executor(dag)
            selected_kwargs = self._merge_kwargs(dag.executor_kwargs)
            success = run_recipe(
                str(dag.path),
                job_id=run_id,
                host_overrides=host_overrides,
                var_overrides=var_overrides,
                resume=resume,
                initial_session_index=initial_session_index,
                executor_name=selected_executor,
                executor_kwargs=selected_kwargs,
                callbacks=callbacks,
                callback_sinks=self.callback_sinks,
                log_callback=self.log_callback,
                run_type=run_type,
            )
            ended_at = datetime.now(timezone.utc)
            if success:
                return DagExecutionResult(
                    dag_id=dag.dag_id,
                    run_id=run_id,
                    recipe_path=str(dag.path),
                    state="success",
                    success=True,
                    started_at=started_at,
                    ended_at=ended_at,
                    message="run completed",
                    output={"schedule": dag.schedule},
                )
            return DagExecutionResult(
                dag_id=dag.dag_id,
                run_id=run_id,
                recipe_path=str(dag.path),
                state="failed",
                success=False,
                started_at=started_at,
                ended_at=ended_at,
                message="run failed",
                output={"schedule": dag.schedule},
            )
        except Exception as exc:  # noqa: BLE001
            ended_at = datetime.now(timezone.utc)
            return DagExecutionResult(
                dag_id=dag.dag_id,
                run_id=run_id,
                recipe_path=str(dag.path),
                state="error",
                success=False,
                started_at=started_at,
                ended_at=ended_at,
                message="executor raised exception",
                error=str(exc),
                output=None,
            )

    def _select_callbacks(self, dag_callbacks: Optional[Sequence[str]]) -> List[str]:
        callback_names: List[str] = []
        callback_names.extend(self.callbacks)
        if dag_callbacks:
            callback_names.extend(dag_callbacks)
        if not callback_names:
            callback_names.extend(self.default_callbacks)
        normalized = []
        for name in callback_names:
            if not name:
                continue
            if isinstance(name, str):
                normalized.append(name.strip())
        # unique preserve order
        dedup = []
        for name in normalized:
            if name not in dedup:
                dedup.append(name)
        return dedup

    def _select_executor(self, dag: ParsedDag) -> str:
        if self.prefer_runtime_options and self.executor_name:
            return self.executor_name
        return dag.executor or self.executor_name or "sequential"

    def _merge_kwargs(self, dag_executor_kwargs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if self.prefer_runtime_options:
            merged = dict(dag_executor_kwargs or {})
            merged.update(self.executor_kwargs)
            return merged

        merged = dict(self.executor_kwargs)
        if dag_executor_kwargs:
            merged.update(dag_executor_kwargs)
        return merged


__all__ = ["DagExecutor", "DagExecutionResult"]
