import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trainsh import load_python_recipe
from trainsh.core.executor_main import run_recipe
from trainsh.core.local_tmux import TmuxCmdResult


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "trainsh" / "examples"


class FakeLocalTmux:
    def __init__(self):
        self.sessions = set()
        self.sent = []
        self.killed = []

    def has_session(self, name: str) -> bool:
        return name in self.sessions

    def new_session(self, name: str, detached: bool = True, window_name=None, command=None) -> TmuxCmdResult:
        self.sessions.add(name)
        return TmuxCmdResult(0, "", "")

    def send_keys(self, target: str, text: str, enter: bool = True, literal: bool = True) -> TmuxCmdResult:
        self.sent.append((target, text, enter, literal))
        return TmuxCmdResult(0, "", "")

    def wait_for(self, signal: str, timeout: int = 1) -> TmuxCmdResult:
        return TmuxCmdResult(0, "", "")

    def kill_session(self, name: str) -> TmuxCmdResult:
        self.killed.append(name)
        self.sessions.discard(name)
        return TmuxCmdResult(0, "", "")


class BundledExampleSmokeTests(unittest.TestCase):
    def test_all_bundled_examples_load_with_public_api(self):
        expected = {
            "aptup.py": "aptup",
            "brewup.py": "brewup",
            "hello.py": "hello-world",
            "nanochat.py": "nanochat",
        }

        for path in sorted(EXAMPLES_DIR.glob("*.py")):
            with self.subTest(example=path.name):
                recipe = load_python_recipe(str(path))
                self.assertEqual(recipe.name, expected[path.name])
                self.assertGreater(recipe.step_count(), 0)

    def test_local_bundled_examples_run_under_fake_tmux(self):
        cases = {
            "brewup.py": [
                "brew update",
                "brew upgrade",
                "brew upgrade --greedy --cask $(brew list --cask)",
                "brew cleanup",
            ],
            "aptup.py": [
                "sudo apt update",
                "sudo apt -y dist-upgrade",
                "sudo apt -y autoremove",
            ],
            "hello.py": [
                "printf",
                "Hello from trainsh",
            ],
        }

        for filename, expected_snippets in cases.items():
            with self.subTest(example=filename):
                fake_tmux = FakeLocalTmux()
                recipe_path = EXAMPLES_DIR / filename

                with tempfile.TemporaryDirectory() as tmpdir:
                    config_dir = Path(tmpdir) / "config"
                    config_dir.mkdir(parents=True, exist_ok=True)

                    with patch("trainsh.core.executor_main.CONFIG_DIR", config_dir), patch(
                        "trainsh.runtime.CONFIG_DIR", config_dir
                    ), patch(
                        "trainsh.core.executor_main.load_config",
                        return_value={
                            "tmux": {"auto_bridge": False},
                            "notifications": {"enabled": False},
                        },
                    ), patch(
                        "trainsh.core.executor_main.LocalTmuxClient",
                        return_value=fake_tmux,
                    ):
                        ok = run_recipe(str(recipe_path), job_id=f"job-{recipe_path.stem}-smoke")

                self.assertTrue(ok)
                joined_commands = "\n".join(item[1] for item in fake_tmux.sent)
                for snippet in expected_snippets:
                    self.assertIn(snippet, joined_commands)
                self.assertFalse(fake_tmux.sessions)
                self.assertEqual(len(fake_tmux.killed), 1)

    def test_nanochat_example_declares_auto_pick_and_eval_flow(self):
        recipe = load_python_recipe(str(EXAMPLES_DIR / "nanochat.py"))
        steps = {step.id: step for step in recipe.steps}

        self.assertEqual(recipe.name, "nanochat")
        self.assertEqual(steps["pick_h200"].params["gpu_name"], "H200")
        self.assertTrue(steps["pick_h200"].params["auto_select"])
        self.assertTrue(steps["pick_h200"].params["create_if_missing"])
        self.assertEqual(steps["pick_h100"].params["gpu_name"], "H100")
        self.assertIn("trainsh_nanochat.sh", steps["write_runner"].raw)
        self.assertIn("scripts.chat_eval", steps["write_runner"].raw)
        self.assertIn("wait_success_flag", steps)
        self.assertIn("copy_success_flag", steps)
        self.assertIn("stop_instance", steps)


if __name__ == "__main__":
    unittest.main()
