import os
import sqlite3
import tempfile
import textwrap
import unittest
from contextlib import closing
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.commands.recipe import cmd_rm
from trainsh.commands.recipe_runtime import _show_execution_details, _show_job_details, cmd_run
from trainsh.commands.recipe_templates import get_recipe_template
from trainsh.commands.runtime_dispatch import run_recipe_via_dag
from trainsh.core.dag_executor import DagExecutor
from trainsh.core.dag_processor import DagProcessor, ParsedDag, parse_schedule
from trainsh.core.execution_log import ExecutionLogReader
from trainsh.core.executor_main import run_recipe
from trainsh.core.job_state import JobStateManager
from trainsh import Recipe, Storage, load_python_recipe
from trainsh.pyrecipe.base import RecipeSpec
from trainsh.pyrecipe.models import ProviderStep
from trainsh.runtime_executors import (
    AirflowExecutor,
    CeleryExecutor,
    DaskExecutor,
    DebugExecutor,
    ProcessPoolExecutor,
    SequentialExecutor,
    get_executor,
    normalize_executor_name,
)


class PythonRecipeLoaderTests(unittest.TestCase):
    def test_load_python_recipe_uses_public_api_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "demo_recipe.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh import Recipe, Storage

                    with Recipe(
                        "demo-pipeline",
                        executor="thread_pool",
                        workers=3,
                        callbacks=["console"],
                    ) as recipe:
                        recipe.empty(id="start")
                    """
                ),
                encoding="utf-8",
            )

            loaded = load_python_recipe(str(recipe_path))

        self.assertIsInstance(loaded, RecipeSpec)
        self.assertEqual(loaded.name, "demo-pipeline")
        self.assertEqual(loaded.executor, "thread_pool")
        self.assertEqual(loaded.executor_kwargs, {"max_workers": 3})
        self.assertEqual(loaded.callbacks, ["console"])
        self.assertEqual(loaded.step_count(), 1)
        self.assertIsInstance(loaded.steps[0], ProviderStep)
        self.assertEqual(loaded.steps[0].provider, "util")
        self.assertEqual(loaded.steps[0].operation, "empty")

    def test_load_python_recipe_requires_declared_recipe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "invalid_recipe.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh import Recipe, Storage
                    """
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "no recipe defined"):
                load_python_recipe(str(recipe_path))

    def test_load_python_recipe_does_not_collect_uppercase_assignments_implicitly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "vars_recipe.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from pathlib import Path
                    from trainsh import Recipe, Storage

                    recipe = Recipe("vars-demo")

                    VAST_ID = 32631353
                    CAPTURE = Path("/tmp/stage20_train_pane.txt")

                    recipe.empty(id="start")
                    """
                ),
                encoding="utf-8",
            )

            loaded = load_python_recipe(str(recipe_path))

        self.assertEqual(loaded.variables, {})


class PythonRecipeBuilderTests(unittest.TestCase):
    def test_builder_normalizes_new_runtime_helpers_and_defaults(self):
        success_callback = lambda ctx=None: ctx
        failure_callback = {"provider": "util", "operation": "notice"}
        artifacts = Storage("r2:bucket", name="artifacts")

        dag = Recipe("builder-demo", executor="thread_pool", executor_kwargs={"concurrency": "7"})
        dag.defaults(
            max_retries=3,
            retry_delay="5s",
            pool="io",
            execution_timeout="2m",
            retry_exponential_backoff=True,
            on_success=success_callback,
            on_failure=failure_callback,
        )

        start = dag.http_post(
            "https://example.com/notify",
            json_body={"ok": True},
            headers={},
            capture_var="response",
            id="start",
        )
        latest = dag.latest_only(message="newer run exists", fail_if_unknown=False, depends_on=[start], id="latest")
        gate = dag.skip_if_not("var:READY==1", host="@gpu", depends_on=[latest], id="gate")
        wait_storage = dag.storage_wait(
            artifacts.path("/done.txt"),
            timeout="10m",
            poll_interval="15s",
            depends_on=[gate],
            id="wait_storage",
            step_options={"trigger_rule": "none_failed"},
        )
        query = dag.xcom_push(
            "answer",
            value={"rows": [1]},
            depends_on=[wait_storage],
            id="query",
        )
        pull = dag.xcom_pull(
            "answer",
            task_ids="task_a, task_b",
            decode_json=True,
            depends_on=[query],
            id="pull",
        )
        join = dag.join(depends_on=[pull], id="join")
        branch = dag.branch(
            "var:FLAG==1",
            true_value="go",
            false_value="stop",
            variable="route",
            depends_on=[join],
            id="branch",
        )

        self.assertEqual([start, latest, gate, wait_storage, query, pull, join, branch], [step.id for step in dag.steps])

        steps = {step.id: step for step in dag.steps}
        start_step = steps["start"]
        self.assertEqual(start_step.provider, "http")
        self.assertEqual(start_step.operation, "post")
        self.assertEqual(start_step.params["method"], "POST")
        self.assertEqual(start_step.params["headers"]["Content-Type"], "application/json")
        self.assertEqual(start_step.params["capture_var"], "response")
        self.assertEqual(start_step.retries, 3)
        self.assertEqual(start_step.retry_delay, 5)
        self.assertEqual(start_step.pool, "io")
        self.assertEqual(start_step.execution_timeout, 120)
        self.assertEqual(start_step.retry_exponential_backoff, 2.0)
        self.assertEqual(start_step.on_success, [success_callback])
        self.assertEqual(start_step.on_failure, [failure_callback])

        latest_step = steps["latest"]
        self.assertEqual(latest_step.provider, "util")
        self.assertEqual(latest_step.operation, "latest_only")
        self.assertEqual(latest_step.params["message"], "newer run exists")
        self.assertEqual(latest_step.depends_on, ["start"])

        gate_step = steps["gate"]
        self.assertEqual(gate_step.provider, "util")
        self.assertEqual(gate_step.operation, "short_circuit")
        self.assertTrue(gate_step.params["invert"])
        self.assertEqual(gate_step.params["host"], "@gpu")

        wait_step = steps["wait_storage"]
        self.assertEqual(wait_step.provider, "storage")
        self.assertEqual(wait_step.operation, "wait")
        self.assertEqual(wait_step.params["storage"], "artifacts")
        self.assertEqual(wait_step.params["path"], "/done.txt")
        self.assertEqual(wait_step.trigger_rule, "none_failed")
        self.assertEqual(dag.storages["artifacts"], "r2:bucket")

        query_step = steps["query"]
        self.assertEqual(query_step.provider, "util")
        self.assertEqual(query_step.operation, "xcom_push")
        self.assertEqual(query_step.params["key"], "answer")

        pull_step = steps["pull"]
        self.assertEqual(pull_step.provider, "util")
        self.assertEqual(pull_step.operation, "xcom_pull")
        self.assertEqual(pull_step.params["task_ids"], ["task_a", "task_b"])
        self.assertTrue(pull_step.params["decode_json"])

        join_step = steps["join"]
        self.assertEqual(join_step.provider, "util")
        self.assertEqual(join_step.operation, "empty")
        self.assertEqual(join_step.trigger_rule, "all_done")

        branch_step = steps["branch"]
        self.assertEqual(branch_step.provider, "util")
        self.assertEqual(branch_step.operation, "branch")
        self.assertEqual(branch_step.params["true_value"], "go")
        self.assertEqual(branch_step.params["false_value"], "stop")
        self.assertEqual(branch_step.params["variable"], "route")
        self.assertEqual(branch_step.depends_on, ["join"])

    def test_builder_supports_namespace_api_assignment_and_chain_style_dependencies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "capture_stage20.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from pathlib import Path
                    from trainsh import Recipe, VastHost

                    recipe = Recipe("capture-stage20")

                    session_name = "train_train_qwen3_coder_next_fullbase_repair_assignments_compact_priority"
                    capture_path = Path("/tmp/stage20_train_pane.txt")
                    local_capture = Path("./artifacts/remote/logs/stage20_train_pane.txt")
                    gpu = VastHost("32631353")

                    recipe.vast.start(gpu)
                    recipe.vast.wait_ready(gpu, timeout="5m")
                    with gpu.tmux("work") as tmux:
                        tmux.capture_pane(target=session_name, lines=400, output=capture_path)
                        recipe.copy(gpu.path(capture_path), local_capture)
                        recipe.notify("Captured stage20 train pane")
                    """
                ),
                encoding="utf-8",
            )

            loaded = load_python_recipe(str(recipe_path))

        self.assertIn("vast:32631353", list(loaded.hosts.values()))
        self.assertEqual(loaded.step_count(), 7)

        steps = {step.id: step for step in loaded.steps}
        self.assertEqual(steps["step_002"].depends_on, ["step_001"])
        self.assertEqual(steps["step_003"].depends_on, ["step_002"])
        self.assertEqual(steps["step_004"].depends_on, ["step_003"])
        self.assertEqual(steps["step_005"].depends_on, ["step_004"])
        self.assertEqual(steps["step_006"].depends_on, ["step_005"])
        self.assertEqual(set(steps["step_007"].depends_on), {"step_003", "step_006"})


