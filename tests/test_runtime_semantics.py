import concurrent.futures
import gc
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from trainsh.core.executor_main import DSLExecutor, _StepNode
from trainsh.core.local_tmux import TmuxCmdResult
from trainsh.core.recipe_models import RecipeModel
from trainsh.core.task_state import TaskInstanceState
from trainsh.core.ti_dependencies import DependencyContext, TriggerRuleDep
from trainsh import Recipe
from trainsh.pyrecipe.models import ProviderStep


@contextmanager
def isolated_executor(recipe_model: Any, *, executor_name: str = "sequential", executor_kwargs=None):
    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        config_dir = Path(tmpdir) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        stack.enter_context(
            patch(
                "trainsh.core.executor_main.load_config",
                return_value={"tmux": {"auto_bridge": False}},
            )
        )
        stack.enter_context(patch("trainsh.core.executor_main.CONFIG_DIR", config_dir))
        stack.enter_context(patch("trainsh.runtime.CONFIG_DIR", config_dir))
        executor = DSLExecutor(
            recipe_model,
            log_callback=lambda *_args, **_kwargs: None,
            executor_name=executor_name,
            executor_kwargs=executor_kwargs or {},
        )
        try:
            yield executor, config_dir
        finally:
            executor.close()
            gc.collect()


class FakeLocalTmux:
    def __init__(self):
        self.sessions = set()
        self.buffers = {}
        self.new_sessions = []
        self.sent = []
        self.captures = []
        self.killed = []

    def has_session(self, name: str) -> bool:
        return name in self.sessions

    def new_session(self, name: str, detached: bool = True, window_name=None, command=None) -> TmuxCmdResult:
        self.sessions.add(name)
        self.buffers.setdefault(name, "")
        self.new_sessions.append(name)
        return TmuxCmdResult(0, "", "")

    def send_keys(self, target: str, text: str, enter: bool = True, literal: bool = True) -> TmuxCmdResult:
        self.sent.append((target, text, enter, literal))
        if "python train.py" in text:
            self.buffers[target] = "booting\ntraining finished\n"
        return TmuxCmdResult(0, "", "")

    def capture_pane(self, target: str, start=None, end=None) -> TmuxCmdResult:
        self.captures.append((target, start, end))
        return TmuxCmdResult(0, self.buffers.get(target, ""), "")

    def kill_session(self, name: str) -> TmuxCmdResult:
        self.killed.append(name)
        self.sessions.discard(name)
        return TmuxCmdResult(0, "", "")


class TriggerRuleDependencyTests(unittest.TestCase):
    def _context(self, states):
        return DependencyContext(
            states=states,
            running={},
            running_count=0,
            max_active_tasks=1,
            pool_limits={"default": 1},
            pool_usage={},
        )

    def test_trigger_rules_cover_join_and_branch_semantics(self):
        cases = [
            (
                "all_done",
                {"up_a": TaskInstanceState.SUCCESS, "up_b": TaskInstanceState.FAILED, "up_c": TaskInstanceState.SKIPPED},
                True,
            ),
            (
                "all_failed",
                {"up_a": TaskInstanceState.FAILED, "up_b": TaskInstanceState.UPSTREAM_FAILED},
                True,
            ),
            (
                "one_success",
                {"up_a": TaskInstanceState.SKIPPED, "up_b": TaskInstanceState.SUCCESS},
                True,
            ),
            (
                "one_failed",
                {"up_a": TaskInstanceState.SUCCESS, "up_b": TaskInstanceState.SKIPPED},
                False,
            ),
            (
                "none_failed",
                {"up_a": TaskInstanceState.SUCCESS, "up_b": TaskInstanceState.SKIPPED},
                True,
            ),
            (
                "none_failed_or_skipped",
                {"up_a": TaskInstanceState.SUCCESS, "up_b": TaskInstanceState.SKIPPED},
                False,
            ),
        ]

        dep = TriggerRuleDep()
        for trigger_rule, states, expected in cases:
            with self.subTest(trigger_rule=trigger_rule, states=states):
                node = SimpleNamespace(
                    step_id="join",
                    depends_on=list(states.keys()),
                    trigger_rule=trigger_rule,
                )
                decision = dep.evaluate(node=node, states=states, context=self._context(states))
                self.assertIs(decision.met, expected)
                self.assertEqual(decision.trigger_rule_failed, not expected)


class SequentialDependencyExecutionTests(unittest.TestCase):
    def test_sequential_executor_honors_trigger_rules_and_continue_on_failure(self):
        recipe = Recipe("sequential-trigger-demo", executor="sequential")
        start = recipe.empty(id="start")
        failed = recipe.fail(
            "boom",
            id="failed",
            depends_on=[start],
            step_options={"continue_on_failure": True},
        )
        join = recipe.join(id="join", depends_on=[failed])
        strict = recipe.on_none_failed(id="strict", depends_on=[failed])
        recipe.empty(id="finish", depends_on=[join])

        events = []
        with isolated_executor(recipe, executor_name="sequential") as (executor, _config_dir):
            with patch.object(
                executor,
                "_emit_event",
                side_effect=lambda event, **payload: events.append((event, payload)),
            ):
                ok = executor.execute()

        self.assertTrue(ok)
        end_states = {
            payload["step_id"]: payload["state"]
            for event, payload in events
            if event == "step_end" and payload.get("step_id")
        }
        self.assertEqual(end_states["failed"], TaskInstanceState.FAILED)
        self.assertEqual(end_states["join"], TaskInstanceState.SUCCESS)
        self.assertEqual(end_states["finish"], TaskInstanceState.SUCCESS)
        self.assertEqual(end_states["strict"], TaskInstanceState.SKIPPED)


