import unittest

from trainsh.config import get_default_config
from trainsh.core.executor_main import DSLExecutor, WindowInfo
from trainsh.core.remote_tmux import RemoteTmuxClient
from trainsh.core.executor_utils import _infer_window_hosts_from_recipe
from trainsh.core.dsl_parser import DSLRecipe, parse_recipe_string


class TmuxBridgeConfigTests(unittest.TestCase):
    def test_tmux_bridge_defaults_enabled(self):
        cfg = get_default_config()
        tmux_cfg = cfg.get("tmux", {})
        self.assertTrue(tmux_cfg.get("auto_bridge"))
        self.assertTrue(tmux_cfg.get("bridge_outside_tmux"))
        self.assertTrue(tmux_cfg.get("auto_enter_tmux"))
        self.assertTrue(tmux_cfg.get("prefer_bridge_exec"))
        self.assertEqual(tmux_cfg.get("bridge_remote_status"), "off")


class BridgeAttachCommandTests(unittest.TestCase):
    def _executor(self) -> DSLExecutor:
        recipe = DSLRecipe(name="test")
        return DSLExecutor(recipe, log_callback=lambda _msg: None, recipe_path=None)

    def test_local_attach_command(self):
        executor = self._executor()
        window = WindowInfo(name="work", host="local", remote_session="train_abcd_work")
        cmd = executor._build_bridge_attach_command(window)
        self.assertIn("TMUX= tmux attach -t train_abcd_work", cmd)
        self.assertIn("TMUX= tmux new-session -A -s train_abcd_work", cmd)

    def test_remote_attach_command_contains_ssh_and_tmux_attach(self):
        executor = self._executor()
        window = WindowInfo(
            name="gpu",
            host="root@example.com -p 2222 -i ~/.ssh/id_rsa",
            remote_session="train_abcd_gpu",
        )
        cmd = executor._build_bridge_attach_command(window)
        self.assertIn("ssh", cmd)
        self.assertIn("-p 2222", cmd)
        self.assertIn("root@example.com", cmd)
        self.assertIn("tmux attach -t train_abcd_gpu", cmd)
        self.assertIn("tmux new-session -A -s train_abcd_gpu", cmd)
        self.assertIn("tmux set-option -gq status off", cmd)


class ResumeHostInferenceTests(unittest.TestCase):
    def test_infer_window_hosts_from_tmux_open_steps(self):
        recipe = parse_recipe_string(
            """
host gpu = root@1.2.3.4 -p 22022
host localbox = local
tmux.open @gpu as train
tmux.open @localbox as localrun
@train > echo hi
"""
        )
        mapping = _infer_window_hosts_from_recipe(recipe, upto_step=4)
        self.assertEqual(mapping.get("train"), "root@1.2.3.4 -p 22022")
        self.assertEqual(mapping.get("localrun"), "local")


class TmuxClientFactoryTests(unittest.TestCase):
    def test_get_tmux_client_local_and_remote_cached(self):
        recipe = DSLRecipe(name="test")
        executor = DSLExecutor(recipe, log_callback=lambda _msg: None, recipe_path=None)

        local_client = executor.get_tmux_client("local")
        remote_a = executor.get_tmux_client("user@host -p 22")
        remote_b = executor.get_tmux_client("user@host -p 22")

        self.assertIs(local_client, executor.local_tmux)
        self.assertIsInstance(remote_a, RemoteTmuxClient)
        self.assertIs(remote_a, remote_b)


if __name__ == "__main__":
    unittest.main()
