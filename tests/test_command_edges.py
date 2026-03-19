import sqlite3
import tempfile
import textwrap
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import mock_open, patch

from trainsh.commands import colab, config_cmd, recipe, schedule_cmd, transfer
from trainsh.core.models import Storage, StorageType


def capture(fn, *args, **kwargs):
    stream = StringIO()
    code = None
    with redirect_stdout(stream):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return stream.getvalue(), code


@contextmanager
def patched_recipe_dirs():
    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        root = Path(tmpdir)
        recipes_dir = root / "recipes"
        examples_dir = root / "examples"
        recipes_dir.mkdir()
        examples_dir.mkdir()
        stack.enter_context(patch("trainsh.commands.recipe._project_root", return_value=root))
        stack.enter_context(patch("trainsh.commands.recipe.get_examples_dir", return_value=str(examples_dir)))
        yield recipes_dir, examples_dir


class ScheduleCommandEdgeTests(unittest.TestCase):
    def test_schedule_parse_helpers_and_errors(self):
        self.assertEqual(schedule_cmd._to_int("3", field="--rows"), 3)
        out, code = capture(schedule_cmd._to_int, "bad", field="--rows")
        self.assertEqual(code, 1)
        self.assertIn("Invalid --rows", out)

        out, code = capture(schedule_cmd._to_int, "0", field="--rows")
        self.assertEqual(code, 1)
        self.assertIn("--rows must be >= 1", out)

        self.assertEqual(schedule_cmd._parse_args(["help"])["mode"], "help")
        for args in [
            ["run", "--recipe"],
            ["run", "--recipes-dir"],
            ["run", "--runtime-state"],
            ["run", "--loop-interval"],
            ["run", "--max-active-runs"],
            ["run", "--max-active-runs-per-recipe"],
            ["run", "--iterations"],
            ["status", "--rows"],
            ["run", "--unknown"],
        ]:
            with self.subTest(args=args):
                with self.assertRaises(SystemExit):
                    schedule_cmd._parse_args(args)

        self.assertTrue(schedule_cmd._matches("demo", []))
        self.assertTrue(schedule_cmd._matches("demo", ["em"]))
        self.assertFalse(schedule_cmd._matches("demo", ["zzz"]))
        self.assertEqual(schedule_cmd._recipe_label("/tmp/demo.py"), "demo")
        self.assertEqual(schedule_cmd._recipe_label(""), "-")
        self.assertTrue(schedule_cmd._is_running_state("running"))
        self.assertFalse(schedule_cmd._is_running_state("success"))

    def test_schedule_list_status_and_run_edge_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "runtime.db"
            from trainsh.core.runtime_store import RuntimeStore

            RuntimeStore(db_path).append_run(
                {
                    "run_id": "run-1",
                    "dag_id": "/tmp/demo.py",
                    "recipe_name": "demo",
                    "recipe_path": "/tmp/demo.py",
                    "state": "running",
                    "status": "running",
                    "run_type": "scheduled",
                    "execution_date": "now",
                    "started_at": "now",
                    "ended_at": "",
                    "updated_at": "now",
                }
            )

            invalid = SimpleNamespace(
                dag_id="/tmp/invalid.py",
                recipe_name="invalid",
                is_valid=False,
                load_error="boom",
                schedule=None,
                path="/tmp/invalid.py",
            )
            valid = SimpleNamespace(
                dag_id="/tmp/demo.py",
                recipe_name="demo",
                is_valid=True,
                load_error=None,
                schedule="@daily",
                path="/tmp/demo.py",
            )

            with patch("trainsh.commands.schedule_cmd.DagProcessor") as mocked_processor:
                mocked_processor.return_value.discover_dags.return_value = [invalid, valid]
                out, code = capture(schedule_cmd.cmd_schedule_list, ["demo", "--runtime-state", str(db_path)])
            self.assertIsNone(code)
            self.assertIn("demo", out)
            self.assertNotIn("invalid", out)

            with patch("trainsh.commands.schedule_cmd.DagProcessor") as mocked_processor:
                mocked_processor.return_value.discover_dags.return_value = [invalid]
                out, code = capture(
                    schedule_cmd.cmd_schedule_list,
                    ["--include-invalid", "invalid", "--runtime-state", str(db_path)],
                )
            self.assertIsNone(code)
            self.assertIn("invalid", out)

            with patch("trainsh.commands.schedule_cmd.DagProcessor") as mocked_processor:
                mocked_processor.return_value.discover_dags.return_value = []
                out, code = capture(schedule_cmd.cmd_schedule_list, ["--runtime-state", str(db_path)])
            self.assertIsNone(code)
            self.assertIn("No scheduled recipes found.", out)

            missing_db_out, _ = capture(schedule_cmd.cmd_schedule_status, ["--runtime-state", str(root / "missing")])
            self.assertIn("No runtime state found", missing_db_out)

            empty_db = root / "empty.db"
            RuntimeStore(empty_db)
            out, code = capture(schedule_cmd.cmd_schedule_status, ["--runtime-state", str(empty_db)])
            self.assertIsNone(code)
            self.assertIn("No runs recorded.", out)

            out, code = capture(schedule_cmd.cmd_schedule_status, ["--runtime-state", str(db_path), "--rows", "5"])
            self.assertIsNone(code)
            self.assertIn("Running: 1", out)

            scheduler = SimpleNamespace(
                run_once=lambda **kwargs: [],
                run_forever=lambda **kwargs: None,
            )
            with patch("trainsh.commands.schedule_cmd.DagScheduler", return_value=scheduler):
                out, code = capture(schedule_cmd.cmd_schedule_run, ["--runtime-state", str(db_path)])
            self.assertIsNone(code)
            self.assertIn("No scheduled recipe was started.", out)

            called = {}

            def _run_forever(**kwargs):
                called.update(kwargs)

            scheduler = SimpleNamespace(run_once=lambda **kwargs: [], run_forever=_run_forever)
            with patch("trainsh.commands.schedule_cmd.DagScheduler", return_value=scheduler):
                out, code = capture(schedule_cmd.main, ["run", "--forever", "--recipe", "demo"])
            self.assertIsNone(code)
            self.assertEqual(called["dag_ids"], ["demo"])

    def test_schedule_status_helpers_without_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from trainsh.core.runtime_store import RuntimeStore

            store = RuntimeStore(Path(tmpdir) / "runtime")
            self.assertIsNone(schedule_cmd._latest_state_for_dag(store, "demo"))
            self.assertEqual(schedule_cmd._query_history(store, 10), [])