class CallbackAndRetryTests(unittest.TestCase):
    def test_retries_apply_exponential_backoff_and_fire_success_callback_once(self):
        shell_calls = []
        success_contexts = []
        step = ProviderStep("util", "empty", {}, id="train")
        node = _StepNode(
            step_num=1,
            step_id="train",
            step=step,
            depends_on=[],
            retries=2,
            retry_delay=2,
            retry_exponential_backoff=2.0,
            on_success=[
                lambda context: success_contexts.append(dict(context)),
                "echo {step_id}:{try_number}",
            ],
        )

        with isolated_executor(RecipeModel(name="retry-success")) as (executor, _config_dir):
            with patch.object(
                executor,
                "_run_single_step",
                side_effect=[
                    (False, "fail-1", 10),
                    (False, "fail-2", 20),
                    (True, "ok", 30),
                ],
            ), patch("trainsh.core.executor_main.time.sleep") as mocked_sleep, patch.object(
                executor,
                "_exec_provider_shell",
                side_effect=lambda params: (shell_calls.append(dict(params)) or True, ""),
            ):
                ok, output, duration_ms = executor._run_single_step_with_retries(node, step_id="train")

        self.assertTrue(ok)
        self.assertEqual(output, "ok")
        self.assertEqual(duration_ms, 30)
        self.assertEqual([call.args[0] for call in mocked_sleep.call_args_list], [2, 4])
        self.assertEqual(len(success_contexts), 1)
        self.assertEqual(success_contexts[0]["try_number"], 3)
        self.assertEqual(shell_calls[0]["command"], "echo train:3")

    def test_failure_callbacks_run_after_final_attempt_and_interpolate_provider_steps(self):
        failure_contexts = []
        step = ProviderStep("util", "empty", {}, id="train")
        callback_step = ProviderStep(
            "util",
            "set_var",
            {"name": "FAILED_CONTEXT", "value": "{step_id}:{try_number}:{output}"},
            id="callback",
        )
        node = _StepNode(
            step_num=1,
            step_id="train",
            step=step,
            depends_on=[],
            retries=2,
            retry_delay=1,
            retry_exponential_backoff=2.0,
            on_failure=[callback_step, lambda context: failure_contexts.append(dict(context))],
        )

        with isolated_executor(RecipeModel(name="retry-failure")) as (executor, _config_dir):
            with patch.object(
                executor,
                "_run_single_step",
                side_effect=[
                    (False, "boom-1", 10),
                    (False, "boom-2", 20),
                    (False, "boom-3", 30),
                ],
            ), patch("trainsh.core.executor_main.time.sleep"):
                ok, output, duration_ms = executor._run_single_step_with_retries(node, step_id="train")

        self.assertFalse(ok)
        self.assertEqual(output, "boom-3")
        self.assertEqual(duration_ms, 30)
        self.assertEqual(len(failure_contexts), 1)
        self.assertEqual(failure_contexts[0]["try_number"], 3)
        self.assertEqual(executor.ctx.variables["FAILED_CONTEXT"], "train:3:boom-3")

    def test_execute_step_with_timeout_returns_timeout_error(self):
        class TimeoutFuture:
            def result(self, timeout=None):
                raise concurrent.futures.TimeoutError()

        class TimeoutPool:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn):
                return TimeoutFuture()

        with isolated_executor(RecipeModel(name="timeout-demo")) as (executor, _config_dir):
            with patch(
                "trainsh.core.executor_main.concurrent.futures.ThreadPoolExecutor",
                return_value=TimeoutPool(),
            ):
                ok, output = executor._execute_step_with_timeout(
                    ProviderStep("util", "empty", {}, id="slow"),
                    timeout_secs=1,
                    step_id="slow",
                    step_num=1,
                    try_number=1,
                )

        self.assertFalse(ok)
        self.assertEqual(output, "Step timeout after 1s")


class SessionLifecycleTests(unittest.TestCase):
    def test_session_helpers_execute_local_tmux_lifecycle_without_real_tmux(self):
        recipe = Recipe("session-demo", executor="sequential")
        main = recipe.tmux_session("local", as_="main", id="open")
        train = main.bg("python train.py", id="train")
        seen = main.wait("training finished", id="seen", depends_on=[train])
        idle = main.wait_idle(id="idle", timeout="10s", depends_on=[seen])
        main.close(id="close", depends_on=[idle])

        fake_tmux = FakeLocalTmux()
        with isolated_executor(recipe, executor_name="sequential") as (executor, _config_dir):
            executor.local_tmux = fake_tmux
            with patch.object(
                executor.wait_helper,
                "is_pane_idle",
                side_effect=[True, True, True],
            ), patch("trainsh.core.executor_wait.time.sleep", side_effect=lambda *_args, **_kwargs: None):
                ok = executor.execute()

        self.assertTrue(ok)
        self.assertEqual(len(fake_tmux.new_sessions), 1)
        session_name = fake_tmux.new_sessions[0]
        self.assertTrue(any(target == session_name and "python train.py" in text for target, text, _, _ in fake_tmux.sent))
        self.assertTrue(any(target == session_name for target, _start, _end in fake_tmux.captures))
        self.assertEqual(fake_tmux.killed, [session_name])
        self.assertNotIn("main", executor.ctx.windows)
        self.assertEqual(executor.ctx.next_window_index, 1)


if __name__ == "__main__":
    unittest.main()
