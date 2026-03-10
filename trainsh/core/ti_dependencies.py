# Lightweight TaskInstance dependency evaluator inspired by Airflow `ti_deps`.

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from .task_state import (
    FAILED_STATES,
    FINISHED_STATES,
    TaskInstanceState,
    is_unfinished,
)


@dataclass(frozen=True)
class TIDepStatus:
    """Dependency status for one evaluator check."""

    dep_name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class DepDecision:
    """Evaluation result for one dependency checker."""

    met: Optional[bool]
    reason: str
    statuses: Sequence[TIDepStatus]
    trigger_rule_failed: bool = False


class BaseTIDep:
    """Base class for lightweight TI dependency checks."""

    NAME = "base"
    IGNORABLE = False
    IS_TASK_DEP = False

    def evaluate(
        self,
        *,
        node: object,
        states: Dict[str, str],
        context: "DependencyContext",
    ) -> DepDecision:
        raise NotImplementedError

    @staticmethod
    def _passing(name: str, reason: str = "") -> DepDecision:
        return DepDecision(
            met=True,
            reason=reason,
            statuses=(TIDepStatus(name, True, reason),),
        )

    @staticmethod
    def _failing(name: str, reason: str = "", *, trigger_rule_failed: bool = False) -> DepDecision:
        return DepDecision(
            met=False,
            reason=reason,
            statuses=(TIDepStatus(name, False, reason),),
            trigger_rule_failed=trigger_rule_failed,
        )

    @staticmethod
    def _waiting(name: str, reason: str = "") -> DepDecision:
        return DepDecision(
            met=None,
            reason=reason,
            statuses=(TIDepStatus(name, False, reason),),
        )


@dataclass
class DependencyContext:
    """Context passed to dependency checks.

    This keeps the scheduler-like dependency model close to Airflow without pulling
    the full ORM stack.
    """

    states: Dict[str, str]
    running: Dict[str, bool]
    running_count: int
    max_active_tasks: int
    pool_limits: Dict[str, int]
    pool_usage: Dict[str, int]
    task_running_counts: Optional[Dict[str, int]] = None
    retry_ready_at: Optional[Dict[str, float]] = None
    now: float = 0.0

    def pool_usage_ratio(self) -> Dict[str, float]:
        """Return occupancy ratio for all observed pools."""
        ratio: Dict[str, float] = {}
        for pool_name, limit in self.pool_limits.items():
            used = self.pool_usage.get(pool_name, 0)
            ratio[pool_name] = float(used) / float(limit) if limit > 0 else 0.0
        return ratio

    def running_for_task(self, step_id: str) -> int:
        running = self.task_running_counts or {}
        return int(running.get(step_id, 0))


def _is_terminal(state: object) -> bool:
    return state in FINISHED_STATES


