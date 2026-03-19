import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.core.executor_utils import (
    _build_ssh_args,
    _format_duration,
    _host_from_ssh_spec,
    _infer_window_hosts_from_recipe,
    _resolve_vast_host,
    _split_ssh_spec,
    _test_ssh_connection,
)
from trainsh.core.local_tmux import LocalTmuxClient, TmuxCmdResult
from trainsh.core.models import AuthMethod, Host, HostType
from trainsh.core.recipe_models import RecipeModel, RecipeStepModel, StepType
from trainsh.core.remote_tmux import RemoteTmuxClient


class LocalTmuxClientTests(unittest.TestCase):
    def test_unavailable_and_basic_wrappers(self):
        with patch("shutil.which", return_value=None):
            client = LocalTmuxClient()
        self.assertFalse(client.available)
        self.assertEqual(client.backend, "unavailable")
        self.assertEqual(client.run("list-sessions").returncode, 127)

        with patch("shutil.which", return_value="/usr/bin/tmux"), patch(
            "subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        ):
            client = LocalTmuxClient()
            self.assertTrue(client.available)
            self.assertEqual(client._tmux_env()["TERM"], "xterm-256color")
            self.assertEqual(client.run_line("tmux list-sessions").stdout, "ok\n")
            self.assertTrue(client.has_session("demo"))
            self.assertTrue(client.list_sessions())
            self.assertTrue(client.list_windows("demo"))
            self.assertTrue(client.list_panes("demo"))
            self.assertEqual(client.display_message("demo", "#{session_name}").stdout, "ok\n")
            self.assertEqual(client.split_window("demo", "echo hi", horizontal=True).stdout, "ok\n")
            self.assertEqual(client.set_pane_title("%1", "main").stdout, "ok\n")
            self.assertEqual(client.select_layout("demo", "tiled").stdout, "ok\n")
            self.assertEqual(client.kill_pane("%1").stdout, "ok\n")
            self.assertEqual(client.capture_pane("%1", start=-10).stdout, "ok\n")
            self.assertEqual(client.wait_for("sig").stdout, "ok\n")
            self.assertIn("tmux attach", client.build_attach_command("demo"))

        with patch("shutil.which", return_value="/usr/bin/tmux"), patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("tmux", 1)
        ):
            client = LocalTmuxClient()
            self.assertEqual(client.run("list-sessions").returncode, 124)

        with patch("shutil.which", return_value="/usr/bin/tmux"), patch(
            "subprocess.run", side_effect=RuntimeError("boom")
        ):
            client = LocalTmuxClient()
            self.assertEqual(client.run("list-sessions").returncode, 1)

    def test_new_session_and_send_keys_paths(self):
        with patch("shutil.which", return_value="/usr/bin/tmux"), patch(
            "subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")
        ):
            client = LocalTmuxClient()
            self.assertEqual(client.new_session("demo", detached=False).returncode, 0)

        result_iter = iter([TmuxCmdResult(0, "", ""), TmuxCmdResult(0, "", "")])
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            client = LocalTmuxClient()
            with patch.object(client, "run", side_effect=lambda *args, **kwargs: next(result_iter)):
                self.assertEqual(client.send_keys("%1", "echo hi").returncode, 0)

        with patch("shutil.which", return_value="/usr/bin/tmux"):
            client = LocalTmuxClient()
            with patch.object(client, "run", return_value=TmuxCmdResult(1, "", "bad")):
                self.assertEqual(client.send_keys("%1", "echo hi").returncode, 1)


class RemoteTmuxClientTests(unittest.TestCase):
    def test_remote_tmux_builders_and_wrappers(self):
        build_args = lambda host, command=None, tty=False, set_term=False: ["ssh", host, command or ""]
        client = RemoteTmuxClient("gpu", build_args)

        self.assertIn("ssh", client.build_shell_command("echo hi"))
        self.assertIn("attach", client.build_attach_command("demo", status_mode="keep"))
        self.assertIn("status-position bottom", client.build_attach_command("demo", status_mode="bottom"))

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")):
            self.assertEqual(client.run("list-sessions").stdout, "ok\n")
            self.assertTrue(client.has_session("demo"))
            self.assertTrue(client.list_sessions())
            self.assertTrue(client.list_windows("demo"))
            self.assertTrue(client.list_panes("demo"))
            self.assertEqual(client.display_message("demo", "#{session_name}").stdout, "ok\n")
            self.assertEqual(client.split_window("demo", "echo hi", horizontal=False).stdout, "ok\n")
            self.assertEqual(client.set_pane_title("%1", "main").stdout, "ok\n")
            self.assertEqual(client.select_layout("demo", "tiled").stdout, "ok\n")
            self.assertEqual(client.kill_pane("%1").stdout, "ok\n")
            self.assertEqual(client.capture_pane("%1", start=-10).stdout, "ok\n")
            self.assertEqual(client.wait_for("sig").stdout, "ok\n")

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)):
            self.assertEqual(client.run("list-sessions").returncode, 124)
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            self.assertEqual(client.run("list-sessions").returncode, 1)

        result_iter = iter([TmuxCmdResult(0, "", ""), TmuxCmdResult(0, "", "")])
        with patch.object(client, "_run_tmux", side_effect=lambda args, timeout=None: next(result_iter)):
            self.assertEqual(client.send_keys("%1", "echo hi").returncode, 0)
        with patch.object(client, "_run_tmux", return_value=TmuxCmdResult(1, "", "bad")):
            self.assertEqual(client.send_keys("%1", "echo hi").returncode, 1)

    def test_write_text_tilde_path(self):
        client = RemoteTmuxClient("gpu", lambda host, command=None, tty=False, set_term=False: ["ssh", host, command or ""])
        with patch.object(client, "_run_shell", return_value=TmuxCmdResult(0, "", "")) as mocked:
            client.write_text("~/demo.txt", "hello")
            client.write_text("~", "hello")
        self.assertEqual(mocked.call_count, 2)


