import concurrent.futures
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.executor_main import _StepNode
from trainsh.core.recipe_models import RecipeModel
from trainsh.pyrecipe.models import ProviderStep

from tests.runtime_test_utils import isolated_executor


class ExecutorMainCoreTests(unittest.TestCase):
    def test_pool_limits_and_step_graph_validation(self):
        with isolated_executor(RecipeModel(name="core")) as (executor, _config_dir):
            executor.max_workers = 4
            self.assertEqual(executor._parse_pool_limits(None), {"default": 4})
            self.assertEqual(executor._parse_pool_limits(2), {"default": 2})
            self.assertEqual(executor._parse_pool_limits("{'gpu': 2}"), {"gpu": 2, "default": 4})
            self.assertEqual(executor._parse_pool_limits({"gpu": "bad"}), {"default": 4})
            self.assertEqual(executor._pool_limit("gpu"), 4)

            step1 = ProviderStep("util", "empty", {}, id="a")
            step2 = ProviderStep("util", "empty", {}, id="b")
            step2.depends_on = ["a"]
            executor.recipe.steps = [step1, step2]
            nodes, ordered, has_dep = executor._build_step_graph()
            self.assertTrue(has_dep)
            self.assertEqual(ordered, ["a", "b"])
            self.assertEqual(nodes["b"].depends_on, ["a"])

            dup = ProviderStep("util", "empty", {}, id="a")
            executor.recipe.steps = [step1, dup]
            with self.assertRaises(ValueError):
                executor._build_step_graph()

            missing = ProviderStep("util", "empty", {}, id="c")
            missing.depends_on = ["missing"]
            executor.recipe.steps = [missing]
            with self.assertRaises(ValueError):
                executor._build_step_graph()

    def test_step_details_defer_check_timeout_and_execute_timeout(self):
        with isolated_executor(RecipeModel(name="core")) as (executor, _config_dir):
            step = ProviderStep("util", "wait_condition", {"condition": "var:READY==1", "timeout": "5s", "poll_interval": "2s"}, id="wait")
            node = _StepNode(step_num=1, step_id="wait", step=step, depends_on=[], deferrable=True)
            details = executor._build_step_details(step)
            self.assertEqual(details["provider"], "util")
            self.assertEqual(details["params"]["condition"], "var:READY==1")

            defer = executor._build_defer_check(node, step_id="wait", attempt=1)
            self.assertIsNotNone(defer)
            check_fn, timeout_secs, poll_interval = defer
            self.assertEqual(timeout_secs, 5)
            self.assertEqual(poll_interval, 2)
            executor.ctx.variables["READY"] = "1"
            self.assertEqual(check_fn(), (True, "Condition met: var:READY==1"))

            bad = ProviderStep("util", "wait_condition", {"condition": "var:READY==1", "timeout": "bad"}, id="bad")
            node_bad = _StepNode(step_num=2, step_id="bad", step=bad, depends_on=[], deferrable=True)
            self.assertIsNone(executor._build_defer_check(node_bad, step_id="bad", attempt=1))

            plain = ProviderStep("util", "empty", {}, id="plain")
            node_plain = _StepNode(step_num=3, step_id="plain", step=plain, depends_on=[], deferrable=True)
            self.assertIsNone(executor._build_defer_check(node_plain, step_id="plain", attempt=1))

            with patch.object(executor, "_execute_step", return_value=(True, "ok")):
                ok, output = executor._execute_step_with_timeout(step, timeout_secs=0, step_id="wait", step_num=1, try_number=1)
            self.assertTrue(ok)
            self.assertEqual(output, "ok")

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

            with patch("trainsh.core.executor_main.concurrent.futures.ThreadPoolExecutor", return_value=TimeoutPool()):
                ok, output = executor._execute_step_with_timeout(step, timeout_secs=1, step_id="wait", step_num=1, try_number=1)
            self.assertFalse(ok)
            self.assertIn("timeout", output.lower())

    def test_run_single_step_with_state_and_execute_paths(self):
        with isolated_executor(RecipeModel(name="core")) as (executor, _config_dir):
            step = ProviderStep("util", "empty", {}, id="empty")
            events = []
            executor.logger = SimpleNamespace(
                step_start=lambda *a, **k: events.append(("logger_start", a)),
                step_output=lambda *a, **k: events.append(("logger_output", a)),
                step_end=lambda *a, **k: events.append(("logger_end", a)),
                log_detail=lambda *a, **k: None,
            )

            with patch.object(executor, "_execute_step_with_timeout", return_value=(True, "ok")), patch.object(
                executor, "_save_checkpoint"
            ) as mocked_checkpoint, patch.object(executor, "_emit_event", side_effect=lambda event, **payload: events.append((event, payload))):
                state, output, duration = executor._run_single_step_with_state(1, step, step_id="empty", try_number=1)
            self.assertEqual(state, "success")
            self.assertEqual(output, "ok")
            mocked_checkpoint.assert_called_once()
            self.assertTrue(any(name == "step_end" for name, _ in events))

            with patch.object(executor, "_execute_step_with_timeout", side_effect=RuntimeError("boom")), patch.object(
                executor, "_emit_event"
            ) as mocked_emit:
                state, output, duration = executor._run_single_step_with_state(1, step, step_id="empty", try_number=1)
            self.assertEqual(state, "failed")
            self.assertIn("RuntimeError", output)
            mocked_emit.assert_called()

            provider_step = ProviderStep("util", "empty", {}, id="provider")
            with patch.object(executor, "_exec_provider", return_value=(True, "provider")):
                self.assertEqual(executor._execute_step(provider_step), (True, "provider"))

            fallback_step = SimpleNamespace(command="provider", raw='provider util.empty {}', provider="", operation="", params={}, type=None)
            with patch.object(executor, "_exec_provider", return_value=(True, "provider-fallback")):
                self.assertEqual(executor._execute_step(fallback_step), (True, "provider-fallback"))

            unknown_step = SimpleNamespace(type="weird")
            ok, msg = executor._execute_step(unknown_step)
            self.assertFalse(ok)
            self.assertIn("Unknown step type", msg)

    def test_execute_main_path_and_bridge_helpers(self):
        recipe = RecipeModel(name="core")
        with isolated_executor(recipe, executor_name="sequential") as (executor, _config_dir):
            executor.logger = SimpleNamespace(end=lambda *a, **k: None, start=lambda *a, **k: None)
            with patch.object(executor, "_emit_event"), patch.object(executor, "_execute_sequential", return_value=True), patch.object(
                executor, "_clear_checkpoint"
            ) as mocked_clear:
                ok = executor.execute(resume_from=0)
            self.assertTrue(ok)
            mocked_clear.assert_called_once()

            executor.executor_name = "threadpool"
            with patch.object(executor, "_emit_event"), patch.object(executor, "_execute_with_dependencies", return_value=False), patch.object(
                executor, "_clear_checkpoint"
            ) as mocked_clear:
                ok = executor.execute(resume_from=1)
            self.assertFalse(ok)
            mocked_clear.assert_not_called()

            window = SimpleNamespace(host="gpu", remote_session="sess", name="main")
            with patch.object(executor.bridge_exec, "build_bridge_attach_command", return_value="attach"), patch.object(
                executor.bridge_exec, "ensure_bridge_window"
            ) as mocked_bridge, patch.object(executor.bridge_exec, "restore_tmux_bridge") as mocked_restore, patch.object(
                executor.bridge_exec, "wait_for_bridge_idle", return_value=(True, "idle")
            ), patch.object(executor.bridge_exec, "exec_via_bridge", return_value=(True, "ok")):
                self.assertEqual(executor._build_bridge_attach_command(window), "attach")
                executor._ensure_bridge_window(window)
                executor.restore_tmux_bridge()
                self.assertEqual(executor._wait_for_bridge_idle("main", "%1", 5), (True, "idle"))
                self.assertEqual(executor._exec_via_bridge(window, "echo hi", 5, False, 0), (True, "ok"))
            mocked_bridge.assert_called_once()
            mocked_restore.assert_called_once()

    def test_control_commands_and_execute_dispatch(self):
        recipe = RecipeModel(name="core")
        with isolated_executor(recipe, executor_name="sequential") as (executor, _config_dir):
            step = SimpleNamespace(command="sleep", args=["1s"])
            with patch("trainsh.core.executor_main.time.sleep") as mocked_sleep:
                ok, msg = executor._exec_control(step)
            self.assertTrue(ok)
            mocked_sleep.assert_called_once_with(1)

            bad_sleep = SimpleNamespace(command="sleep", args=[])
            ok, msg = executor._exec_control(bad_sleep)
            self.assertFalse(ok)
            self.assertIn("Usage: sleep", msg)

            with patch.object(executor.tmux_control, "cmd_tmux_open", return_value=(True, "open")) as mocked_open:
                self.assertEqual(executor._exec_control(SimpleNamespace(command="tmux.open", args=["@gpu", "as", "main"])), (True, "open"))
            mocked_open.assert_called_once()

            with patch.object(executor.tmux_control, "cmd_tmux_close", return_value=(True, "close")) as mocked_close:
                self.assertEqual(executor._exec_control(SimpleNamespace(command="tmux.close", args=["@main"])), (True, "close"))
            mocked_close.assert_called_once()

            with patch.object(executor.tmux_control, "cmd_tmux_config", return_value=(True, "cfg")) as mocked_cfg:
                self.assertEqual(executor._exec_control(SimpleNamespace(command="tmux.config", args=["@gpu"])), (True, "cfg"))
            mocked_cfg.assert_called_once()

            with patch.object(executor.vast_control, "cmd_vast_start", return_value=(True, "start")), patch.object(
                executor.vast_control, "cmd_vast_stop", return_value=(True, "stop")
            ), patch.object(
                executor.vast_control, "cmd_vast_pick", return_value=(True, "pick")
            ), patch.object(
                executor.vast_control, "cmd_vast_wait", return_value=(True, "wait")
            ), patch.object(
                executor.vast_control, "cmd_vast_cost", return_value=(True, "cost")
            ):
                self.assertEqual(executor._exec_control(SimpleNamespace(command="vast.start", args=[])), (True, "start"))
                self.assertEqual(executor._exec_control(SimpleNamespace(command="vast.stop", args=[])), (True, "stop"))
                self.assertEqual(executor._exec_control(SimpleNamespace(command="vast.pick", args=[])), (True, "pick"))
                self.assertEqual(executor._exec_control(SimpleNamespace(command="vast.wait", args=[])), (True, "wait"))
                self.assertEqual(executor._exec_control(SimpleNamespace(command="vast.cost", args=[])), (True, "cost"))

            with patch.object(executor.notifier, "notify", return_value=(True, "sent")):
                ok, msg = executor._cmd_notify(["hello"])
            self.assertTrue(ok)
            executor.notify_enabled = False
            ok, msg = executor._cmd_notify(["hello"])
            self.assertTrue(ok)
            self.assertIn("skipped", msg)
            executor.notify_enabled = True
            ok, msg = executor._cmd_notify([])
            self.assertFalse(ok)

            ok, msg = executor._exec_control(SimpleNamespace(command="missing", args=[]))
            self.assertFalse(ok)
            self.assertIn("Unknown control command", msg)

            self.assertEqual(executor._normalize_provider_timeout(None), 0)
            self.assertIsNone(executor._normalize_provider_timeout("bad"))
            self.assertEqual(executor._positive_provider_timeout("bad", default=7), 7)


if __name__ == "__main__":
    unittest.main()