class TriggerRuleDep(BaseTIDep):
    """Evaluate whether upstream states satisfy the node trigger rule."""

    NAME = "Trigger Rule"
    IGNORABLE = True
    IS_TASK_DEP = True

    def evaluate(
        self,
        *,
        node: object,
        states: Dict[str, str],
        context: DependencyContext,
    ) -> DepDecision:
        depends_on: Sequence[str] = getattr(node, "depends_on", [])
        trigger_rule = str(getattr(node, "trigger_rule", "all_success")).strip().lower()

        if not depends_on:
            return self._passing(self.NAME, "No upstream dependencies.")

        upstream_states = [states.get(dep_id, TaskInstanceState.NONE) for dep_id in depends_on]
        if not all(_is_terminal(state) for state in upstream_states):
            return self._waiting(self.NAME, "Upstream tasks are not finished yet.")

        from collections import Counter

        counter = Counter(upstream_states)
        total = sum(counter.values())
        success = counter.get(TaskInstanceState.SUCCESS, 0)
        skipped = counter.get(TaskInstanceState.SKIPPED, 0)
        failed = counter.get(TaskInstanceState.FAILED, 0) + counter.get(TaskInstanceState.UPSTREAM_FAILED, 0) + counter.get(TaskInstanceState.REMOVED, 0)
        is_all_success = success == total and total > 0
        is_all_done = total > 0 and _is_terminal_states_all_true(all(state in FINISHED_STATES for state in upstream_states))
        is_none_failed = not _has_failed_or_removed(counter, fail_keys=True)

        if trigger_rule == "all_success":
            if is_all_success:
                return self._passing(self.NAME, "all_success satisfied.")
            return self._failing(self.NAME, "all_success not satisfied.", trigger_rule_failed=True)
        if trigger_rule == "all_done":
            if is_all_done:
                return self._passing(self.NAME, "all_done satisfied.")
            return self._failing(self.NAME, "all_done not satisfied.", trigger_rule_failed=True)
        if trigger_rule == "all_failed":
            if failed == total and total > 0:
                return self._passing(self.NAME, "all_failed satisfied.")
            return self._failing(self.NAME, "all_failed not satisfied.", trigger_rule_failed=True)
        if trigger_rule == "one_success":
            if success >= 1:
                return self._passing(self.NAME, "one_success satisfied.")
            return self._failing(self.NAME, "one_success not satisfied.", trigger_rule_failed=True)
        if trigger_rule == "one_failed":
            if failed >= 1:
                return self._passing(self.NAME, "one_failed satisfied.")
            return self._failing(self.NAME, "one_failed not satisfied.", trigger_rule_failed=True)
        if trigger_rule == "none_failed":
            if is_none_failed:
                return self._passing(self.NAME, "none_failed satisfied.")
            return self._failing(self.NAME, "none_failed not satisfied.", trigger_rule_failed=True)
        if trigger_rule == "none_failed_or_skipped":
            if failed == 0 and skipped == 0:
                return self._passing(self.NAME, "none_failed_or_skipped satisfied.")
            return self._failing(self.NAME, "none_failed_or_skipped not satisfied.", trigger_rule_failed=True)

        return self._passing(self.NAME, f"Unknown trigger rule {trigger_rule!r}; treated as passed.")


def _is_terminal_states_all_true(value: bool) -> bool:
    return bool(value)


def _has_failed_or_removed(counter: Dict[str, int], fail_keys: bool = True) -> bool:
    if fail_keys:
        return (
            counter.get(TaskInstanceState.FAILED, 0) > 0
            or counter.get(TaskInstanceState.UPSTREAM_FAILED, 0) > 0
            or counter.get(TaskInstanceState.REMOVED, 0) > 0
        )
    return counter.get(TaskInstanceState.FAILED, 0) > 0


class PoolSlotsAvailableDep(BaseTIDep):
    """Check if node's pool has free slots."""

    NAME = "Pool Slots Available"
    IGNORABLE = True

    def evaluate(
        self,
        *,
        node: object,
        states: Dict[str, str],
        context: DependencyContext,
    ) -> DepDecision:
        pool = str(getattr(node, "pool", "default"))
        limit = max(1, int(context.pool_limits.get(pool, 1)))
        usage = int(context.pool_usage.get(pool, 0))
        if usage < limit:
            return self._passing(self.NAME, f"Pool {pool} has free slots: used={usage}, limit={limit}.")
        return self._failing(self.NAME, f"Pool {pool} is saturated: used={usage}, limit={limit}.")


class DagTISlotsAvailableDep(BaseTIDep):
    """Check global DAG run concurrency against `max_workers`."""

    NAME = "DAG TI Slots Available"
    IGNORABLE = True

    def evaluate(
        self,
        *,
        node: object,
        states: Dict[str, str],
        context: DependencyContext,
    ) -> DepDecision:
        max_slots = max(1, int(context.max_active_tasks))
        if context.running_count < max_slots:
            return self._passing(self.NAME, f"DAG has capacity: running={context.running_count}, max={max_slots}.")
        return self._failing(self.NAME, f"DAG reached max concurrent tasks: running={context.running_count}, max={max_slots}.")