class ExecutorUtilsTests(unittest.TestCase):
    def test_ssh_spec_split_build_and_host_parsing(self):
        host, options = _split_ssh_spec("root@example -p 2200 -J jump")
        self.assertEqual(host, "root@example")
        self.assertIn("-p", options)
        args = _build_ssh_args("root@example -p 2200", command="echo hi", tty=True, set_term=True)
        self.assertIn("-t", args)
        self.assertIn("TERM=xterm-256color", args[-1])

        parsed = _host_from_ssh_spec("root@example -p 2200 -i ~/.ssh/id_rsa -J jump -o ProxyCommand=proxy")
        self.assertEqual(parsed.hostname, "example")
        self.assertEqual(parsed.port, 2200)
        self.assertEqual(parsed.jump_host, "jump")
        self.assertEqual(parsed.env_vars["proxy_command"], "proxy")

        configured = Host(
            name="gpu-box",
            type=HostType.SSH,
            hostname="gpu.example.com",
            port=2200,
            username="root",
            auth_method=AuthMethod.KEY,
        )
        fake_client = SimpleNamespace(
            _build_ssh_args=lambda command=None, interactive=False: [
                "ssh",
                "-p",
                "2200",
                "root@gpu.example.com",
                command or "",
            ]
        )
        with patch("trainsh.commands.host.load_hosts", return_value={"gpu-box": configured}), patch(
            "trainsh.services.ssh.SSHClient.from_host",
            return_value=fake_client,
        ):
            alias_args = _build_ssh_args("gpu-box", command="echo hi", tty=True, set_term=True)
            alias_host = _host_from_ssh_spec("gpu-box")
        self.assertEqual(alias_args[:2], ["ssh", "-t"])
        self.assertIn("TERM=xterm-256color", alias_args[-1])
        self.assertEqual(alias_host.hostname, "gpu.example.com")
        self.assertEqual(alias_host.port, 2200)

        self.assertEqual(_format_duration(3661), "1h01m01s")
        self.assertEqual(_format_duration(61), "1m01s")
        self.assertEqual(_format_duration(5), "5s")

        recipe = RecipeModel(
            name="demo",
            hosts={"gpu": "root@example"},
            steps=[
                RecipeStepModel(type=StepType.CONTROL, line_num=0, raw="tmux.open @gpu as main", command="tmux.open", args=["@gpu", "as", "main"]),
                RecipeStepModel(type=StepType.CONTROL, line_num=0, raw="noop"),
            ],
        )
        self.assertEqual(_infer_window_hosts_from_recipe(recipe, 1), {"main": "root@example"})

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")):
            self.assertTrue(_test_ssh_connection("host", 22))
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            self.assertFalse(_test_ssh_connection("host", 22))

        instance = SimpleNamespace(
            public_ipaddr="1.2.3.4",
            ports={"22/tcp": [{"HostPort": "2201"}]},
            direct_port_start=2200,
            ssh_host="proxy",
            ssh_port=2222,
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda instance_id: instance)), patch(
            "trainsh.core.executor_utils._test_ssh_connection", side_effect=[True]
        ):
            resolved = _resolve_vast_host("7")
            self.assertIn("1.2.3.4", resolved)
            self.assertIn("-p 2201", resolved)
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda instance_id: instance)), patch(
            "trainsh.core.executor_utils._test_ssh_connection", side_effect=[False, True]
        ):
            resolved = _resolve_vast_host("7")
            self.assertIn("1.2.3.4", resolved)
            self.assertIn("-p 2200", resolved)
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda instance_id: instance)), patch(
            "trainsh.core.executor_utils._test_ssh_connection", side_effect=[False, False, False]
        ):
            resolved = _resolve_vast_host("7")
            self.assertIn("1.2.3.4", resolved)
            self.assertIn("-p 2201", resolved)
        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom")):
            self.assertEqual(_resolve_vast_host("7"), "vast-7")


if __name__ == "__main__":
    unittest.main()