class RuntimeExecutorAliasTests(unittest.TestCase):
    def test_executor_aliases_resolve_to_compatible_runtime_classes(self):
        self.assertEqual(normalize_executor_name("Airflow Executor"), "airflowexecutor")

        sequential = get_executor("sync")
        debug = get_executor("noop")
        airflow = get_executor("local_executor", concurrency="7")
        celery = get_executor("celery", worker_count="3")
        dask = get_executor("dask_executor", parallelism="5")
        process_pool = get_executor("process pool executor", workers="2")

        self.assertIsInstance(sequential, SequentialExecutor)
        self.assertIsInstance(debug, DebugExecutor)
        self.assertIsInstance(airflow, AirflowExecutor)
        self.assertEqual(airflow.max_workers, 7)
        self.assertIsInstance(celery, CeleryExecutor)
        self.assertEqual(celery.max_workers, 3)
        self.assertIsInstance(dask, DaskExecutor)
        self.assertEqual(dask.max_workers, 5)
        self.assertIsInstance(process_pool, ProcessPoolExecutor)
        self.assertEqual(process_pool.max_workers, 2)

        with self.assertRaisesRegex(ValueError, "kubernetes"):
            get_executor("kubernetes_executor")


class DagProcessorPythonRecipeTests(unittest.TestCase):
    def test_discovers_python_recipe_metadata_and_loads_recipe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "scheduled_recipe.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh import Recipe, Storage

                    recipe = Recipe(
                        "scheduled-demo",
                        schedule="@every 5m",
                        tags=["gpu", "nightly"],
                        paused=True,
                        callbacks=["console"],
                        executor="airflow",
                        executor_kwargs={"parallelism": 6},
                    )
                    recipe.empty(id="start")
                    """
                ),
                encoding="utf-8",
            )

            processor = DagProcessor([tmpdir])
            dags = processor.discover_dags()
            self.assertEqual(len(dags), 1)
            dag = dags[0]
            loaded = dag.load_recipe()

        self.assertEqual(dag.recipe_name, "scheduled-demo")
        self.assertEqual(dag.schedule, "@every 5m")
        self.assertEqual(dag.schedule_meta.kind, "interval")
        self.assertEqual(dag.schedule_meta.interval_seconds, 300)
        self.assertTrue(dag.is_paused)
        self.assertEqual(dag.tags, ["gpu", "nightly"])
        self.assertEqual(dag.callbacks, ["console"])
        self.assertEqual(dag.executor, "airflow")
        self.assertEqual(dag.executor_kwargs, {"parallelism": 6})
        self.assertTrue(dag.is_valid)
        self.assertIsInstance(loaded, RecipeSpec)
        self.assertEqual(loaded.name, "scheduled-demo")
        self.assertEqual(loaded.step_count(), 1)

    def test_discovers_metadata_from_context_manager_recipe_definition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "context_recipe.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh import Recipe

                    with Recipe(
                        "context-demo",
                        schedule="@every 15m",
                        owner="ml",
                        tags=["nightly"],
                        executor="thread_pool",
                        executor_kwargs={"max_workers": 3},
                        callbacks=["console"],
                    ) as recipe:
                        recipe.empty(id="start")
                    """
                ),
                encoding="utf-8",
            )

            dag = DagProcessor([tmpdir]).process_dag_file(recipe_path)

        self.assertEqual(dag.recipe_name, "context-demo")
        self.assertEqual(dag.schedule, "@every 15m")
        self.assertEqual(dag.owner, "ml")
        self.assertEqual(dag.tags, ["nightly"])
        self.assertEqual(dag.executor, "thread_pool")
        self.assertEqual(dag.executor_kwargs, {"max_workers": 3})
        self.assertEqual(dag.callbacks, ["console"])


