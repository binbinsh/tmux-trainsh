import os
import sqlite3
import tempfile
import threading
import textwrap
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.commands.recipe_runtime import cmd_run
from trainsh.commands.recipe_templates import get_recipe_template
from trainsh.commands.runtime_dispatch import run_recipe_via_dag
from trainsh.core.dag_executor import DagExecutor
from trainsh.core.dag_processor import DagProcessor, ParsedDag, parse_schedule
from trainsh.core.executor_main import run_recipe
from trainsh.pyrecipe import load_python_recipe, recipe as recipe_factory
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


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A003
        return


class PythonRecipeLoaderTests(unittest.TestCase):
    def test_load_python_recipe_uses_public_api_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "demo_recipe.py"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh.pyrecipe import *

                    recipe(
                        "demo-pipeline",
                        executor="thread_pool",
                        workers=3,
                        callbacks=["console"],
                    )

                    empty(id="start")
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
            recipe_path = Path(tmpdir) / "invalid_recipe.py"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh.pyrecipe import *
                    """
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "no recipe defined"):
                load_python_recipe(str(recipe_path))


class PythonRecipeBuilderTests(unittest.TestCase):
    def test_builder_normalizes_new_runtime_helpers_and_defaults(self):
        success_callback = lambda ctx=None: ctx
        failure_callback = {"provider": "util", "operation": "notice"}

        dag = recipe_factory("builder-demo", executor="thread_pool", executor_kwargs={"concurrency": "7"})
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
            "@artifacts",
            path="/done.txt",
            timeout="10m",
            poll_interval="15s",
            depends_on=[gate],
            id="wait_storage",
            step_options={"trigger_rule": "none_failed"},
        )
        query = dag.sqlite_query(
            "select 1",
            database="runtime.db",
            output_var="rows",
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

        query_step = steps["query"]
        self.assertEqual(query_step.provider, "sqlite")
        self.assertEqual(query_step.operation, "query")
        self.assertEqual(query_step.params["mode"], "all")
        self.assertEqual(query_step.params["database"], "runtime.db")

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
            recipe_path = Path(tmpdir) / "scheduled_recipe.py"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh.pyrecipe import *

                    recipe(
                        "scheduled-demo",
                        schedule="@every 5m",
                        tags=["gpu", "nightly"],
                        paused=True,
                        callbacks=["console"],
                        executor="airflow",
                        executor_kwargs={"parallelism": 6},
                    )
                    empty(id="start")
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


class DagBridgeRuntimeTests(unittest.TestCase):
    def test_dag_executor_forwards_manual_runtime_options(self):
        dag = ParsedDag(
            dag_id="demo-dag",
            path=Path("/tmp/demo.py"),
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

    def test_runtime_dispatch_executes_recipe_via_parsed_dag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_path = Path(tmpdir) / "dispatch_demo.py"
            recipe_path.write_text(
                textwrap.dedent(
                    """\
                    from trainsh.pyrecipe import *

                    recipe("dispatch-demo")
                    empty(id="start")
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
        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.py"), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag",
            return_value=SimpleNamespace(success=True),
        ) as mocked:
            cmd_run(["demo", "--var", "MODEL=tiny", "--executor", "thread_pool"])

        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["var_overrides"], {"MODEL": "tiny"})
        self.assertEqual(kwargs["executor_name"], "thread_pool")


class FeatureTourTemplateTests(unittest.TestCase):
    def test_feature_tour_template_contains_integrated_features(self):
        template = get_recipe_template("feature-tour", "demo")

        for marker in (
            "latest_only(",
            "choose(",
            "join(",
            "http_wait(",
            "sql_script(",
            "sql_query(",
            "xcom_push(",
            "xcom_pull(",
            "storage_wait(",
            "main.bg(",
            "main.wait(",
            "main.idle(",
        ):
            self.assertIn(marker, template)

    def test_bundled_feature_tour_example_loads(self):
        example_path = Path(__file__).resolve().parents[1] / "trainsh" / "examples" / "feature-tour.py"

        loaded = load_python_recipe(str(example_path))

        self.assertEqual(loaded.name, "feature-tour")
        self.assertGreaterEqual(len(loaded.steps), 10)
        self.assertIn("RUN_MODE", loaded.variables)
        self.assertIn("artifacts", loaded.storages)


