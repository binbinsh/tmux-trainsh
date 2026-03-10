import unittest
from types import SimpleNamespace

from trainsh.core.task_state import TaskInstanceState
from trainsh.core.ti_dependencies import (
    DagTISlotsAvailableDep,
    DependencyContext,
    NotInRetryPeriodDep,
    PoolSlotsAvailableDep,
    TIDependencyEvaluator,
    TaskConcurrencyDep,
    TaskNotRunningDep,
    TriggerRuleDep,
)


class DependencyHelpersTests(unittest.TestCase):
    def _context(self, **kwargs) -> DependencyContext:
        defaults = {
            "states": {},
            "running": {},
            "running_count": 0,
            "max_active_tasks": 2,
            "pool_limits": {"default": 2, "gpu": 1},
            "pool_usage": {},
            "task_running_counts": {},
            "retry_ready_at": {},
            "now": 100.0,
        }
        defaults.update(kwargs)
        return DependencyContext(**defaults)

    def test_pool_slots_available_dep_pass_and_fail(self):
        dep = PoolSlotsAvailableDep()
        node = SimpleNamespace(step_id="train", pool="gpu")

        passed = dep.evaluate(node=node, states={}, context=self._context(pool_usage={"gpu": 0}))
        failed = dep.evaluate(node=node, states={}, context=self._context(pool_usage={"gpu": 1}))

        self.assertTrue(passed.met)
        self.assertFalse(failed.met)
        self.assertIn("saturated", failed.reason)

    def test_dag_ti_slots_available_dep_pass_and_fail(self):
        dep = DagTISlotsAvailableDep()
        node = SimpleNamespace(step_id="train")

        passed = dep.evaluate(node=node, states={}, context=self._context(running_count=1, max_active_tasks=2))
        failed = dep.evaluate(node=node, states={}, context=self._context(running_count=2, max_active_tasks=2))

        self.assertTrue(passed.met)
        self.assertFalse(failed.met)
        self.assertIn("max concurrent tasks", failed.reason)

    def test_task_concurrency_dep_handles_limit_and_invalid_values(self):
        dep = TaskConcurrencyDep()

        no_limit = dep.evaluate(
            node=SimpleNamespace(step_id="train", max_active_tis_per_dagrun=None),
            states={},
            context=self._context(),
        )
        invalid_limit = dep.evaluate(
            node=SimpleNamespace(step_id="train", max_active_tis_per_dagrun="bad"),
            states={},
            context=self._context(),
        )
        blocked = dep.evaluate(
            node=SimpleNamespace(step_id="train", max_active_tis_per_dagrun=1),
            states={},
            context=self._context(task_running_counts={"train": 1}),
        )

        self.assertTrue(no_limit.met)
        self.assertTrue(invalid_limit.met)
        self.assertFalse(blocked.met)
        self.assertIn("limit reached", blocked.reason)

    def test_task_not_running_dep_blocks_running_steps(self):
        dep = TaskNotRunningDep()
        node = SimpleNamespace(step_id="train")
        blocked = dep.evaluate(
            node=node,
            states={"train": TaskInstanceState.RUNNING},
            context=self._context(states={"train": TaskInstanceState.RUNNING}),
        )
        passed = dep.evaluate(node=node, states={}, context=self._context())

        self.assertFalse(blocked.met)
        self.assertTrue(passed.met)

    def test_not_in_retry_period_dep_waits_until_retry_ready(self):
        dep = NotInRetryPeriodDep()
        node = SimpleNamespace(step_id="train")
        waiting = dep.evaluate(
            node=node,
            states={"train": TaskInstanceState.UP_FOR_RETRY},
            context=self._context(
                states={"train": TaskInstanceState.UP_FOR_RETRY},
                retry_ready_at={"train": 120.0},
                now=100.0,
            ),
        )
        passed = dep.evaluate(
            node=node,
            states={"train": TaskInstanceState.UP_FOR_RETRY},
            context=self._context(
                states={"train": TaskInstanceState.UP_FOR_RETRY},
                retry_ready_at={"train": 90.0},
                now=100.0,
            ),
        )

        self.assertIsNone(waiting.met)
        self.assertIn("retry period", waiting.reason)
        self.assertTrue(passed.met)

    def test_trigger_rule_dep_waits_for_unfinished_upstream(self):
        dep = TriggerRuleDep()
        node = SimpleNamespace(step_id="join", depends_on=["a", "b"], trigger_rule="all_done")
        decision = dep.evaluate(
            node=node,
            states={"a": TaskInstanceState.SUCCESS, "b": TaskInstanceState.RUNNING},
            context=self._context(states={"a": TaskInstanceState.SUCCESS, "b": TaskInstanceState.RUNNING}),
        )

        self.assertIsNone(decision.met)
        self.assertIn("not finished", decision.reason)

    def test_dependency_evaluator_reports_waiting_reason(self):
        node = SimpleNamespace(
            step_id="train",
            depends_on=[],
            trigger_rule="all_success",
            pool="default",
            max_active_tis_per_dagrun=None,
        )
        evaluator = TIDependencyEvaluator()
        decision = evaluator.evaluate(
            node,
            self._context(
                states={"train": TaskInstanceState.UP_FOR_RETRY},
                retry_ready_at={"train": 150.0},
                now=100.0,
            ),
        )

        self.assertIsNone(decision.met)
        self.assertIn("retry period", decision.reason)

    def test_dependency_evaluator_propagates_trigger_rule_failure(self):
        node = SimpleNamespace(
            step_id="join",
            depends_on=["a", "b"],
            trigger_rule="none_failed",
            pool="default",
            max_active_tis_per_dagrun=None,
        )
        states = {"a": TaskInstanceState.SUCCESS, "b": TaskInstanceState.FAILED}
        evaluator = TIDependencyEvaluator()
        decision = evaluator.evaluate(node, self._context(states=states))

        self.assertFalse(decision.met)
        self.assertTrue(decision.trigger_rule_failed)
        self.assertIn("none_failed", decision.reason)

    def test_dependency_evaluator_can_ignore_trigger_rule(self):
        node = SimpleNamespace(
            step_id="join",
            depends_on=["a", "b"],
            trigger_rule="none_failed",
            pool="default",
            max_active_tis_per_dagrun=None,
        )
        states = {"a": TaskInstanceState.SUCCESS, "b": TaskInstanceState.FAILED}
        evaluator = TIDependencyEvaluator(include_trigger_rule=False)
        decision = evaluator.evaluate(node, self._context(states=states))

        self.assertTrue(decision.met)
        self.assertFalse(decision.trigger_rule_failed)


if __name__ == "__main__":
    unittest.main()