class TaskConcurrencyDep(BaseTIDep):
    """Restrict parallel running tasks for the same node id."""

    NAME = "Task Concurrency"
    IGNORABLE = True
    IS_TASK_DEP = True

    def evaluate(
        self,
        *,
        node: object,
        states: Dict[str, str],
        context: DependencyContext,
    ) -> DepDecision:
        limit = getattr(node, "max_active_tis_per_dagrun", None)
        if limit is None:
            return self._passing(self.NAME, "No task concurrency limit.")

        try:
            limit_value = max(1, int(limit))
        except Exception:
            return self._passing(self.NAME, f"Invalid task concurrency value: {limit!r}.")

        running_for_node = context.running_for_task(getattr(node, "step_id", ""))
        if running_for_node < limit_value:
            return self._passing(
                self.NAME,
                f"Task concurrency not exceeded: running={running_for_node}, limit={limit_value}.",
            )
        return self._failing(
            self.NAME,
            f"Task concurrency limit reached for {node.step_id}: running={running_for_node}, limit={limit_value}.",
        )


class TaskNotRunningDep(BaseTIDep):
    """Skip running steps from being re-queued."""

    NAME = "Task Instance Not Running"
    IGNORABLE = False

    def evaluate(
        self,
        *,
        node: object,
        states: Dict[str, str],
        context: DependencyContext,
    ) -> DepDecision:
        if states.get(getattr(node, "step_id", ""), "") == TaskInstanceState.RUNNING:
            return self._failing(self.NAME, "Task is running.")
        return self._passing(self.NAME, "Task is not running.")


class NotInRetryPeriodDep(BaseTIDep):
    """Delay scheduling while waiting for retry timeout."""

    NAME = "Not In Retry Period"
    IGNORABLE = True
    IS_TASK_DEP = True

    def evaluate(
        self,
        *,
        node: object,
        states: Dict[str, str],
        context: DependencyContext,
    ) -> DepDecision:
        step_id = getattr(node, "step_id", "")
        state = states.get(step_id, TaskInstanceState.NONE)
        if state != TaskInstanceState.UP_FOR_RETRY:
            return self._passing(self.NAME, "Task is not in retry period.")

        retry_ready = context.retry_ready_at or {}
        wait_until = retry_ready.get(step_id, 0.0)
        if not wait_until:
            return self._passing(self.NAME, "Retry-ready timestamp missing; continue.")
        if context.now >= wait_until:
            return self._passing(self.NAME, "Retry delay passed.")
        return self._waiting(self.NAME, f"Task in retry period until {wait_until:.0f}.")


class TIDependencyEvaluator:
    """Evaluate all TI-like dependencies for one step."""

    def __init__(self, include_trigger_rule: bool = True):
        self._deps = [
            TaskNotRunningDep(),
            NotInRetryPeriodDep(),
            PoolSlotsAvailableDep(),
            DagTISlotsAvailableDep(),
            TaskConcurrencyDep(),
            TriggerRuleDep(),
        ]
        if not include_trigger_rule:
            self._deps = [dep for dep in self._deps if not isinstance(dep, TriggerRuleDep)]

    def evaluate(self, node: object, context: DependencyContext) -> DepDecision:
        """Aggregate dependency statuses.

        Returns:
            met is True     -> all deps passed, can be scheduled.
            met is False    -> dependency condition failed definitively.
            met is None     -> waiting on upstream / retry / external conditions.
        """
        reasons: List[TIDepStatus] = []
        met: Optional[bool] = True
        trigger_rule_failed = False
        waiting_reasons: List[str] = []

        for dep in self._deps:
            decision = dep.evaluate(node=node, states=context.states, context=context)
            reasons.extend(decision.statuses)
            if decision.met is False:
                met = False
                trigger_rule_failed = trigger_rule_failed or decision.trigger_rule_failed
                # keep the first concrete fail and break early for deterministic behavior
                break
            if decision.met is None:
                met = None
                waiting_reasons.append(decision.reason)

        reason = waiting_reasons[0] if met is None and waiting_reasons else ""
        if met is False:
            reason = next((item.reason for item in reasons if not item.passed), "")
            if not reason and waiting_reasons:
                reason = waiting_reasons[0]
        if met is True and not reasons:
            reason = "dependencies passed"
        if met is True and reasons:
            reason = ", ".join(item.reason for item in reasons if item.passed and item.reason)
        return DepDecision(
            met=met,
            reason=reason,
            statuses=tuple(reasons),
            trigger_rule_failed=trigger_rule_failed,
        )