class PythonRecipeRuntimeIntegrationTests(unittest.TestCase):
    def test_run_recipe_executes_local_provider_chain_and_persists_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recipe_path = root / "runtime_demo.py"
            sqlite_db = root / "feature.db"
            config_dir = root / "config"
            jobs_dir = config_dir / "jobs"
            storage_dir = root / "artifacts"
            storage_dir.mkdir(parents=True, exist_ok=True)
            (storage_dir / "ready.txt").write_text("ready\n", encoding="utf-8")

            server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            port = server.server_address[1]

            recipe_path.write_text(
                textwrap.dedent(
                    f"""\
                    from trainsh.pyrecipe import *

                    recipe("runtime-demo", callbacks=["console", "sqlite"])
                    storage("artifacts", {{"type": "local", "config": {{"path": r"{storage_dir}"}}}})

                    latest = latest_only(
                        sqlite_db=r"{sqlite_db}",
                        fail_if_unknown=False,
                        id="latest",
                    )
                    prepare = sql_script(
                        \"\"\"
                        CREATE TABLE IF NOT EXISTS workflow_events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            event TEXT NOT NULL
                        );
                        \"\"\",
                        db=r"{sqlite_db}",
                        id="prepare",
                        after=latest,
                    )
                    insert = sql_exec(
                        "INSERT INTO workflow_events(event) VALUES ('done')",
                        db=r"{sqlite_db}",
                        id="insert",
                        after=prepare,
                    )
                    query = sql_query(
                        "SELECT event FROM workflow_events ORDER BY id",
                        db=r"{sqlite_db}",
                        into="ROWS",
                        id="query",
                        after=insert,
                    )
                    push = xcom_push(
                        "rows",
                        from_var="ROWS",
                        database=r"{sqlite_db}",
                        id="push",
                        after=query,
                    )
                    pull = xcom_pull(
                        "rows",
                        task_ids=["push"],
                        output_var="ROWS_COPY",
                        database=r"{sqlite_db}",
                        id="pull",
                        after=push,
                    )
                    http = http_wait(
                        "http://127.0.0.1:{port}/health",
                        status=200,
                        expected_text="ok",
                        capture="HTTP_BODY",
                        timeout="5s",
                        every="1s",
                        id="http",
                        after=pull,
                    )
                    wait_storage = storage_wait(
                        "artifacts",
                        "/ready.txt",
                        timeout="5s",
                        poll_interval="1s",
                        id="wait_storage",
                        after=http,
                    )
                    notice("runtime done", id="notice", after=wait_storage)
                    """
                ),
                encoding="utf-8",
            )

            try:
                with patch("trainsh.core.executor_main.load_config", return_value={"tmux": {}}), patch(
                    "trainsh.core.executor_main.CONFIG_DIR",
                    config_dir,
                ), patch(
                    "trainsh.runtime.CONFIG_DIR",
                    config_dir,
                ), patch(
                    "trainsh.core.job_state.JOBS_DIR",
                    jobs_dir,
                ), patch(
                    "trainsh.core.execution_log.JOBS_DIR",
                    jobs_dir,
                ):
                    ok = run_recipe(str(recipe_path), job_id="job9999")
                runtime_db = config_dir / "runtime.db"
                self.assertTrue(ok)
                self.assertTrue(sqlite_db.exists())
                self.assertTrue(runtime_db.exists())

                with sqlite3.connect(sqlite_db) as conn:
                    rows = conn.execute("SELECT event FROM workflow_events ORDER BY id").fetchall()
                    xcom_rows = conn.execute("SELECT key, task_id, value FROM xcom ORDER BY created_at").fetchall()
                self.assertEqual(rows, [("done",)])
                self.assertEqual(xcom_rows[0][0], "rows")
                self.assertEqual(xcom_rows[0][1], "push")
                self.assertIn("done", xcom_rows[0][2])

                with sqlite3.connect(runtime_db) as conn:
                    dag_runs = conn.execute("SELECT dag_id, run_id, state FROM dag_run").fetchall()
                    task_instances = conn.execute(
                        "SELECT task_id, state FROM task_instance ORDER BY start_date, task_id"
                    ).fetchall()
                self.assertEqual(dag_runs[0][1], "job9999")
                self.assertEqual(dag_runs[0][2], "success")
                self.assertTrue(any(task_id == "http" and state == "success" for task_id, state in task_instances))
                self.assertTrue(any(task_id == "wait_storage" and state == "success" for task_id, state in task_instances))
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
