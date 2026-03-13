import queue
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.executor_main import run_recipe
from trainsh.core.recipe_models import RecipeModel
from trainsh.core.task_state import TaskInstanceState
from trainsh.core.executor_runtime import _StepNode
from trainsh.pyrecipe.models import ProviderStep

from tests.runtime_test_utils import isolated_executor


class ExecStepHelperEdgeTests(unittest.TestCase):
    def test_extractors_normalizers_and_callback_dispatch(self):
        with isolated_executor(RecipeModel(name="edge-helpers")) as (executor, _config_dir):
            wrapper = SimpleNamespace(to_step_model=lambda: None)
            self.assertIs(executor._coerce_step(wrapper), wrapper)
            self.assertEqual(executor._extract_step_id(SimpleNamespace(id=""), 0), "step_001")
            self.assertEqual(executor._extract_step_id(SimpleNamespace(id="abc"), 1), "abc")
            self.assertEqual(executor._extract_depends(SimpleNamespace(depends_on="a")), ["a"])
            self.assertEqual(
                executor._extract_depends(SimpleNamespace(depends_on=["a", "", "a", "b"])),
                ["a", "b"],
            )

            self.assertTrue(executor._normalize_bool("yes"))
            self.assertFalse(executor._normalize_bool("", default=False))
            self.assertTrue(executor._coerce_bool(True))
            self.assertEqual(executor._coerce_list(""), [])
            self.assertEqual(executor._coerce_list(("a", " b ", "")), ["a", "b"])
            self.assertEqual(executor._coerce_list("x, y"), ["x", "y"])
            self.assertEqual(executor._coerce_list(5), ["5"])

            self.assertEqual(executor._normalize_retry_delay(None), 0)
            self.assertEqual(executor._normalize_retry_delay(True), 1)
            self.assertEqual(executor._normalize_retry_delay("5s"), 5)
            self.assertEqual(executor._normalize_retry_delay("bad"), 0)

            step = SimpleNamespace(
                retries="2",
                retry_delay="7s",
                continue_on_failure="true",
                trigger_rule="bad-rule",
                max_active_tis_per_dagrun="3",
                deferrable="yes",
                pool="gpu",
                priority="4",
                execution_timeout="9s",
                retry_exponential_backoff="2.5",
                on_success=[None, lambda: None, "echo ok", b"bytes", {"k": "v"}, ProviderStep("util", "empty", {}, id="cbok")],
                on_failure={"provider": "util", "operation": "empty"},
            )
            self.assertEqual(executor._extract_step_retries(step), 2)
            self.assertEqual(executor._extract_step_retry_delay(step), 7)
            self.assertTrue(executor._extract_step_continue_on_failure(step))
            self.assertEqual(executor._extract_step_trigger_rule(step), "all_success")
            self.assertEqual(executor._extract_step_max_active_tis_per_dagrun(step), 3)
            self.assertTrue(executor._extract_step_deferrable(step))
            self.assertEqual(executor._extract_step_pool(step), "gpu")
            self.assertEqual(executor._extract_step_priority(step), 4)
            self.assertEqual(executor._extract_step_execution_timeout(step), 9)
            self.assertEqual(executor._extract_step_retry_exponential_backoff(step), 2.5)
            self.assertEqual(len(executor._extract_step_callbacks(step, "on_success")), 5)
            self.assertEqual(len(executor._extract_step_callbacks(step, "on_failure")), 1)
            self.assertTrue(executor._step_is_terminal("success"))
            self.assertEqual(executor._compute_backoff_delay(SimpleNamespace(retry_delay=3, retry_exponential_backoff=2.0), 3), 12)

            edge = SimpleNamespace(
                retries="bad",
                trigger_rule="not-valid",
                max_active_tis_per_dagrun=False,
                priority="bad",
                execution_timeout="bad",
                retry_exponential_backoff=-1,
                on_success=None,
                on_failure=object(),
            )
            self.assertEqual(executor._extract_step_retries(edge), 0)
            self.assertEqual(executor._extract_step_trigger_rule(edge), "all_success")
            self.assertIsNone(executor._extract_step_max_active_tis_per_dagrun(edge))
            self.assertEqual(executor._extract_step_priority(edge), 0)
            self.assertEqual(executor._extract_step_execution_timeout(edge), 0)
            self.assertEqual(executor._extract_step_retry_exponential_backoff(edge), 0.0)
            self.assertEqual(executor._extract_step_callbacks(edge, "on_success"), [])
            self.assertEqual(executor._extract_step_callbacks(edge, "on_failure"), [])

            rendered = executor._render_callback_value("hello {step_id}", {"step_id": "s1"})
            self.assertEqual(rendered, "hello s1")
            self.assertEqual(executor._render_callback_value(b"hi", {}), "hi")
            self.assertEqual(executor._render_callback_value(5, {}), 5)
            self.assertEqual(executor._render_callback_value("{broken", {"step_id": "s1"}), "{broken")
            nested = executor._normalize_callback_payload({"x": "{step_id}", "items": [b"ok", "{try_number}"]}, {"step_id": "s1", "try_number": 2})
            self.assertEqual(nested, {"x": "s1", "items": [b"ok", "2"]})

            shell_calls = []
            provider_calls = []
            log_messages = []

            def _noarg():
                log_messages.append("noarg")

            provider_cb = ProviderStep("util", "empty", {"x": "{step_id}"}, id="cb")
            dict_provider = {"provider": "util", "operation": "empty", "params": {"x": "{step_id}"}}
            dict_command = {"command": "echo {step_id}", "cwd": "/tmp"}

            with patch.object(executor, "_exec_provider", side_effect=lambda step: provider_calls.append(step) or (True, "ok")), patch.object(
                executor,
                "_run_provider_or_shell_callback",
                side_effect=lambda spec, context: shell_calls.append((spec, context)),
            ), patch.object(executor, "log", side_effect=lambda msg: log_messages.append(msg)):
                executor._run_step_callback(provider_cb, {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"})
                executor._run_step_callback(_noarg, {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"})
                executor._run_step_callback("echo {step_id}", {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"})
                executor._run_step_callback(b"echo bytes", {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"})
                executor._run_step_callback(dict_provider, {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"})
                executor._run_step_callback(dict_command, {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "gpu"})
                executor._run_step_callback({"ignored": True}, {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"})
                executor._run_step_callback(lambda context: (_ for _ in ()).throw(RuntimeError("boom")), {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"})

            self.assertGreaterEqual(len(provider_calls), 2)
            self.assertEqual(len(shell_calls), 3)
            self.assertTrue(any("Callback execution failed" in msg for msg in log_messages))

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")) as mocked_shell, patch.object(
                executor,
                "_provider_host",
                side_effect=lambda host: f"resolved:{host}",
            ):
                executor._run_provider_or_shell_callback(
                    {"command": "echo {step_id}", "host": b"gpu", "timeout": 0, "cwd": "{step_id}", "env": {"K": "{try_number}"}},
                    {"step_id": "s1", "step_num": 1, "try_number": 2, "callback_host": "local"},
                )
            self.assertEqual(mocked_shell.call_args.kwargs, {})
            params = mocked_shell.call_args.args[0]
            self.assertEqual(params["command"], "echo s1")
            self.assertEqual(params["host"], "resolved:gpu")
            self.assertEqual(params["timeout"], 30)
            self.assertEqual(params["cwd"], "s1")
            self.assertEqual(params["env"], {"K": "2"})

            with patch.object(executor, "_exec_provider_shell", return_value=(False, "boom")), patch.object(
                executor, "log"
            ) as mocked_log:
                executor._run_provider_or_shell_callback(
                    {"command": "echo hi", "host": None},
                    {"step_id": "s1", "step_num": 1, "try_number": 1, "callback_host": "local"},
                )
            mocked_log.assert_called()


class ExecSupportAndNotifyEdgeTests(unittest.TestCase):
    def test_support_wrappers_interpolation_and_notify_helpers(self):
        with isolated_executor(RecipeModel(name="edge-support")) as (executor, _config_dir):
            events = []
            executor.logger = SimpleNamespace(log_detail=lambda *args: events.append(args))
            executor._log_detail("demo", "msg", {"x": 1})
            self.assertEqual(events[0][0], "demo")
            executor.logger = None
            executor._log_detail("demo", "msg", {"x": 1})

            window = SimpleNamespace(name="main", host="local", remote_session="sess")
            with patch.object(executor.bridge_exec, "build_bridge_attach_command", return_value="attach"), patch.object(
                executor.bridge_exec, "ensure_bridge_window"
            ) as mocked_ensure, patch.object(executor.bridge_exec, "restore_tmux_bridge") as mocked_restore, patch.object(
                executor.bridge_exec, "wait_for_bridge_idle", return_value=(True, "idle")
            ), patch.object(executor.bridge_exec, "exec_via_bridge", return_value=(True, "ok")):
                self.assertEqual(executor._build_bridge_attach_command(window), "attach")
                executor._ensure_bridge_window(window)
                executor.restore_tmux_bridge()
                self.assertEqual(executor._wait_for_bridge_idle("main", "%1", 5), (True, "idle"))
                self.assertEqual(executor._exec_via_bridge(window, "echo hi", 5, False, 0), (True, "ok"))
            mocked_ensure.assert_called_once()
            mocked_restore.assert_called_once()

            with patch.object(executor.tmux_control, "cmd_tmux_open", return_value=(True, "open")), patch.object(
                executor.tmux_control, "cmd_tmux_close", return_value=(True, "close")
            ), patch.object(
                executor.tmux_control, "cmd_tmux_config", return_value=(True, "cfg")
            ), patch.object(
                executor.execute_helper, "exec_execute", return_value=(True, "exec")
            ), patch.object(
                executor.execute_helper, "tmux_send_keys"
            ) as mocked_send, patch.object(
                executor.execute_helper, "tmux_wait_for_signal", return_value=True
            ), patch.object(
                executor.transfer_helper, "exec_transfer", return_value=(True, "transfer")
            ), patch.object(
                executor.wait_helper, "run_tmux_cmd", return_value="run"
            ), patch.object(
                executor.wait_helper, "get_pane_recent_output", return_value="out"
            ), patch.object(
                executor.wait_helper, "is_pane_idle", return_value=True
            ), patch.object(
                executor.wait_helper, "get_pane_process_info", return_value=("bash", "tree")
            ), patch.object(
                executor.wait_helper, "wait_for_idle", return_value=(True, "idle")
            ), patch.object(
                executor.wait_helper, "exec_wait", return_value=(True, "wait")
            ):
                self.assertEqual(executor._cmd_tmux_open([]), (True, "open"))
                self.assertEqual(executor._cmd_tmux_close([]), (True, "close"))
                self.assertEqual(executor._cmd_tmux_config([]), (True, "cfg"))
                self.assertEqual(executor._exec_execute(SimpleNamespace()), (True, "exec"))
                executor._tmux_send_keys("local", "sess", "echo hi")
                self.assertTrue(executor._tmux_wait_for_signal("local", "sig"))
                self.assertEqual(executor._exec_transfer(SimpleNamespace()), (True, "transfer"))
                self.assertEqual(executor._run_tmux_cmd("local", "cmd"), "run")
                self.assertEqual(executor._get_pane_recent_output("local", "sess"), "out")
                self.assertTrue(executor._is_pane_idle("local", "sess"))
                self.assertEqual(executor._get_pane_process_info("local", "sess"), ("bash", "tree"))
                self.assertEqual(executor._wait_for_idle(window, 5), (True, "idle"))
                self.assertEqual(executor._exec_wait(SimpleNamespace()), (True, "wait"))
            mocked_send.assert_called_once()

            executor.notify_enabled = False
            ok, msg = executor._cmd_notify(["hello"])
            self.assertTrue(ok)
            self.assertIn("skipped", msg)
            executor.notify_enabled = True
            ok, msg = executor._cmd_notify([])
            self.assertFalse(ok)
            with patch.object(executor.notifier, "notify", return_value=(True, "sent")):
                ok, msg = executor._cmd_notify(["hello", "$NAME"])
            self.assertTrue(ok)
            self.assertEqual(msg, "sent")

            with patch.object(executor.vast_control, "cmd_vast_start", return_value=(True, "start")), patch.object(
                executor.vast_control, "cmd_vast_stop", return_value=(True, "stop")
            ), patch.object(
                executor.vast_control, "cmd_vast_pick", return_value=(True, "pick")
            ), patch.object(
                executor.vast_control, "cmd_vast_wait", return_value=(True, "wait")
            ), patch.object(
                executor.vast_control, "verify_ssh_connection", return_value=True
            ), patch.object(
                executor.vast_control, "ensure_ssh_key_attached"
            ) as mocked_attach, patch.object(
                executor.vast_control, "cmd_vast_cost", return_value=(True, "cost")
            ):
                self.assertEqual(executor._cmd_vast_start([]), (True, "start"))
                self.assertEqual(executor._cmd_vast_stop([]), (True, "stop"))
                self.assertEqual(executor._cmd_vast_pick([]), (True, "pick"))
                self.assertEqual(executor._cmd_vast_wait([]), (True, "wait"))
                self.assertTrue(executor._verify_ssh_connection("gpu"))
                executor._ensure_ssh_key_attached(object(), "~/.ssh/id")
                self.assertEqual(executor._cmd_vast_cost([]), (True, "cost"))
            mocked_attach.assert_called_once()

            with patch("trainsh.core.executor_support.time.sleep") as mocked_sleep:
                ok, msg = executor._cmd_sleep(["2s"])
            self.assertTrue(ok)
            mocked_sleep.assert_called_once_with(2)
            ok, msg = executor._cmd_sleep([])
            self.assertFalse(ok)
            self.assertIn("Usage: sleep", msg)

            executor.recipe.hosts["gpu"] = "vast:123"
            with patch("trainsh.core.executor_support._resolve_vast_host", return_value="gpu-host"):
                self.assertEqual(executor._resolve_host("@gpu"), "gpu-host")
            self.assertIsNone(executor._resolve_window("missing"))
            executor.allow_host_execute = True
            with patch("trainsh.core.executor_support._resolve_vast_host", return_value="gpu-host"):
                resolved = executor._resolve_window("gpu")
            self.assertEqual(resolved.host, "gpu-host")

            executor.ctx.variables["TOKEN"] = "${secret:API_KEY}"
            executor.ctx.variables["NAME"] = "demo"
            executor.secrets.get = lambda name: "sekret" if name == "API_KEY" else ""
            self.assertEqual(executor._interpolate("https://${TOKEN}-$NAME"), "https://sekret-demo")

            executor.recipe.storages = {"artifacts": {"path": "/tmp/out"}}
            self.assertEqual(executor._storage_snapshot(), {"artifacts": {"path": "/tmp/out"}})
            self.assertEqual(executor._parse_duration("1h"), 3600)
            self.assertEqual(executor._parse_duration("2m"), 120)
            self.assertEqual(executor._parse_duration("3s"), 3)
            self.assertEqual(executor._parse_duration("4"), 4)

    def test_notify_python_and_vast_provider_edges(self):
        with isolated_executor(RecipeModel(name="edge-notify")) as (executor, _config_dir):
            ok, msg = executor._exec_provider_set_var({"name": "A", "value": None})
            self.assertTrue(ok)
            self.assertEqual(executor.ctx.variables["A"], "")
            ok, msg = executor._exec_provider_set_var({})
            self.assertFalse(ok)

            ok, msg = executor._exec_provider_notice("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_notice({"body": "body-only", "channels": ["log"]})
            self.assertIn(ok, {True, False})
            ok, msg = executor._exec_provider_notice({"message": "x", "channels": object()})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_notice({"message": "x", "timeout": "bad"})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_notice({"message": "x", "fail_on_error": "bad-bool"})
            self.assertFalse(ok)

            with patch.object(executor.notifier, "notify", return_value=(True, "sent")):
                ok, msg = executor._exec_provider_notice(
                    {
                        "text": "hello",
                        "subject": "subj",
                        "channels": ["log"],
                        "webhook": "https://hook",
                        "cmd": "echo ok",
                        "timeout_secs": 0,
                        "fail_on_error": False,
                    }
                )
            self.assertTrue(ok)
            self.assertEqual(msg, "sent")

            ok, msg = executor._exec_provider_empty({})
            self.assertTrue(ok)
            self.assertEqual(msg, "noop")

            ok, msg = executor._exec_provider_python("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_python({})
            self.assertFalse(ok)
            with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")) as mocked_shell:
                self.assertTrue(executor._exec_provider_python({"code": "print(1)"})[0])
                self.assertIn("python - <<'PY'", mocked_shell.call_args.args[0]["command"])
                self.assertTrue(executor._exec_provider_python({"script": "demo.py"})[0])
                self.assertIn("python demo.py", mocked_shell.call_args.args[0]["command"])
                self.assertTrue(executor._exec_provider_python({"command": "print(1)"})[0])
                self.assertIn("python -c", mocked_shell.call_args.args[0]["command"])

            ok, msg = executor._exec_provider_vast("launch", {})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_vast("start", "bad")
            self.assertFalse(ok)
            with patch.object(executor, "_cmd_vast_start", return_value=(True, "start")) as mocked_start, patch.object(
                executor, "_cmd_vast_pick", return_value=(True, "pick")
            ) as mocked_pick, patch.object(
                executor, "_cmd_vast_wait", return_value=(True, "wait")
            ) as mocked_wait, patch.object(
                executor, "_cmd_vast_cost", return_value=(True, "cost")
            ) as mocked_cost:
                self.assertEqual(executor._exec_provider_vast("start", {"instance_id": "123"}), (True, "start"))
                self.assertEqual(
                    executor._exec_provider_vast(
                        "pick",
                        {"host": "@gpu", "gpu": "A100", "num_gpus": 2, "skip_if_set": "READY"},
                    ),
                    (True, "pick"),
                )
                self.assertEqual(
                    executor._exec_provider_vast("wait", {"timeout": "5s", "poll_interval": "2s", "stop_on_fail": True}),
                    (True, "wait"),
                )
                self.assertEqual(executor._exec_provider_vast("cost", {"id": "123"}), (True, "cost"))
            mocked_start.assert_called_once()
            mocked_pick.assert_called_once()
            mocked_wait.assert_called_once()
            mocked_cost.assert_called_once()


class RunRecipeEdgeTests(unittest.TestCase):
    def test_run_recipe_validates_resume_merges_and_restores(self):
        fake_recipe = SimpleNamespace(
            executor_kwargs={"max_workers": 2, "pool_slots": {"default": 1}},
            callbacks=["sqlite", "console"],
            executor="thread_pool",
            variables={"A": "1"},
            hosts={"gpu": "local"},
            storages={},
            name="demo",
        )
        saved_state = SimpleNamespace(
            job_id="job-1",
            current_step=1,
            total_steps=3,
            variables={"OLD": "2"},
            hosts={"gpu": "local"},
            bridge_session="bridge-1",
            next_window_index=4,
            window_sessions={"gpu": "sess-1"},
        )
        runtime_executor_calls = {}

        class FakeExecutor:
            def __init__(self, recipe_obj, **kwargs):
                runtime_executor_calls["recipe"] = recipe_obj
                runtime_executor_calls["kwargs"] = kwargs
                self.ctx = SimpleNamespace(next_window_index=0, windows={})
                self.restore_tmux_bridge = MagicMock()

            def execute(self, resume_from=0):
                runtime_executor_calls["resume_from"] = resume_from
                runtime_executor_calls["windows"] = dict(self.ctx.windows)
                runtime_executor_calls["next_window_index"] = self.ctx.next_window_index
                return True

        manager = SimpleNamespace(find_resumable=lambda path: saved_state, load=lambda job_id: saved_state)

        class FakeRuntimeExec:
            def execute(self, fn):
                return fn()

        with patch("trainsh.pyrecipe.load_python_recipe", return_value=fake_recipe), patch(
            "trainsh.runtime.build_sinks", return_value=["console-sink"]
        ) as mocked_build_sinks, patch(
            "trainsh.runtime.get_executor", return_value=FakeRuntimeExec()
        ) as mocked_get_executor, patch(
            "trainsh.runtime.SqliteCallbackSink", return_value="sqlite-sink"
        ), patch(
            "trainsh.core.executor_main.DSLExecutor", FakeExecutor
        ), patch(
            "trainsh.core.executor_main.JobStateManager", return_value=manager
        ), patch(
            "trainsh.core.executor_main.get_window_session_name", return_value="generated-sess"
        ):
            ok = run_recipe(
                "/tmp/demo.py",
                var_overrides={"NEW": "3"},
                resume=True,
                initial_session_index=2,
                executor_kwargs={"max_workers": 8},
                callbacks=["sqlite,console"],
                run_type="scheduled",
            )
        self.assertTrue(ok)
        mocked_build_sinks.assert_called_once()
        mocked_get_executor.assert_called_once_with("thread_pool", max_workers=8, pool_slots={"default": 1})
        self.assertEqual(runtime_executor_calls["resume_from"], 1)
        self.assertEqual(fake_recipe.variables["OLD"], "2")
        self.assertEqual(fake_recipe.variables["NEW"], "3")
        self.assertEqual(runtime_executor_calls["next_window_index"], 4)
        self.assertIn("gpu", runtime_executor_calls["windows"])
        self.assertEqual(runtime_executor_calls["kwargs"]["bridge_session"], "bridge-1")
        self.assertEqual(runtime_executor_calls["kwargs"]["run_type"], "scheduled")
        self.assertEqual(runtime_executor_calls["kwargs"]["callback_sinks"], ["sqlite-sink", "console-sink"])

    def test_run_recipe_validation_and_host_override_paths(self):
        with self.assertRaises(ValueError):
            run_recipe("/tmp/demo.txt")
        with self.assertRaises(ValueError):
            run_recipe("/tmp/demo.py", resume=True, host_overrides={"gpu": "local"})

        fake_recipe = SimpleNamespace(
            executor_kwargs={},
            callbacks=[],
            executor="",
            variables={},
            hosts={},
            storages={},
            name="demo",
        )

        class FakeExecutor:
            def __init__(self, recipe_obj, **kwargs):
                self.recipe_obj = recipe_obj
                self.ctx = SimpleNamespace(next_window_index=0, windows={})

            def execute(self, resume_from=0):
                return True

        class FakeRuntimeExec:
            def execute(self, fn):
                return fn()

        manager = SimpleNamespace(find_resumable=lambda path: None, load=lambda job_id: None)

        with patch("trainsh.pyrecipe.load_python_recipe", return_value=fake_recipe), patch(
            "trainsh.runtime.build_sinks", return_value=[]
        ), patch(
            "trainsh.runtime.get_executor", return_value=FakeRuntimeExec()
        ) as mocked_get_executor, patch(
            "trainsh.runtime.SqliteCallbackSink", return_value="sqlite-sink"
        ), patch(
            "trainsh.core.executor_main.DSLExecutor", FakeExecutor
        ), patch(
            "trainsh.core.executor_main.JobStateManager", return_value=manager
        ):
            ok = run_recipe(
                "/tmp/demo.py",
                host_overrides={"gpu": "vast:123"},
                callback_sinks=["extra"],
                job_id="job-2",
                executor_name="sequential",
            )
        self.assertTrue(ok)
        self.assertEqual(fake_recipe.hosts["gpu"], "vast:123")
        self.assertEqual(fake_recipe.variables["VAST_ID"], "123")
        mocked_get_executor.assert_called_once_with("sequential")


class ExecDependencyEdgeTests(unittest.TestCase):
    def _fake_pool_manager(self):
        return SimpleNamespace(
            refresh=lambda: {"default": SimpleNamespace(occupied=0)},
            try_acquire=lambda pool: True,
            release=lambda pool: None,
            close=lambda: None,
        )

    def test_execute_with_dependencies_handles_deferrable_skip_and_unsatisfied(self):
        wait_step = ProviderStep("util", "wait_condition", {"condition": "var:READY==1"}, id="wait")
        wait_step.deferrable = True
        with isolated_executor(RecipeModel(name="deps", steps=[wait_step]), executor_name="thread_pool") as (executor, _config_dir):
            events = queue.Queue()

            class FakeTriggerer:
                def __init__(self):
                    self.events = events

                def start(self):
                    return None

                def stop(self):
                    return None

                def submit(self, *, step_id, check_fn, timeout, poll_interval):
                    self.events.put(SimpleNamespace(step_id=step_id, status="success", message="done"))
                    return "task-1"

            executor._triggerer = FakeTriggerer()
            executor._pool_manager = self._fake_pool_manager()

            with patch.object(executor, "_save_checkpoint"), patch.object(
                executor, "_emit_step_start"
            ) as mocked_start, patch.object(
                executor, "_emit_step_end"
            ) as mocked_end, patch.object(
                executor, "_run_step_callbacks"
            ) as mocked_callbacks:
                ok = executor._execute_with_dependencies()
            self.assertTrue(ok)
            mocked_start.assert_called()
            mocked_end.assert_called()
            mocked_callbacks.assert_called()

        empty_step = ProviderStep("util", "empty", {}, id="a")
        with isolated_executor(RecipeModel(name="deps-skip", steps=[empty_step]), executor_name="thread_pool") as (executor, _config_dir):
            executor._triggerer = SimpleNamespace(start=lambda: None, stop=lambda: None, events=queue.Queue())
            executor._pool_manager = self._fake_pool_manager()
            executor._ti_dependency_evaluator = SimpleNamespace(
                evaluate=lambda node, context: SimpleNamespace(met=False, trigger_rule_failed=True)
            )
            executor.logger = SimpleNamespace(log_detail=lambda *a, **k: None)
            with patch.object(executor, "_emit_step_end") as mocked_end:
                ok = executor._execute_with_dependencies()
            self.assertTrue(ok)
            mocked_end.assert_called()

        with isolated_executor(RecipeModel(name="deps-blocked", steps=[empty_step]), executor_name="thread_pool") as (executor, _config_dir):
            executor._triggerer = SimpleNamespace(start=lambda: None, stop=lambda: None, events=queue.Queue())
            executor._pool_manager = self._fake_pool_manager()
            executor._ti_dependency_evaluator = SimpleNamespace(
                evaluate=lambda node, context: SimpleNamespace(met=False, trigger_rule_failed=False)
            )
            logged = []
            executor.log = lambda msg: logged.append(msg)
            ok = executor._execute_with_dependencies()
            self.assertFalse(ok)
            self.assertTrue(any("Dependency cycle or unsatisfiable trigger rules" in msg for msg in logged))

    def test_execute_with_dependencies_retry_and_exception_worker_paths(self):
        retry_step = ProviderStep("util", "empty", {}, id="retry")
        retry_step.retries = 1
        with isolated_executor(RecipeModel(name="deps-retry", steps=[retry_step]), executor_name="thread_pool") as (executor, _config_dir):
            executor._triggerer = SimpleNamespace(start=lambda: None, stop=lambda: None, events=queue.Queue())
            executor._pool_manager = self._fake_pool_manager()
            with patch.object(
                executor,
                "_run_single_step_with_state",
                side_effect=[
                    (TaskInstanceState.FAILED, "boom", 10),
                    (TaskInstanceState.SUCCESS, "ok", 20),
                ],
            ), patch.object(executor, "_save_checkpoint"), patch.object(
                executor, "_emit_step_start"
            ), patch.object(
                executor, "_emit_step_end"
            ) as mocked_end, patch.object(
                executor, "_run_step_callbacks"
            ) as mocked_callbacks:
                ok = executor._execute_with_dependencies()
            self.assertTrue(ok)
            self.assertTrue(mocked_end.called)
            self.assertTrue(mocked_callbacks.called)

        fail_step = ProviderStep("util", "empty", {}, id="fail")
        fail_step.continue_on_failure = True
        with isolated_executor(RecipeModel(name="deps-exc", steps=[fail_step]), executor_name="thread_pool") as (executor, _config_dir):
            executor._triggerer = SimpleNamespace(start=lambda: None, stop=lambda: None, events=queue.Queue())
            executor._pool_manager = self._fake_pool_manager()
            with patch.object(
                executor,
                "_run_single_step_with_state",
                side_effect=RuntimeError("worker boom"),
            ), patch.object(executor, "_save_checkpoint"), patch.object(
                executor, "_emit_step_start"
            ), patch.object(
                executor, "_emit_step_end"
            ) as mocked_end, patch.object(
                executor, "_run_step_callbacks"
            ) as mocked_callbacks:
                ok = executor._execute_with_dependencies()
            self.assertTrue(ok)
            self.assertTrue(mocked_end.called)
            self.assertTrue(mocked_callbacks.called)

    def test_step_runtime_emit_and_timeout_misc_paths(self):
        with isolated_executor(RecipeModel(name="steps")) as (executor, _config_dir):
            node = _StepNode(step_num=1, step_id="wait", step=ProviderStep("util", "wait_condition", {"condition": ""}, id="wait"), depends_on=[])
            self.assertIsNone(executor._build_defer_check(node, step_id="wait", attempt=1))
            bad_step = ProviderStep("util", "wait_condition", {"condition": "var:X", "timeout": "bad"}, id="wait2")
            node2 = _StepNode(step_num=2, step_id="wait2", step=bad_step, depends_on=[])
            with patch.object(executor, "log") as mocked_log:
                self.assertIsNone(executor._build_defer_check(node2, step_id="wait2", attempt=1))
            mocked_log.assert_called()

            logger = SimpleNamespace(step_start=MagicMock(), step_output=MagicMock(), step_end=MagicMock())
            executor.logger = logger
            executor._emit_step_start(_StepNode(step_num=1, step_id="x", step=ProviderStep("util", "empty", {}, id="x"), depends_on=[]), "x", try_number=1)
            executor._emit_step_end(_StepNode(step_num=1, step_id="x", step=ProviderStep("util", "empty", {}, id="x"), depends_on=[]), "x", state="success", success=True, duration_ms=1, output="ok")
            logger.step_start.assert_called()

            with patch.object(executor, "_execute_step", return_value=(True, "ok")), patch.object(executor, "_set_active_step_context") as mocked_set, patch.object(
                executor, "_clear_active_step_context"
            ) as mocked_clear:
                ok, output = executor._execute_step_with_timeout(ProviderStep("util", "empty", {}, id="x"), timeout_secs=0, step_id="x", step_num=1, try_number=1)
            self.assertTrue(ok)
            mocked_set.assert_called_once()
            mocked_clear.assert_called_once()

            node = _StepNode(step_num=1, step_id="x", step=ProviderStep("util", "empty", {}, id="x"), depends_on=[], retries=1, retry_delay=0)
            with patch.object(executor, "_run_single_step", side_effect=[(False, "boom", 1), (False, "boom2", 2)]), patch.object(
                executor, "_run_step_callbacks"
            ) as mocked_callbacks, patch.object(executor, "log") as mocked_log:
                ok, output, duration = executor._run_single_step_with_retries(node, step_id="x")
            self.assertFalse(ok)
            mocked_callbacks.assert_called()
            mocked_log.assert_called()

    def test_dependency_helpers_misc_paths(self):
        with isolated_executor(RecipeModel(name="deps-misc")) as (executor, _config_dir):
            executor.max_workers = 3
            self.assertEqual(executor._parse_pool_limits("bad"), {"default": 3})
            self.assertEqual(executor._parse_pool_limits({"gpu": 2}), {"gpu": 2, "default": 3})
            self.assertEqual(executor._parse_pool_limits({"default": 5}), {"default": 5})
            executor._pool_limits = {"default": 3}
            self.assertEqual(executor._pool_limit("gpu"), 3)

        step = ProviderStep("util", "empty", {}, id="done")
        with isolated_executor(RecipeModel(name="deps-resume", steps=[step]), executor_name="thread_pool") as (executor, _config_dir):
            executor._triggerer = SimpleNamespace(start=lambda: None, stop=lambda: None, events=queue.Queue())
            executor._pool_manager = self._fake_pool_manager()
            ok = executor._execute_with_dependencies(resume_from=1)
            self.assertTrue(ok)

        with isolated_executor(RecipeModel(name="deps-empty", steps=[]), executor_name="thread_pool") as (executor, _config_dir):
            executor._triggerer = SimpleNamespace(start=lambda: None, stop=lambda: None, events=queue.Queue())
            executor._pool_manager = self._fake_pool_manager()
            ok = executor._execute_with_dependencies()
            self.assertTrue(ok)

        retry_step = ProviderStep("util", "empty", {}, id="retry-late")
        retry_step.retries = 1
        with isolated_executor(RecipeModel(name="deps-backoff", steps=[retry_step]), executor_name="thread_pool") as (executor, _config_dir):
            executor._triggerer = SimpleNamespace(start=lambda: None, stop=lambda: None, events=queue.Queue())
            executor._pool_manager = SimpleNamespace(
                refresh=lambda: {"default": SimpleNamespace(occupied=0)},
                try_acquire=lambda pool: False,
                release=lambda pool: None,
                close=lambda: None,
            )
            executor._ti_dependency_evaluator = SimpleNamespace(
                evaluate=lambda node, context: SimpleNamespace(met=True, trigger_rule_failed=False)
            )
            logs = []
            executor.log = lambda msg: logs.append(msg)
            with patch("trainsh.core.executor_dependencies.time.time", side_effect=[0, 0, 2, 2, 2]), patch(
                "trainsh.core.executor_dependencies.time.sleep"
            ):
                ok = executor._execute_with_dependencies()
            self.assertFalse(ok)
            self.assertTrue(any("Dependency cycle or unsatisfiable trigger rules" in msg for msg in logs))


if __name__ == "__main__":
    unittest.main()
