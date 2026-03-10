# Runtime executor aliasing and compatibility shims.

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, Dict


def normalize_executor_name(name: str) -> str:
    """Normalize executor names for compatibility checks."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _coerce_max_workers(kwargs: Dict[str, Any], default: int = 4) -> int:
    """Read common concurrency knobs from executor kwargs."""
    parallelism = kwargs.get("parallelism")
    raw = kwargs.get(
        "max_workers",
        kwargs.get(
            "workers",
            kwargs.get(
                "concurrency",
                kwargs.get(
                    "worker_processes",
                    kwargs.get("worker_count", default),
                ),
            ),
        ),
    )
    if parallelism is not None:
        raw = parallelism
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return max(1, int(default))


_SEQUENTIAL_EXECUTOR_ALIASES = {
    "sequential",
    "sequentialexecutor",
    "sequencialexecutor",
    "synchronous",
    "sync",
    "inline",
    "serial",
    "mock",
    "mockexecutor",
}
_THREAD_EXECUTOR_ALIASES = {
    "thread_pool",
    "thread_pool_executor",
    "threadpool",
    "threadpoolexecutor",
    "threadexecutor",
    "threadpoolexecuter",
    "thread pool",
    "thread pool executor",
    "executor",
    "local",
    "localexecutor",
    "localsexecutor",
    "localthreadexecutor",
    "airflow",
    "airflowexecutor",
    "airflow executor",
    "dagscheduler",
    "dagschedulerexecutor",
    "dagschedulerexecutor",
    "default",
    "defaultexecutor",
    "executorairflow",
    "airflowexecutor",
    "airflowexecutors",
}
_PROCESS_EXECUTOR_ALIASES = {
    "process_pool",
    "process_pool_executor",
    "multiprocessing",
    "processpool",
    "processpoolexecutor",
    "processexecutor",
    "process pool",
    "process pool executor",
    "process",
    "dagprocess",
    "dagprocessexecutor",
    "dag process executor",
}
_CELERY_EXECUTOR_ALIASES = {
    "celery",
    "celeryexecutor",
    "celery executor",
    "celeryexecutor",
}
_DASK_EXECUTOR_ALIASES = {
    "dask",
    "daskexecutor",
    "dask executor",
    "dask_executor",
}
_KUBERNETES_EXECUTOR_ALIASES = {
    "k8s",
    "kubernetes",
    "kubernetesexecutor",
    "kubernetes executor",
    "kubernetes_executor",
    "kubeexecutor",
    "kubernetesexecutors",
}
_DEBUG_EXECUTOR_ALIASES = {
    "debug",
    "debugexecutor",
    "dryrun",
    "null",
    "noexecutor",
    "no executor",
    "noop",
}

SEQUENTIAL_EXECUTOR_ALIASES = frozenset(normalize_executor_name(v) for v in _SEQUENTIAL_EXECUTOR_ALIASES)
THREAD_EXECUTOR_ALIASES = frozenset(normalize_executor_name(v) for v in _THREAD_EXECUTOR_ALIASES)
PROCESS_EXECUTOR_ALIASES = frozenset(normalize_executor_name(v) for v in _PROCESS_EXECUTOR_ALIASES)
CELERY_EXECUTOR_ALIASES = frozenset(normalize_executor_name(v) for v in _CELERY_EXECUTOR_ALIASES)
DASK_EXECUTOR_ALIASES = frozenset(normalize_executor_name(v) for v in _DASK_EXECUTOR_ALIASES)
KUBERNETES_EXECUTOR_ALIASES = frozenset(normalize_executor_name(v) for v in _KUBERNETES_EXECUTOR_ALIASES)
DEBUG_EXECUTOR_ALIASES = frozenset(normalize_executor_name(v) for v in _DEBUG_EXECUTOR_ALIASES)
PARALLEL_EXECUTOR_ALIASES = frozenset(
    {
        *THREAD_EXECUTOR_ALIASES,
        *PROCESS_EXECUTOR_ALIASES,
        *CELERY_EXECUTOR_ALIASES,
        *DASK_EXECUTOR_ALIASES,
    }
)


class ExecutionExecutor:
    """Base class for runtime executors."""

    name = "base"

    def execute(self, fn: Callable[[], bool]) -> bool:
        raise NotImplementedError(f"{self.__class__.__name__} must implement execute()")


class SequentialExecutor(ExecutionExecutor):
    """Run one execution function sequentially (default)."""

    name = "sequential"

    def execute(self, fn: Callable[[], bool]) -> bool:
        return bool(fn())


class ThreadPoolExecutor(ExecutionExecutor):
    """Run execution function inside a thread pool."""

    name = "thread_pool"

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def execute(self, fn: Callable[[], bool]) -> bool:
        if self.max_workers <= 1:
            return bool(fn())

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future = pool.submit(fn)
            return bool(future.result())


class ProcessPoolExecutor(ExecutionExecutor):
    """Compatibility shim for Airflow-like ProcessPool-like executors."""

    name = "process_pool"

    def __init__(self, max_workers: int = 4):
        self.max_workers = max(1, int(max_workers))

    def execute(self, fn: Callable[[], bool]) -> bool:
        if self.max_workers <= 1:
            return bool(fn())
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future = pool.submit(fn)
            return bool(future.result())


class LocalExecutor(ThreadPoolExecutor):
    """Compatibility alias for legacy Airflow 'LocalExecutor' semantics."""

    name = "local"


class DaskExecutor(ExecutionExecutor):
    """Compatibility alias for Dask-style executors."""

    name = "dask"

    def __init__(self, max_workers: int = 4):
        self.max_workers = max(1, int(max_workers))

    def execute(self, fn: Callable[[], bool]) -> bool:
        if self.max_workers <= 1:
            return bool(fn())
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future = pool.submit(fn)
            return bool(future.result())


class CeleryExecutor(ProcessPoolExecutor):
    """Compatibility alias for Airflow 'CeleryExecutor'."""

    name = "celery"


class AirflowExecutor(ThreadPoolExecutor):
    """Compatibility alias for legacy Airflow local/thread executors."""

    name = "airflow"


class NoopExecutor(ExecutionExecutor):
    """Compatibility alias for no-op / debug-run execution."""

    name = "noop"

    def execute(self, fn: Callable[[], bool]) -> bool:
        return bool(fn())


class DebugExecutor(ExecutionExecutor):
    """Debug-like executor (sequential)."""

    name = "debug"

    def execute(self, fn: Callable[[], bool]) -> bool:
        return bool(fn())


def get_executor(name: str, **kwargs: Any) -> ExecutionExecutor:
    """Resolve executor implementation by name."""
    lower = normalize_executor_name(name or "sequential")
    max_workers = _coerce_max_workers(kwargs)

    if lower in SEQUENTIAL_EXECUTOR_ALIASES:
        return SequentialExecutor()
    if lower in DEBUG_EXECUTOR_ALIASES:
        return DebugExecutor()
    if lower in THREAD_EXECUTOR_ALIASES:
        return AirflowExecutor(max_workers=max_workers)
    if lower in CELERY_EXECUTOR_ALIASES:
        return CeleryExecutor(max_workers=max_workers)
    if lower in DASK_EXECUTOR_ALIASES:
        return DaskExecutor(max_workers=max_workers)
    if lower in PROCESS_EXECUTOR_ALIASES:
        return ProcessPoolExecutor(max_workers=max_workers)
    if lower in KUBERNETES_EXECUTOR_ALIASES:
        raise ValueError("unsupported executor: kubernetes (not migrated in this runtime)")
    raise ValueError(f"unknown executor: {name}")