class ColabCommandEdgeTests(unittest.TestCase):
    def test_load_save_list_and_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            colab_file = Path(tmpdir) / "colab.yaml"
            with patch("trainsh.commands.colab.COLAB_FILE", colab_file), patch("trainsh.commands.colab.CONFIG_DIR", Path(tmpdir)):
                out, code = capture(colab.cmd_list, [])
                self.assertIsNone(code)
                self.assertIn("No Colab connections configured.", out)

                colab._save_colab_data({"connections": [{"name": "demo", "tunnel_type": "cloudflared"}]})
                self.assertEqual(colab._load_colab_data()["connections"][0]["name"], "demo")

                colab_file.write_text("connections: [\n", encoding="utf-8")
                out, code = capture(colab._load_colab_data)
                self.assertEqual(code, 1)
                self.assertIn("Invalid YAML", out)

    def test_connect_ssh_run_and_main_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            colab_file = Path(tmpdir) / "colab.yaml"
            with patch("trainsh.commands.colab.COLAB_FILE", colab_file), patch("trainsh.commands.colab.CONFIG_DIR", Path(tmpdir)):
                with patch("trainsh.commands.colab.prompt_input", side_effect=[None]):
                    out, code = capture(colab.cmd_connect, [])
                self.assertIsNone(code)

                with patch("trainsh.commands.colab.prompt_input", side_effect=["",]):
                    out, code = capture(colab.cmd_connect, [])
                self.assertIsNone(code)
                self.assertIn("Cancelled.", out)

                with patch(
                    "trainsh.commands.colab.prompt_input",
                    side_effect=["demo-ng", "2", "ngrok.example.com", "2200", "pw"],
                ):
                    out, code = capture(colab.cmd_connect, [])
                self.assertIsNone(code)
                self.assertIn("Added Colab connection: demo-ng", out)

                with patch(
                    "trainsh.commands.colab.prompt_input",
                    side_effect=["demo-cf", "1", "cf.example.com", "pw"],
                ):
                    out, code = capture(colab.cmd_connect, [])
                self.assertIsNone(code)
                self.assertIn("demo-cf", colab._load_colab_data()["connections"][1]["name"])

                with patch("os.system") as mocked_system:
                    out, code = capture(colab.cmd_ssh, ["demo-ng"])
                self.assertIsNone(code)
                self.assertIn("ngrok", mocked_system.call_args.args[0])

                with patch("os.system") as mocked_system:
                    out, code = capture(colab.cmd_ssh, ["demo-cf"])
                self.assertIsNone(code)
                self.assertIn("cloudflared access ssh", mocked_system.call_args.args[0])

                with patch("trainsh.commands.colab.prompt_input", side_effect=["3"]):
                    out, code = capture(colab.cmd_ssh, [])
                self.assertEqual(code, 1)
                self.assertIn("Invalid selection.", out)

                out, code = capture(colab.cmd_ssh, ["missing"])
                self.assertEqual(code, 1)
                self.assertIn("Connection not found", out)

                with patch("os.system") as mocked_system:
                    out, code = capture(colab.cmd_run, ["echo", "hi"])
                self.assertIsNone(code)
                self.assertIn("Running on Colab: echo hi", out)
                self.assertIn("ssh", mocked_system.call_args.args[0])

                out, code = capture(colab.cmd_run, [])
                self.assertEqual(code, 1)
                self.assertIn("Usage: train colab run <command>", out)

                out, code = capture(colab.main, ["--help"])
                self.assertIsNone(code)
                self.assertIn("train colab", out)

                out, code = capture(colab.main, ["unknown"])
                self.assertEqual(code, 1)
                self.assertIn("Unknown subcommand", out)


