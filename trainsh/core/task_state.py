"""Task/Dag state helpers inspired by Airflow state enums.

This module keeps the migration surface small while adding the extra status
values needed for dependency checks, triggerer-style deferral, and retry states.
"""

from __future__ import annotations

from typing import Final, FrozenSet


class TaskInstanceState:
    """Compact task instance state container."""

    NONE = None
    SCHEDULED: Final[str] = "scheduled"
    QUEUED: Final[str] = "queued"
    RUNNING: Final[str] = "running"
    SUCCESS: Final[str] = "success"
    RESTARTING: Final[str] = "restarting"
    FAILED: Final[str] = "failed"
    UP_FOR_RETRY: Final[str] = "up_for_retry"
    UP_FOR_RESCHEDULE: Final[str] = "up_for_reschedule"
    UPSTREAM_FAILED: Final[str] = "upstream_failed"
    SKIPPED: Final[str] = "skipped"
    REMOVED: Final[str] = "removed"
    DEFERRED: Final[str] = "deferred"


FINISHED_STATES: Final[FrozenSet[str]] = frozenset(
    {
        TaskInstanceState.SUCCESS,
        TaskInstanceState.FAILED,
        TaskInstanceState.SKIPPED,
        TaskInstanceState.UPSTREAM_FAILED,
        TaskInstanceState.REMOVED,
    }
)


UNFINISHED_STATES: Final[FrozenSet[object]] = frozenset(
    {
        TaskInstanceState.NONE,
        TaskInstanceState.SCHEDULED,
        TaskInstanceState.QUEUED,
        TaskInstanceState.RUNNING,
        TaskInstanceState.RESTARTING,
        TaskInstanceState.UP_FOR_RETRY,
        TaskInstanceState.UP_FOR_RESCHEDULE,
        TaskInstanceState.DEFERRED,
    }
)


SUCCESS_STATES: Final[FrozenSet[str]] = frozenset(
    {
        TaskInstanceState.SUCCESS,
        TaskInstanceState.SKIPPED,
    }
)


FAILED_STATES: Final[FrozenSet[str]] = frozenset(
    {
        TaskInstanceState.FAILED,
        TaskInstanceState.UPSTREAM_FAILED,
        TaskInstanceState.REMOVED,
    }
)


RUNNING_STATES: Final[FrozenSet[str]] = frozenset(
    {
        TaskInstanceState.RUNNING,
        TaskInstanceState.UP_FOR_RETRY,
        TaskInstanceState.UP_FOR_RESCHEDULE,
        TaskInstanceState.DEFERRED,
        TaskInstanceState.QUEUED,
    }
)


RETRY_STATES: Final[FrozenSet[str]] = frozenset(
    {
        TaskInstanceState.UP_FOR_RETRY,
        TaskInstanceState.UP_FOR_RESCHEDULE,
    }
)


def is_terminal(state: object) -> bool:
    """Return whether a task state is terminal."""

    return state in FINISHED_STATES


def is_unfinished(state: object) -> bool:
    """Return whether a task state is unfinished or can still run logic."""

    return state in UNFINISHED_STATES


def normalize_state(value: object) -> object:
    """Normalize empty/whitespace states to canonical values."""

    if value is None:
        return TaskInstanceState.NONE
    text = str(value).strip().lower()
    if not text:
        return TaskInstanceState.NONE
    return text

