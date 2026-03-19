import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.commands import recipe_runtime
from trainsh.commands import recipe_shared


class CaptureMixin:
    def capture(self, fn, *args, **kwargs):
        out = io.StringIO()
        code = None
        result = None
        with redirect_stdout(out):
            try:
                result = fn(*args, **kwargs)
            except SystemExit as exc:
                code = exc.code
        return out.getvalue(), code, result


class RecipeRuntimeDeepTests(CaptureMixin, unittest.TestCase):
    def test_usage_and_parse_helpers(self):
        for func, exit_code in [
            (recipe_shared._print_run_usage, 0),
            (recipe_shared._print_exec_usage, 0),
            (recipe_shared._print_resume_usage, 1),
            (recipe_shared._print_logs_usage, 1),
            (recipe_shared._print_status_usage, 1),
            (recipe_shared._print_jobs_usage, 1),
        ]:
            out, code, _ = self.capture(func, exit_code)
            self.assertEqual(code, exit_code)
            self.assertIn("Usage:", out)

        self.assertEqual(recipe_runtime._parse_assignment("A=1", flag_name="--set"), ("A", "1"))
        out, code, _ = self.capture(recipe_runtime._parse_assignment, "A", flag_name="--set")
        self.assertEqual(code, 1)
        self.assertIn("Expected --set NAME=VALUE", out)

        self.assertEqual(recipe_runtime._parse_int_flag("4", flag_name="--workers"), 4)
        out, code, _ = self.capture(recipe_runtime._parse_int_flag, "bad", flag_name="--workers")
        self.assertEqual(code, 1)
        self.assertIn("must be integer", out)

    def test_auto_enter_tmux_paths(self):
        with patch.dict(os.environ, {"TMUX": "1"}, clear=False):
            self.assertFalse(
                recipe_runtime._maybe_auto_enter_tmux(["recipe", "run"], ["demo"], recipe_name="demo", job_id="job1", session_index=0, next_session_index=1)
            )
        with patch.dict(os.environ, {"TRAINSH_TMUX_BOOTSTRAP": "1"}, clear=False):
            self.assertFalse(
                recipe_runtime._maybe_auto_enter_tmux(["recipe", "run"], ["demo"], recipe_name="demo", job_id="job1", session_index=0, next_session_index=1)
            )

        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False):
            self.assertFalse(
                recipe_runtime._maybe_auto_enter_tmux(["recipe", "run"], ["demo"], recipe_name="demo", job_id="job1", session_index=0, next_session_index=1)
            )

        fake_tmux = SimpleNamespace(available=False)
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), patch(
            "trainsh.config.load_config", return_value={"tmux": {"auto_enter_tmux": True}}
        ), patch("trainsh.core.local_tmux.LocalTmuxClient", return_value=fake_tmux):
            self.assertFalse(
                recipe_runtime._maybe_auto_enter_tmux(["recipe", "run"], ["demo"], recipe_name="demo", job_id="job1", session_index=0, next_session_index=1)
            )

        fake_tmux = SimpleNamespace(available=True, new_session=lambda *args, **kwargs: SimpleNamespace(returncode=1))
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), patch(
            "trainsh.config.load_config", return_value={"tmux": {"auto_enter_tmux": False}}
        ), patch("trainsh.core.local_tmux.LocalTmuxClient", return_value=fake_tmux):
            self.assertFalse(
                recipe_runtime._maybe_auto_enter_tmux(["recipe", "run"], ["demo"], recipe_name="demo", job_id="job1", session_index=0, next_session_index=1)
            )

        calls = {}

        def new_session(name, detached=False, command=None):
            calls["name"] = name
            calls["command"] = command
            return SimpleNamespace(returncode=0)

        fake_tmux = SimpleNamespace(available=True, new_session=new_session)
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), patch.dict(
            os.environ, {"TERM": "dumb"}, clear=False
        ), patch("trainsh.config.load_config", return_value={"tmux": {"auto_enter_tmux": True}}), patch(
            "trainsh.core.local_tmux.LocalTmuxClient", return_value=fake_tmux
        ), patch("builtins.print") as mocked_print:
            result = recipe_runtime._maybe_auto_enter_tmux(
                ["recipe", "run"],
                ["demo", "--set", "A=1"],
                recipe_name="demo",
                job_id="job1",
                session_index=0,
                next_session_index=1,
            )
        self.assertTrue(result)
        mocked_print.assert_any_call("Not in tmux; auto-starting session: train_demo_job1_0")
        self.assertIn("TRAINSH_TMUX_BOOTSTRAP=1", calls["command"])

        fake_tmux = SimpleNamespace(available=True, new_session=lambda *args, **kwargs: SimpleNamespace(returncode=1))
        with patch.object(recipe_runtime.sys, "stdin", SimpleNamespace(isatty=lambda: True)), patch.object(
            recipe_runtime.sys, "stdout", SimpleNamespace(isatty=lambda: True)
        ), patch(
            "trainsh.config.load_config", return_value={"tmux": {"auto_enter_tmux": True}}
        ), patch("trainsh.core.local_tmux.LocalTmuxClient", return_value=fake_tmux), patch("builtins.print") as mocked_print:
            result = recipe_runtime._maybe_auto_enter_tmux(
                ["recipe", "run"],
                ["demo"],
                recipe_name="demo",
                job_id="job1",
                session_index=0,
                next_session_index=1,
            )
        self.assertFalse(result)
        mocked_print.assert_any_call("Failed to auto-start tmux session. Continuing in current terminal.")

    def test_pick_vast_host_paths(self):
        client = SimpleNamespace(list_instances=lambda: [])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            out, code, result = self.capture(recipe_runtime._pick_vast_host, "gpu")
        self.assertIsNone(code)
        self.assertIsNone(result)
        self.assertIn("No vast.ai instances available.", out)

        stopped = SimpleNamespace(id=1, is_running=False)
        client = SimpleNamespace(list_instances=lambda: [stopped])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            out, code, result = self.capture(recipe_runtime._pick_vast_host, "gpu")
        self.assertIsNone(result)
        self.assertIn("No running instances.", out)

        running = SimpleNamespace(id=7, is_running=True)
        client = SimpleNamespace(list_instances=lambda: [running])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD")
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", return_value="1"):
            out, code, result = self.capture(recipe_runtime._pick_vast_host, "gpu")
        self.assertEqual(result, "vast:7")
        self.assertIn("Select host for @gpu", out)

        client = SimpleNamespace(list_instances=lambda: [running, SimpleNamespace(id=9, is_running=True)])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD")
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", return_value="9"):
            _, _, result = self.capture(recipe_runtime._pick_vast_host, "gpu")
        self.assertEqual(result, "vast:9")

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD")
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", return_value="bad"):
            out, _, result = self.capture(recipe_runtime._pick_vast_host, "gpu")
        self.assertIsNone(result)
        self.assertIn("Invalid selection.", out)

        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom")):
            out, _, result = self.capture(recipe_runtime._pick_vast_host, "gpu")
        self.assertIsNone(result)
        self.assertIn("Error listing vast.ai instances: boom", out)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD")
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", side_effect=KeyboardInterrupt()):
            out, _, result = self.capture(recipe_runtime._pick_vast_host, "gpu")
        self.assertIsNone(result)
        self.assertIn("Cancelled.", out)

    def test_cmd_run_option_errors_and_paths(self):
        out, code, _ = self.capture(recipe_runtime.cmd_run, [])
        self.assertEqual(code, 1)
        self.assertIn("train recipe run", out)

        out, code, _ = self.capture(recipe_runtime.cmd_run, ["--help"])
        self.assertEqual(code, 0)

        bad_args = [
            ["demo", "--host"],
            ["demo", "--set"],
            ["demo", "--pick-host"],
            ["demo", "--executor"],
            ["demo", "--executor-workers"],
            ["demo", "--executor-option"],
            ["demo", "--executor-options"],
            ["demo", "--callback"],
        ]
        for args in bad_args:
            _, code, _ = self.capture(recipe_runtime.cmd_run, args)
            self.assertEqual(code, 1)

        for args in [
            ["demo", "--executor", "kubernetes"],
            ["demo", "--executor=k8s"],
            ["demo", "--executor-workers", "bad"],
            ["demo", "--executor-options", "badtoken"],
            ["demo", "--callback="],
            ["demo", "--unknown"],
            ["demo", "extra"],
        ]:
            _, code, _ = self.capture(recipe_runtime.cmd_run, args)
            self.assertEqual(code, 1)

        with patch("trainsh.commands.recipe_runtime._pick_vast_host", return_value=None):
            _, code, _ = self.capture(recipe_runtime.cmd_run, ["demo", "--pick-host", "gpu"])
        self.assertEqual(code, 1)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value=None):
            out, code, _ = self.capture(recipe_runtime.cmd_run, ["demo"])
        self.assertEqual(code, 1)
        self.assertIn("Recipe not found: demo", out)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=True
        ):
            out, code, result = self.capture(recipe_runtime.cmd_run, ["demo"])
        self.assertIsNone(code)
        self.assertIsNone(result)

        result_obj = SimpleNamespace(success=False)
        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=False
        ), patch("trainsh.commands.recipe_runtime._pick_vast_host", return_value="vast:8"), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=result_obj
        ), patch(
            "trainsh.commands.recipe_runtime.generate_job_id", return_value="job1"
        ):
            out, code, _ = self.capture(
                recipe_runtime.cmd_run,
                [
                    "demo",
                    "--host",
                    "gpu=local",
                    "--set",
                    "MODEL=tiny",
                    "--pick-host",
                    "gpu2",
                    "--executor",
                    "thread_pool",
                    "--executor-workers",
                    "4",
                    "--executor-option",
                    "parallelism=8",
                    "--executor-options",
                    '{"x":1}',
                    "--callback",
                    "console,sqlite",
                ],
            )
        self.assertEqual(code, 1)
        self.assertIn("Recipe execution failed.", out)

        result_obj = SimpleNamespace(success=True)
        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=False
        ), patch("trainsh.commands.recipe_runtime._pick_vast_host", return_value="vast:7"), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=result_obj
        ):
            out, code, _ = self.capture(recipe_runtime.cmd_run, ["demo", "--pick-host", "gpu"])
        self.assertIsNone(code)
        self.assertIn("Recipe completed successfully!", out)

        result_obj = SimpleNamespace(success=True)
        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=False
        ), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=result_obj
        ):
            out, code, _ = self.capture(
                recipe_runtime.cmd_run,
                [
                    "demo",
                    "--host=gpu=local",
                    "--set=MODEL=tiny",
                    "--executor=thread_pool",
                    "--executor-workers=2",
                    "--executor-option=parallelism=4",
                    "--executor-options=max_tasks=3,enabled=true,pi=3.5",
                    "--callback=console",
                ],
            )
        self.assertIsNone(code)
        self.assertIn("Host overrides:", out)
        self.assertIn("Variable overrides:", out)

    def test_cmd_exec_file_inline_and_stdin_paths(self):
        out, code, _ = self.capture(recipe_runtime.cmd_exec, ["--help"])
        self.assertEqual(code, 0)
        self.assertIn("train exec <<'EOF'", out)

        with patch.object(recipe_runtime.sys, "stdin", SimpleNamespace(isatty=lambda: True, read=lambda: "")):
            out, code, _ = self.capture(recipe_runtime.cmd_exec, [])
        self.assertEqual(code, 1)
        self.assertIn("train recipe exec", out)

        with patch.object(recipe_runtime.sys, "stdin", SimpleNamespace(isatty=lambda: False, read=lambda: "")):
            out, code, _ = self.capture(recipe_runtime.cmd_exec, [])
        self.assertEqual(code, 1)
        self.assertIn("No recipe code received on stdin.", out)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=False
        ), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=SimpleNamespace(success=True)
        ) as mocked:
            out, code, _ = self.capture(recipe_runtime.cmd_exec, ["demo", "--set", "MODEL=tiny"])
        self.assertIsNone(code)
        self.assertIn("Recipe completed successfully!", out)
        self.assertEqual(mocked.call_args.kwargs["var_overrides"], {"MODEL": "tiny"})

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value=None):
            out, code, _ = self.capture(recipe_runtime.cmd_exec, ["demo"])
        self.assertEqual(code, 1)
        self.assertIn("Recipe not found: demo", out)

        inline_code = "from trainsh import Recipe\nrecipe = Recipe('demo')\nrecipe.empty(id='start')\n"
        with patch("trainsh.commands.recipe_runtime._write_inline_recipe_file", return_value="/tmp/.trainsh-exec-demo.pyrecipe"), patch(
            "trainsh.commands.recipe_runtime._maybe_auto_enter_tmux"
        ) as auto_tmux, patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=SimpleNamespace(success=True)
        ), patch("os.remove") as remove_mock:
            out, code, _ = self.capture(recipe_runtime.cmd_exec, ["--code", inline_code])
        self.assertIsNone(code)
        self.assertIn("Executing inline recipe code.", out)
        auto_tmux.assert_not_called()
        remove_mock.assert_called_once_with("/tmp/.trainsh-exec-demo.pyrecipe")

        stdin_code = "from trainsh import Recipe\nrecipe = Recipe('stdin-demo')\nrecipe.empty(id='start')\n"
        with patch.object(recipe_runtime.sys, "stdin", SimpleNamespace(isatty=lambda: False, read=lambda: stdin_code)), patch(
            "trainsh.commands.recipe_runtime._write_inline_recipe_file", return_value="/tmp/.trainsh-stdin-demo.pyrecipe"
        ), patch(
            "trainsh.commands.recipe_runtime._maybe_auto_enter_tmux"
        ) as auto_tmux, patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=SimpleNamespace(success=True)
        ) as mocked, patch("os.remove"):
            out, code, _ = self.capture(recipe_runtime.cmd_exec, ["--set", "FLAG=1"])
        self.assertIsNone(code)
        self.assertIn("Executing recipe code from stdin.", out)
        self.assertEqual(mocked.call_args.kwargs["var_overrides"], {"FLAG": "1"})
        auto_tmux.assert_not_called()

        for args in [["--code"], ["--code="], ["demo", "extra"]]:
            _, code, _ = self.capture(recipe_runtime.cmd_exec, args)
            self.assertEqual(code, 1)

    def test_logs_status_jobs_resume_and_formatters(self):
        class Reader:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def list_executions(self, limit=20):
                return []

            def get_execution_summary(self, job_id):
                return None

            def list_recent_events(self, job_id, limit=6):
                return []

        reader = Reader()
        with patch("trainsh.core.execution_log.ExecutionLogReader", return_value=reader):
            out, code, _ = self.capture(recipe_runtime.cmd_logs, [])
        self.assertIsNone(code)
        self.assertIn("No execution logs found.", out)

        out, code, _ = self.capture(recipe_runtime.cmd_logs, ["--help"])
        self.assertEqual(code, 0)

        class FilledReader:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def list_executions(self, limit=20):
                return [{"job_id": "job1", "recipe": "demo", "started": "2026-03-12T00:00:00", "success": None, "duration_ms": 0, "host_count": 2, "storage_count": 1}]

            def get_execution_summary(self, job_id):
                return {"job_id": "job1", "recipe": "demo", "recipe_path": "/tmp/demo.py", "started": "s", "ended": "e", "success": True, "duration_ms": 1, "variables": {}, "hosts": {}, "storages": {}, "steps": [], "recent_events": []}

            def list_recent_events(self, job_id, limit=6):
                return []

        reader = FilledReader()
        with patch("trainsh.core.execution_log.ExecutionLogReader", return_value=reader):
            out, _, _ = self.capture(recipe_runtime.cmd_logs, [])
            self.assertIn("2/1", out)
            out, _, _ = self.capture(recipe_runtime.cmd_logs, ["--last"])
            self.assertIn("Job ID: job1", out)

        missing_reader = SimpleNamespace(get_execution_summary=lambda job_id: None)
        out, code, _ = self.capture(recipe_runtime._show_execution_details, missing_reader, "missing")
        self.assertEqual(code, 1)

        state_manager = SimpleNamespace(
            list_running=lambda: [],
            list_all=lambda limit=20: [],
            load=lambda job_id: None,
            find_resumable=lambda recipe_path: None,
        )
        with patch("trainsh.core.job_state.JobStateManager", return_value=state_manager):
            out, _, _ = self.capture(recipe_runtime.cmd_status, [])
            self.assertIn("No running recipe jobs.", out)
            out, _, _ = self.capture(recipe_runtime.cmd_status, ["--last"])
            self.assertIn("No recipe jobs found.", out)
            out, _, _ = self.capture(recipe_runtime.cmd_jobs, [])
            self.assertIn("No job states found.", out)

        job = SimpleNamespace(
            job_id="job123456",
            recipe_name="demo",
            recipe_path="/tmp/demo.py",
            status="running",
            current_step=0,
            total_steps=2,
            next_window_index=1,
            created_at="2026-03-12T00:00:00",
            updated_at="2026-03-12T00:00:01",
            tmux_session="sess",
            bridge_session="bridge",
            window_sessions={"gpu": "sess2"},
            hosts={"gpu": "local"},
            storages={"artifacts": {"path": "/tmp/out"}},
            vast_instance_id="7",
            vast_start_time="2026-03-12T00:00:00",
        )
        state_manager = SimpleNamespace(
            list_running=lambda: [job],
            list_all=lambda limit=20: [job],
            load=lambda job_id: job if job_id == "job123456" else None,
            find_resumable=lambda recipe_path: job,
        )

        class RecentReader:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def list_recent_events(self, job_id, limit=6):
                return [{"event": "execution_end", "success": True, "ts": "2026-03-12T08:00:00"}]

        with patch("trainsh.core.job_state.JobStateManager", return_value=state_manager), patch(
            "trainsh.core.execution_log.ExecutionLogReader", return_value=RecentReader()
        ), patch("trainsh.core.tmux_session.session_exists", return_value=False):
            out, _, _ = self.capture(recipe_runtime.cmd_status, ["job123456"])
            self.assertIn("Storages:", out)
            self.assertIn("Recent Events:", out)
            out, _, _ = self.capture(recipe_runtime.cmd_jobs, ["--all"])
            self.assertIn("job12345", out)
            self.assertIn("1/2", out)

        self.assertIn("execution end (success)", recipe_runtime._format_recent_event({"event": "execution_end", "success": True, "ts": "2026-03-12T08:00:00"}))
        self.assertEqual(recipe_runtime._short_text("x" * 100, max_len=10), "xxxxxxx...")
        self.assertIn("execution start", recipe_runtime._format_recent_event({"event": "execution_start", "ts": "2026-03-12T08:00:00"}))
        self.assertIn("step 1 start", recipe_runtime._format_recent_event({"event": "step_start", "step_num": 1, "ts": "2026-03-12T08:00:00"}))
        self.assertIn("var X", recipe_runtime._format_recent_event({"event": "variable_set", "name": "X", "value": "1", "ts": "2026-03-12T08:00:00"}))
        self.assertIn("ssh gpu", recipe_runtime._format_recent_event({"event": "ssh_command", "host": "gpu", "returncode": 0, "ts": "2026-03-12T08:00:00"}))
        self.assertIn("tmux attach", recipe_runtime._format_recent_event({"event": "tmux_operation", "operation": "attach", "target": "sess", "ts": "2026-03-12T08:00:00"}))
        self.assertIn("transfer src", recipe_runtime._format_recent_event({"event": "file_transfer", "source": "src", "dest": "dst", "ts": "2026-03-12T08:00:00"}))
        self.assertIn("vast pick", recipe_runtime._format_recent_event({"event": "vast_api", "operation": "pick", "ts": "2026-03-12T08:00:00"}))
        self.assertIn("custom", recipe_runtime._format_recent_event({"event": "custom", "ts": "2026-03-12T08:00:00"}))

        out, code, _ = self.capture(recipe_runtime.cmd_resume, [])
        self.assertEqual(code, 1)
        out, code, _ = self.capture(recipe_runtime.cmd_resume, ["--help"])
        self.assertEqual(code, 0)

        for args in [["demo", "--host", "gpu=local"], ["demo", "--bad"]]:
            _, code, _ = self.capture(recipe_runtime.cmd_resume, args)
            self.assertEqual(code, 1)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value=None):
            out, code, _ = self.capture(recipe_runtime.cmd_resume, ["demo"])
        self.assertEqual(code, 1)
        self.assertIn("Recipe not found", out)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.core.job_state.JobStateManager", return_value=SimpleNamespace(find_resumable=lambda path: None)
        ):
            out, code, _ = self.capture(recipe_runtime.cmd_resume, ["demo"])
        self.assertEqual(code, 1)
        self.assertIn("No resumable state found", out)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.core.job_state.JobStateManager", return_value=state_manager
        ), patch("trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=True):
            out, code, _ = self.capture(recipe_runtime.cmd_resume, ["demo"])
        self.assertIsNone(code)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.core.job_state.JobStateManager", return_value=state_manager
        ), patch("trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=False), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=SimpleNamespace(success=False)
        ):
            out, code, _ = self.capture(recipe_runtime.cmd_resume, ["demo", "--set", "MODEL=big"])
        self.assertEqual(code, 1)
        self.assertIn("Variable overrides:", out)
        self.assertIn("retry from the failed step", out)

        with patch("trainsh.commands.recipe_runtime.find_recipe", return_value="/tmp/demo.pyrecipe"), patch(
            "trainsh.core.job_state.JobStateManager", return_value=state_manager
        ), patch("trainsh.commands.recipe_runtime._maybe_auto_enter_tmux", return_value=False), patch(
            "trainsh.commands.recipe_runtime.run_recipe_via_dag", return_value=SimpleNamespace(success=True)
        ):
            out, code, _ = self.capture(recipe_runtime.cmd_resume, ["demo", "--set=MODEL=small"])
        self.assertIsNone(code)
        self.assertIn("Recipe completed successfully!", out)

    def test_attach_commands_and_live_output_paths(self):
        job = SimpleNamespace(
            job_id="jobabcdef",
            recipe_name="demo",
            recipe_path="/tmp/demo.py",
            status="running",
            current_step=0,
            total_steps=1,
            created_at="2026-03-12T00:00:00",
            updated_at="2026-03-12T00:00:01",
            tmux_session="sess",
            bridge_session="bridge",
            window_sessions={"gpu": "sess2"},
            hosts={"gpu": "local", "cpu": "ssh://box"},
            storages={},
            vast_instance_id="",
            vast_start_time="",
        )

        class RecentReader:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def list_recent_events(self, job_id, limit=6):
                return []

        tmux = SimpleNamespace(
            list_panes=lambda: [SimpleNamespace(pane_id="%1", window_name="main", current_command="bash")],
            capture=lambda pane_id, start=-20: "line1\nline2",
        )
        with patch("trainsh.core.execution_log.ExecutionLogReader", return_value=RecentReader()), patch(
            "trainsh.core.local_tmux.LocalTmuxClient",
            return_value=SimpleNamespace(build_attach_command=lambda session, nested=False: f"local:{session}:{nested}"),
        ), patch(
            "trainsh.core.remote_tmux.RemoteTmuxClient",
            return_value=SimpleNamespace(build_attach_command=lambda session, status_mode='keep': f"remote:{session}:{status_mode}"),
        ), patch("trainsh.core.tmux_session.session_exists", return_value=True), patch(
            "trainsh.core.tmux_session.TmuxSession", return_value=tmux
        ):
            out, code, _ = self.capture(recipe_runtime._show_job_details, job)
        self.assertIsNone(code)
        self.assertIn("bridge: tmux attach -t bridge", out)
        self.assertIn("@gpu: local:sess2:False", out)
        self.assertIn("@cpu: remote:train_demo_jobabcde_1:keep", out)
        self.assertIn("Live Output", out)

        with patch("trainsh.core.execution_log.ExecutionLogReader", return_value=RecentReader()), patch(
            "trainsh.core.local_tmux.LocalTmuxClient",
            return_value=SimpleNamespace(build_attach_command=lambda session, nested=False: (_ for _ in ()).throw(RuntimeError("boom"))),
        ), patch(
            "trainsh.core.remote_tmux.RemoteTmuxClient",
            return_value=SimpleNamespace(build_attach_command=lambda session, status_mode='keep': (_ for _ in ()).throw(RuntimeError("boom"))),
        ), patch("trainsh.core.tmux_session.session_exists", return_value=True), patch(
            "trainsh.core.tmux_session.TmuxSession", side_effect=RuntimeError("capture failed")
        ):
            out, code, _ = self.capture(recipe_runtime._show_job_details, job)
        self.assertIsNone(code)
        self.assertIn("@gpu: tmux attach -t sess2", out)
        self.assertIn("(Could not capture output: capture failed)", out)


if __name__ == "__main__":
    unittest.main()