class ConfigCommandEdgeTests(unittest.TestCase):
    def test_show_get_set_reset_and_tmux_namespace(self):
        with patch("trainsh.config.load_config", return_value={"ui": {"currency": "USD"}, "flag": True}):
            out, code = capture(config_cmd.cmd_show, [])
        self.assertIsNone(code)
        self.assertIn("ui:", out)
        self.assertIn("currency = USD", out)

        out, code = capture(config_cmd.cmd_get, [])
        self.assertEqual(code, 1)
        self.assertIn("Usage: train config get", out)

        with patch("trainsh.config.get_config_value", return_value=None):
            out, code = capture(config_cmd.cmd_get, ["missing.key"])
        self.assertEqual(code, 1)
        self.assertIn("Key not found", out)

        with patch("trainsh.config.get_config_value", return_value="USD"):
            out, code = capture(config_cmd.cmd_get, ["ui.currency"])
        self.assertIsNone(code)
        self.assertEqual(out.strip(), "USD")

        out, code = capture(config_cmd.cmd_set, ["ui.currency"])
        self.assertEqual(code, 1)
        self.assertIn("Usage: train config set", out)

        with patch("trainsh.config.set_config_value") as mocked_set:
            for raw, expected in [("true", True), ("false", False), ("12", 12), ("1.5", 1.5), ("CNY", "CNY")]:
                out, code = capture(config_cmd.cmd_set, ["demo.key", raw])
                self.assertIsNone(code)
                self.assertIn("Set demo.key =", out)
                self.assertEqual(mocked_set.call_args.args[1], expected)

        with patch("trainsh.commands.config_cmd.prompt_input", return_value="n"):
            out, code = capture(config_cmd.cmd_reset, [])
        self.assertIsNone(code)
        self.assertIn("Cancelled.", out)

        with patch("trainsh.commands.config_cmd.prompt_input", return_value="y"), patch(
            "trainsh.config.get_default_config", return_value={"tmux": {"options": []}}
        ), patch("trainsh.config.save_config") as mocked_save:
            out, code = capture(config_cmd.cmd_reset, [])
        self.assertIsNone(code)
        mocked_save.assert_called_once()

        self.assertIn("set -g mouse on", config_cmd.generate_tmux_conf(["set -g mouse on"]))

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            tmux_conf = home / ".tmux.conf"
            with patch("os.path.expanduser", side_effect=lambda p: str(tmux_conf) if p == "~/.tmux.conf" else p), patch(
                "trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}
            ), patch("trainsh.commands.config_cmd.prompt_input", return_value="y"):
                out, code = capture(config_cmd.cmd_tmux_setup, [])
            self.assertIsNone(code)
            self.assertTrue(tmux_conf.exists())
            self.assertIn("Written to", out)

            with patch("trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}):
                out, code = capture(config_cmd.cmd_tmux_list, [])
            self.assertIsNone(code)
            self.assertIn("Total: 1 options", out)

            tmux_conf.write_text(config_cmd.generate_tmux_conf(["set -g mouse on"]), encoding="utf-8")
            with patch("os.path.expanduser", side_effect=lambda p: str(tmux_conf) if p == "~/.tmux.conf" else p), patch(
                "trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}
            ):
                out, code = capture(config_cmd.cmd_tmux_setup, [])
            self.assertIsNone(code)
            self.assertIn("already up to date", out)

            tmux_conf.write_text("old", encoding="utf-8")
            with patch("os.path.expanduser", side_effect=lambda p: str(tmux_conf) if p == "~/.tmux.conf" else p), patch(
                "trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mode-keys vi"]}}
            ), patch("trainsh.commands.config_cmd.prompt_input", return_value="y"):
                out, code = capture(config_cmd.cmd_tmux_setup, [])
            self.assertIsNone(code)
            self.assertTrue((home / ".tmux.conf.bak").exists())
            self.assertIn("Backed up existing config", out)

            mocked = mock_open(read_data="# comment\nset -g status on\n")
            with patch("trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}), patch(
                "tempfile.NamedTemporaryFile"
            ) as mocked_tmp, patch("subprocess.run", return_value=SimpleNamespace(returncode=0)), patch(
                "builtins.open", mocked
            ), patch("trainsh.config.save_config") as mocked_save, patch("os.unlink"):
                mocked_tmp.return_value.__enter__.return_value.name = str(home / "tmp.tmux.conf")
                mocked_tmp.return_value.__enter__.return_value.write = lambda *_a, **_k: None
                out, code = capture(config_cmd.cmd_tmux_edit, [])
            self.assertIsNone(code)
            mocked_save.assert_called_once()
            self.assertIn("Saved 1 tmux options", out)

            with patch("trainsh.config.load_config", return_value={"tmux": {"options": []}}), patch(
                "tempfile.NamedTemporaryFile"
            ) as mocked_tmp, patch("subprocess.run", return_value=SimpleNamespace(returncode=1)), patch("os.unlink"):
                mocked_tmp.return_value.__enter__.return_value.name = str(home / "tmp.tmux.conf")
                mocked_tmp.return_value.__enter__.return_value.write = lambda *_a, **_k: None
                out, code = capture(config_cmd.cmd_tmux_edit, [])
            self.assertIsNone(code)
            self.assertIn("Editor exited with error", out)

            with patch("trainsh.config.load_config", return_value={}), patch(
                "tempfile.NamedTemporaryFile"
            ) as mocked_tmp, patch("subprocess.run", return_value=SimpleNamespace(returncode=0)), patch(
                "builtins.open", mock_open(read_data="\n# ignored\n")
            ), patch("trainsh.config.save_config") as mocked_save, patch("os.unlink", side_effect=OSError("boom")):
                mocked_tmp.return_value.__enter__.return_value.name = str(home / "tmp.tmux.conf")
                mocked_tmp.return_value.__enter__.return_value.write = lambda *_a, **_k: None
                out, code = capture(config_cmd.cmd_tmux_edit, [])
            self.assertIsNone(code)
            mocked_save.assert_called_once()

        out, code = capture(config_cmd._handle_tmux_namespace, [])
        self.assertIsNone(code)
        self.assertIn("train config tmux", out)

        out, code = capture(config_cmd._handle_tmux_namespace, ["unknown"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown tmux subcommand", out)

        out, code = capture(config_cmd.main, ["unknown"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown subcommand", out)


class RecipeCommandEdgeTests(unittest.TestCase):
    def test_recipe_helpers_and_listing(self):
        with patched_recipe_dirs() as (recipes_dir, examples_dir):
            (recipes_dir / "mine.pyrecipe").write_text("print('user')\n", encoding="utf-8")
            (examples_dir / "hello.pyrecipe").write_text("print('example')\n", encoding="utf-8")

            self.assertEqual(recipe.list_recipes(), ["mine.pyrecipe"])
            self.assertEqual(recipe.list_examples(), ["hello.pyrecipe"])
            self.assertEqual(Path(recipe.find_recipe("mine")).name, "mine.pyrecipe")
            self.assertEqual(Path(recipe.find_recipe("examples/hello")).name, "hello.pyrecipe")
            self.assertEqual(Path(recipe.find_user_recipe("mine")).name, "mine.pyrecipe")
            self.assertIsNone(recipe.find_user_recipe(str(examples_dir / "hello.pyrecipe")))
            self.assertTrue(recipe._is_bundled_example(str(examples_dir / "hello.pyrecipe")))
            self.assertFalse(recipe._path_within("/tmp/a", None))

            out, code = capture(recipe.cmd_list, [])
            self.assertIsNone(code)
            self.assertIn("User recipes:", out)
            self.assertIn("Bundled examples:", out)

        with patched_recipe_dirs():
            out, code = capture(recipe.cmd_list, [])
            self.assertIsNone(code)
            self.assertIn("No recipes found.", out)

    def test_recipe_show_new_edit_remove_and_main(self):
        with patched_recipe_dirs() as (recipes_dir, examples_dir):
            user_path = recipes_dir / "demo.pyrecipe"
            user_path.write_text("print('demo')\n", encoding="utf-8")
            example_path = examples_dir / "hello.pyrecipe"
            example_path.write_text("print('hello')\n", encoding="utf-8")

            out, code = capture(recipe.cmd_show, [])
            self.assertEqual(code, 1)
            self.assertIn("Usage: train recipe show", out)

            out, code = capture(recipe.cmd_show, ["missing"])
            self.assertEqual(code, 1)
            self.assertIn("Recipe not found", out)

            loaded = SimpleNamespace(name="demo", variables={"A": "1"}, hosts={"gpu": "local"}, steps=[SimpleNamespace(raw="echo hi")])
            with patch("trainsh.pyrecipe.load_python_recipe", return_value=loaded):
                out, code = capture(recipe.cmd_show, ["demo"])
            self.assertIsNone(code)
            self.assertIn("Recipe: demo", out)
            self.assertIn("1. echo hi", out)

            with patch("trainsh.pyrecipe.load_python_recipe", side_effect=RuntimeError("boom")):
                out, code = capture(recipe.cmd_show, ["demo"])
            self.assertEqual(code, 1)
            self.assertIn("Error loading recipe: boom", out)

            out, code = capture(recipe.cmd_new, [])
            self.assertEqual(code, 1)
            self.assertIn("Usage: train recipe new", out)

            out, code = capture(recipe.cmd_new, ["demo", "--bad"])
            self.assertEqual(code, 1)
            self.assertIn("Unknown flag", out)

            out, code = capture(recipe.cmd_new, ["demo", "--template"])
            self.assertEqual(code, 1)
            self.assertIn("Missing value for --template", out)

            out, code = capture(recipe.cmd_new, ["demo"])
            self.assertEqual(code, 1)
            self.assertIn("Recipe already exists", out)

            with patch("trainsh.commands.recipe.get_recipe_template", side_effect=ValueError("bad template")):
                out, code = capture(recipe.cmd_new, ["fresh", "--template", "bad"])
            self.assertEqual(code, 1)
            self.assertIn("bad template", out)

            with patch("trainsh.commands.recipe.get_recipe_template", return_value="# demo\n"), patch(
                "trainsh.commands.recipe._open_editor"
            ) as mocked_open:
                out, code = capture(recipe.cmd_new, ["fresh", "--template", "minimal"])
            self.assertIsNone(code)
            self.assertTrue((recipes_dir / "fresh.pyrecipe").exists())
            mocked_open.assert_called_once()

            out, code = capture(recipe.cmd_edit, [])
            self.assertEqual(code, 1)
            self.assertIn("Usage: train recipe edit", out)

            with patch("trainsh.commands.recipe._open_editor") as mocked_open:
                out, code = capture(recipe.cmd_edit, ["demo"])
            self.assertIsNone(code)
            mocked_open.assert_called_once()

            out, code = capture(recipe.cmd_edit, ["hello"])
            self.assertEqual(code, 1)
            self.assertIn("Bundled examples cannot be edited in place", out)

            out, code = capture(recipe.cmd_edit, ["missing"])
            self.assertEqual(code, 1)
            self.assertIn("Use 'train recipe new' to create one.", out)

            out, code = capture(recipe.cmd_rm, [])
            self.assertEqual(code, 1)
            self.assertIn("Usage: train recipe remove", out)

            with patch("trainsh.commands.recipe.prompt_input", return_value="n"):
                out, code = capture(recipe.cmd_rm, ["demo"])
            self.assertIsNone(code)
            self.assertIn("Cancelled.", out)

            with patch("trainsh.commands.recipe.prompt_input", return_value="y"), patch(
                "os.remove", side_effect=OSError("nope")
            ):
                out, code = capture(recipe.cmd_rm, ["demo"])
            self.assertEqual(code, 1)
            self.assertIn("Failed to remove recipe", out)

            with patch("trainsh.commands.recipe.prompt_input", return_value="y"):
                out, code = capture(recipe.cmd_rm, ["demo"])
            self.assertIsNone(code)
            self.assertIn("Recipe removed:", out)

            out, code = capture(recipe.cmd_rm, ["hello"])
            self.assertEqual(code, 1)
            self.assertIn("Bundled examples cannot be removed", out)

            out, code = capture(recipe.cmd_rm, ["missing"])
            self.assertEqual(code, 1)
            self.assertIn("Recipe not found", out)

            for sub in ["run", "resume", "status", "logs", "jobs", "schedule"]:
                out, code = capture(recipe.main, [sub])
                self.assertEqual(code, 1)
                self.assertIn("Use 'train recipe", out)

            out, code = capture(recipe.main, ["unknown"])
            self.assertEqual(code, 1)
            self.assertIn("Unknown subcommand", out)

            out, code = capture(recipe.main, ["--help"])
            self.assertIsNone(code)
            self.assertIn("train recipe", out)


class TransferCommandEdgeTests(unittest.TestCase):
    def test_transfer_parse_and_main_branch_paths(self):
        self.assertEqual(transfer.parse_endpoint("@gpu:/tmp/out"), ("host", "/tmp/out", "gpu"))
        self.assertEqual(transfer.parse_endpoint("@broken"), ("local", "@broken", None))
        self.assertEqual(transfer.parse_endpoint("host:gpu"), ("host", "gpu", None))
        self.assertEqual(transfer.parse_endpoint("storage:artifacts"), ("storage", "artifacts", None))

        out, code = capture(transfer.main, ["-e"])
        self.assertEqual(code, 1)
        self.assertIn("Missing value for --exclude.", out)

        with patch("trainsh.services.transfer_engine.TransferEngine") as mocked_engine:
            mocked_engine.return_value.rsync.return_value = SimpleNamespace(success=True, message="ok", bytes_transferred=0)
            out, code = capture(transfer.main, ["./src", "./dst", "--dry-run", "-d"])
        self.assertIsNone(code)
        self.assertIn("(dry run - no files will be transferred)", out)

        cloud = Storage(name="artifacts", type=StorageType.R2, config={"bucket": "bucket"})
        with patch("trainsh.services.transfer_engine.TransferEngine") as mocked_engine, patch(
            "trainsh.commands.storage.load_storages", return_value={"artifacts": cloud}
        ):
            mocked_engine.return_value.rclone.return_value = SimpleNamespace(success=False, message="boom", bytes_transferred=0)
            out, code = capture(transfer.main, ["storage:artifacts:/in", "./out"])
        self.assertEqual(code, 1)
        self.assertIn("Transfer failed: boom", out)

        with patch("trainsh.services.transfer_engine.TransferEngine") as mocked_engine:
            mocked_engine.return_value.transfer.return_value = SimpleNamespace(success=True, message="ok", bytes_transferred=42)
            out, code = capture(transfer.main, ["@gpu:/in", "@box:/out"])
        self.assertIsNone(code)
        self.assertIn("Use 'train host list' to see configured hosts.", out)
        self.assertIn("Transferred: 42 bytes", out)


if __name__ == "__main__":
    unittest.main()