class DagBridgeRuntimeTests(unittest.TestCase):
    def test_dag_executor_forwards_manual_runtime_options(self):
        dag = ParsedDag(
            dag_id="demo-dag",
            path=Path("/tmp/demo.pyrecipe"),
            recipe_name="demo",
            is_python=True,
            schedule=None,
            schedule_meta=parse_schedule(None),
        )

        with patch("trainsh.core.dag_executor.run_recipe", return_value=True) as mocked:
            executor = DagExecutor(
                executor_name="thread_pool",
                executor_kwargs={"max_workers": 4},
                callbacks=["console"],
                callback_sinks=["sink"],
            )
            result = executor.run(
                dag,
                run_id="job123",
                run_type="manual",
                host_overrides={"gpu": "local"},
                var_overrides={"MODE": "test"},
                resume=True,
                initial_session_index=2,
            )

        self.assertTrue(result.success)
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["job_id"], "job123")
        self.assertEqual(kwargs["host_overrides"], {"gpu": "local"})
        self.assertEqual(kwargs["var_overrides"], {"MODE": "test"})
        self.assertTrue(kwargs["resume"])
        self.assertEqual(kwargs["initial_session_index"], 2)
        self.assertEqual(kwargs["executor_name"], "thread_pool")
        self.assertEqual(kwargs["executor_kwargs"], {"max_workers": 4})

    def test_dag_executor_prefers_manual_runtime_executor_over_recipe_default(self):
        dag = ParsedDag(
            dag_id="demo-dag",
            path=Path("/tmp/demo.pyrecipe"),
            recipe_name="demo",
            is_python=True,
            schedule=None,
            schedule_meta=parse_schedule(None),
            executor="sequential",
            executor_kwargs={"parallelism": 2},
        )

        with patch("trainsh.core.dag_executor.run_recipe", return_value=True) as mocked:
            executor = DagExecutor(
                executor_name="thread_pool",
                executor_kwargs={"max_workers": 4},
                prefer_runtime_options=True,
            )
            executor.run(dag, run_id="job123")

        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["executor_name"], "thread_pool")
        self.assertEqual(kwargs["executor_kwargs"], {"parallelism": 2, "max_workers": 4})

    def test_dag_executor_respects_explicit_recipe_callback_list(self):
        dag = ParsedDag(
            dag_id="demo-dag",
            path=Path("/tmp/demo.pyrecipe"),
            recipe_name="demo",
            is_python=True,
            schedule=None,
            schedule_meta=parse_schedule(None),
            callbacks=["console"],
        )

        with patch("trainsh.core.dag_executor.run_recipe", return_value=True) as mocked:
            DagExecutor(executor_name=None).run(dag, run_id="job123")

        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["callbacks"], ["console"])

    def test_runtime_dispatch_executes_recipe_via_parsed_dag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "dispatch_demo.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """\
                    from trainsh import Recipe

                    recipe = Recipe("dispatch-demo")
                    recipe.empty(id="start")
                    """
                ),
                encoding="utf-8",
            )

            expected = SimpleNamespace(success=True, dag_id=str(recipe_path.resolve()))
            with patch("trainsh.commands.runtime_dispatch.DagExecutor.run", return_value=expected) as mocked:
                result = run_recipe_via_dag(
                    str(recipe_path),
                    job_id="job456",
                    var_overrides={"FLAG": "1"},
                    executor_name="thread_pool",
                    executor_kwargs={"max_workers": 3},
                )

        self.assertIs(result, expected)
        dag = mocked.call_args.args[0]
        kwargs = mocked.call_args.kwargs
        self.assertEqual(dag.recipe_name, "dispatch-demo")
        self.assertEqual(kwargs["run_id"], "job456")
        self.assertEqual(kwargs["var_overrides"], {"FLAG": "1"})
        self.assertEqual(kwargs["run_type"], "manual")

    def test_cmd_run_routes_manual_execution_through_dag_bridge(self):
        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag",
            return_value=SimpleNamespace(success=True),
        ) as mocked:
            cmd_run(["demo", "--set", "MODEL=tiny", "--executor", "thread_pool"])

        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["var_overrides"], {"MODEL": "tiny"})
        self.assertEqual(kwargs["executor_name"], "thread_pool")


class RecipeCommandSafetyTests(unittest.TestCase):
    def test_cmd_remove_rejects_bundled_examples(self):
        with patch("trainsh.commands.recipe.prompt_input") as prompt_mock, patch(
            "trainsh.commands.recipe.os.remove"
        ) as remove_mock:
            with self.assertRaises(SystemExit):
                cmd_rm(["hello"])

        prompt_mock.assert_not_called()
        remove_mock.assert_not_called()


class MinimalTemplateTests(unittest.TestCase):
    def test_minimal_template_renders_and_loads(self):
        template = get_recipe_template("minimal", "demo")
        self.assertIn('Recipe("demo"', template)
        self.assertIn("local.tmux(", template)

        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "demo.pyrecipe"
            recipe_path.write_text(template, encoding="utf-8")
            loaded = load_python_recipe(str(recipe_path))

        self.assertEqual(loaded.name, "demo")
        self.assertGreaterEqual(len(loaded.steps), 4)


class PythonRecipeRuntimeIntegrationTests(unittest.TestCase):
    def test_run_recipe_honors_explicit_executor_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "override_demo.pyrecipe"
            config_dir = Path(tmpdir) / "config"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh import Recipe

                    recipe = Recipe("override-demo", executor="sequential", executor_kwargs={"parallelism": 2})
                    recipe.empty(id="start")
                    """
                ),
                encoding="utf-8",
            )

            seen = {}

            class DummyExecutor:
                def execute(self, fn):
                    return True

            def fake_get_executor(name, **kwargs):
                seen["name"] = name
                seen["kwargs"] = kwargs
                return DummyExecutor()

            with patch("trainsh.runtime.get_executor", side_effect=fake_get_executor), patch(
                "trainsh.runtime.build_sinks",
                return_value=[],
            ), patch(
                "trainsh.core.executor_main.CONFIG_DIR",
                config_dir,
            ), patch(
                "trainsh.core.executor_main.RUNTIME_STATE_DIR",
                config_dir / "runtime",
            ), patch(
                "trainsh.runtime.CONFIG_DIR",
                config_dir / "runtime",
            ):
                ok = run_recipe(
                    str(recipe_path),
                    executor_name="thread_pool",
                    executor_kwargs={"max_workers": 8},
                    callbacks=[],
                )

        self.assertTrue(ok)
        self.assertEqual(seen["name"], "thread_pool")
        self.assertEqual(seen["kwargs"], {"parallelism": 2, "max_workers": 8})

    def test_run_recipe_executes_local_provider_chain_and_persists_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recipe_path = root / "runtime_demo.pyrecipe"
            sqlite_db = root / "feature.db"
            config_dir = root / "config"
            storage_dir = root / "artifacts"
            storage_dir.mkdir(parents=True, exist_ok=True)
            (storage_dir / "ready.txt").write_text("ready\n", encoding="utf-8")

            recipe_path.write_text(
                textwrap.dedent(
                    f"""\
                    from trainsh import Recipe, Storage

                    recipe = Recipe("runtime-demo", callbacks=["console", "jsonl"])
                    artifacts = Storage({{"type": "local", "config": {{"path": r"{storage_dir}"}}}}, name="artifacts")

                    latest = recipe.latest_only(
                        runtime_state=r"{config_dir / 'runtime'}",
                        fail_if_unknown=False,
                        id="latest",
                    )
                    prepare = recipe.set_var(
                        "ROWS",
                        '[{{"event":"done"}}]',
                        id="prepare",
                        depends_on=[latest],
                    )
                    push = recipe.xcom_push(
                        "rows",
                        from_var="ROWS",
                        runtime_state=r"{config_dir / 'runtime'}",
                        id="push",
                        depends_on=[prepare],
                    )
                    pull = recipe.xcom_pull(
                        "rows",
                        task_ids=["push"],
                        output_var="ROWS_COPY",
                        runtime_state=r"{config_dir / 'runtime'}",
                        id="pull",
                        depends_on=[push],
                    )
                    http = recipe.http_wait(
                        "https://example.test/health",
                        expected_status=200,
                        expected_text="ok",
                        capture_var="HTTP_BODY",
                        timeout="5s",
                        poll_interval="1s",
                        id="http",
                        depends_on=[pull],
                    )
                    wait_storage = recipe.storage_wait(
                        artifacts.path("/ready.txt"),
                        timeout="5s",
                        poll_interval="1s",
                        id="wait_storage",
                        depends_on=[http],
                    )
                    recipe.notify("runtime done", id="notice", depends_on=[wait_storage])
                    """
                ),
                encoding="utf-8",
            )

            with patch("trainsh.core.executor_main.load_config", return_value={"tmux": {}}), patch(
                "trainsh.core.executor_main.DSLExecutor._http_request_once",
                return_value=(True, 200, "ok", ""),
            ), patch(
                    "trainsh.core.executor_main.CONFIG_DIR",
                    config_dir,
                ), patch(
                    "trainsh.core.executor_main.RUNTIME_STATE_DIR",
                    config_dir / "runtime",
                ), patch(
                    "trainsh.runtime.CONFIG_DIR",
                    config_dir / "runtime",
                ):
                ok = run_recipe(str(recipe_path), job_id="job9999")
            runtime_db = config_dir / "runtime"
            self.assertTrue(ok)
            self.assertTrue(runtime_db.exists())
            from trainsh.core.runtime_store import RuntimeStore

            store = RuntimeStore(runtime_db)
            xcom_row = store.query_xcom(dag_id=str(recipe_path), key="rows", run_id="job9999")
            self.assertEqual(xcom_row["key"], "rows")
            self.assertEqual(xcom_row["task_id"], "push")
            self.assertIn("done", xcom_row["value"])

            dag_run = store.get_run("job9999")
            self.assertEqual(dag_run["run_id"], "job9999")
            self.assertEqual(dag_run["state"], "success")
            task_instances = store.list_tasks(run_id="job9999")
            self.assertTrue(any(task["task_id"] == "http" and task["state"] == "success" for task in task_instances))
            self.assertTrue(any(task["task_id"] == "wait_storage" and task["state"] == "success" for task in task_instances))
            self.assertEqual(dag_run["hosts"], {})
            self.assertEqual(dag_run["storages"]["artifacts"]["config"]["path"], str(storage_dir))

            state_manager = JobStateManager(str(runtime_db))
            saved_state = state_manager.load("job9999")
            self.assertIsNotNone(saved_state)
            self.assertEqual(saved_state.storages["artifacts"]["config"]["path"], str(storage_dir))

            reader = ExecutionLogReader(str(runtime_db))
            executions = reader.list_executions(limit=1)
            self.assertEqual(executions[0]["host_count"], 0)
            self.assertEqual(executions[0]["storage_count"], 1)
            recent_events = reader.list_recent_events("job9999", limit=3)
            self.assertEqual(len(recent_events), 3)
            self.assertEqual(recent_events[-1]["event"], "execution_end")

            logs_output = StringIO()
            with redirect_stdout(logs_output):
                _show_execution_details(reader, "job9999")
            logs_text = logs_output.getvalue()
            self.assertIn("Storages (1):", logs_text)
            self.assertIn("Recent Events", logs_text)

            status_output = StringIO()
            with patch("trainsh.core.execution_log.ExecutionLogReader", return_value=reader), redirect_stdout(
                status_output
            ):
                _show_job_details(saved_state)
            status_text = status_output.getvalue()
            self.assertIn("Storages:", status_text)
            self.assertIn("Recent Events:", status_text)


if __name__ == "__main__":
    unittest.main()
