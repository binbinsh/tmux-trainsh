import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.commands import host
from trainsh.core.models import AuthMethod, Host, HostType


@contextmanager
def patched_host_store():
    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        config_dir = Path(tmpdir) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        stack.enter_context(patch("trainsh.constants.CONFIG_DIR", config_dir))
        stack.enter_context(patch("trainsh.constants.HOSTS_FILE", config_dir / "hosts.yaml"))
        stack.enter_context(patch("trainsh.core.secrets.CONFIG_DIR", config_dir))
        stack.enter_context(patch("trainsh.core.secrets.CONFIG_FILE", config_dir / "config.yaml"))
        stack.enter_context(patch("trainsh.core.secrets._ENC_FILE", config_dir / "secrets.enc"))
        stack.enter_context(patch("trainsh.core.secrets._secrets_manager", None))
        stack.enter_context(patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("disabled in tests")))
        yield config_dir


def capture_output(fn, *args, **kwargs):
    stream = StringIO()
    code = None
    with redirect_stdout(stream):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return stream.getvalue(), code


class HostCommandDeepTests(unittest.TestCase):
    def _ssh_host(self, name="gpu-box", **overrides):
        data = dict(
            name=name,
            type=HostType.SSH,
            hostname="gpu.example.com",
            port=2222,
            username="root",
            auth_method=AuthMethod.KEY,
            ssh_key_path="~/.ssh/id_rsa",
            jump_host="jump.example.com",
            env_vars={
                "tunnel_type": "cloudflared",
                "cloudflared_hostname": "ssh.example.com",
                "proxy_command": "proxy-cmd",
                "connection_candidates": [
                    {"type": "ssh", "hostname": "gpu-alt", "port": 2200, "jump_host": "jump-alt"},
                    {"type": "cloudflared", "hostname": "cf.example.com", "cloudflared_bin": "/usr/bin/cloudflared"},
                ],
            },
        )
        data.update(overrides)
        return Host(**data)

    def _colab_host(self, name="colab-box", **overrides):
        data = dict(
            name=name,
            type=HostType.COLAB,
            hostname="cf.colab.example.com",
            port=22,
            username="root",
            auth_method=AuthMethod.PASSWORD,
            env_vars={"tunnel_type": "cloudflared", "cloudflared_hostname": "cf.colab.example.com"},
        )
        data.update(overrides)
        return Host(**data)

    def _vast_instance(self, **overrides):
        data = dict(
            id=123,
            label="vast-exited",
            actual_status="exited",
            template_name="tmpl",
            num_gpus=1,
            dph_total=0.5,
            disk_space=100.0,
            public_ipaddr="1.2.3.4",
            ports={"22/tcp": [{"HostPort": "2201"}]},
            direct_port_start=2200,
            direct_port_end=2205,
            ssh_host="proxy",
            ssh_port=2222,
        )
        data.update(overrides)
        return SimpleNamespace(**data)

    def test_candidate_helpers(self):
        self.assertEqual(host._normalize_connection_candidates(["a"]), ["a"])
        self.assertEqual(host._normalize_connection_candidates({"x": 1}), [{"x": 1}])
        self.assertEqual(host._normalize_connection_candidates("a, b"), ["a", "b"])
        self.assertEqual(host._normalize_connection_candidates(None), [])

        self.assertIn("ssh://gpu-alt:2200", host._render_connection_candidate_line(1, {"type": "ssh", "hostname": "gpu-alt", "port": 2200}))
        self.assertIn("jump=jump-alt", host._render_connection_candidate_line(1, {"type": "ssh", "hostname": "gpu-alt", "jump_host": "jump-alt"}))
        self.assertIn("(proxy)", host._render_connection_candidate_line(1, {"type": "ssh", "hostname": "gpu-alt", "proxy_command": "proxy"}))
        self.assertIn("cloudflared://cf.example.com", host._render_connection_candidate_line(2, {"type": "cloudflared", "hostname": "cf.example.com", "cloudflared_bin": "/usr/bin/cloudflared"}))
        self.assertIn("plain-text", host._render_connection_candidate_line(3, "plain-text"))

    def test_prompt_connection_candidates_and_int(self):
        with patch(
            "trainsh.commands.host.prompt_input",
            side_effect=[
                "y", "2", "cf.example.com", "/usr/bin/cloudflared",
                "y", "1", "gpu-alt", "2200", "jump-alt", "proxy-cmd",
                "n",
            ],
        ):
            candidates = host._prompt_connection_candidates()
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["type"], "cloudflared")
        self.assertEqual(candidates[1]["jump_host"], "jump-alt")

        with patch("trainsh.commands.host.prompt_input", side_effect=[None]):
            self.assertIsNone(host._prompt_connection_candidates())

        with patch("trainsh.commands.host.prompt_input", side_effect=["bad", "22"]):
            value = host._prompt_int("Port [22]: ", 22)
        self.assertEqual(value, 22)

        with patch("trainsh.commands.host.prompt_input", side_effect=[None]):
            self.assertIsNone(host._prompt_int("Port [22]: ", 22))
        with patch("trainsh.commands.host.prompt_input", side_effect=[""]):
            self.assertEqual(host._prompt_int("Port [22]: ", 22), 22)

        for side_effect, expected in [
            (["y", None], None),
            (["y", "2", None], None),
            (["y", "2", "", "n"], []),
            (["y", "2", "cf.example.com", None], None),
            (["y", "1", None], None),
            (["y", "1", "", "n"], []),
            (["y", "1", "gpu-alt", None], None),
            (["y", "1", "gpu-alt", "22", None], None),
            (["y", "1", "gpu-alt", "22", "", None], None),
        ]:
            with self.subTest(side_effect=side_effect, expected=expected):
                with patch("trainsh.commands.host.prompt_input", side_effect=side_effect):
                    result = host._prompt_connection_candidates()
                self.assertEqual(result, expected)

    def test_cmd_add_colab_cloudflared_and_ngrok(self):
        with patched_host_store():
            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=["colab-cf", "2", "cf.example.com"],
            ):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Added host: colab-cf", out)
            loaded = host.load_hosts()["colab-cf"]
            self.assertEqual(loaded.type, HostType.COLAB)
            self.assertEqual(loaded.env_vars["tunnel_type"], "cloudflared")

            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=["colab-ng", "3", "ngrok.example.com", "2200"],
            ):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Added host: colab-ng", out)
            loaded = host.load_hosts()["colab-ng"]
            self.assertEqual(loaded.port, 2200)
            self.assertEqual(loaded.env_vars["tunnel_type"], "ngrok")

    def test_cmd_add_standard_ssh_variants(self):
        with patched_host_store():
            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "gpu-key", "1", "gpu.example.com", "2222", "root",
                    "1", "~/.ssh/id_ed25519", "jump.example.com",
                    "y", "ssh.example.com", "/usr/bin/cloudflared",
                    "proxy-cmd",
                    "n",
                ],
            ):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            created = host.load_hosts()["gpu-key"]
            self.assertEqual(created.auth_method, AuthMethod.KEY)
            self.assertEqual(created.ssh_key_path, "~/.ssh/id_ed25519")
            self.assertEqual(created.jump_host, "jump.example.com")
            self.assertEqual(created.env_vars["cloudflared_hostname"], "ssh.example.com")
            self.assertEqual(created.env_vars["proxy_command"], "proxy-cmd")

            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "gpu-agent", "1", "gpu2.example.com", "22", "alice",
                    "2", "", "n", "", "n",
                ],
            ):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            created = host.load_hosts()["gpu-agent"]
            self.assertEqual(created.auth_method, AuthMethod.AGENT)
            self.assertIsNone(created.ssh_key_path)

            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "gpu-pass", "1", "gpu3.example.com", "22", "bob",
                    "3", "y", "", "n", "", "n",
                ],
            ), patch("trainsh.commands.host_interactive.getpass.getpass", return_value="pw-secret"):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            created = host.load_hosts()["gpu-pass"]
            self.assertEqual(created.auth_method, AuthMethod.PASSWORD)
            self.assertNotIn("ssh_password_secret", created.env_vars)

    def test_cmd_add_imports_private_key_into_secrets(self):
        with patched_host_store(), tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "id_ed25519"
            key_path.write_text("PRIVATE KEY\n", encoding="utf-8")
            secrets = MagicMock()
            with patch("trainsh.services.secret_materialize.get_secrets_manager", return_value=secrets), patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "gpu-secret", "1", "gpu.example.com", "22", "root",
                    "1", "secret", str(key_path), "", "n", "", "n",
                ],
            ):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Stored SSH private key in train secrets.", out)
            created = host.load_hosts()["gpu-secret"]
            self.assertIsNone(created.ssh_key_path)
            self.assertNotIn("ssh_key_secret", created.env_vars)
            secrets.set.assert_called_once()

    def test_cmd_add_stores_password_in_secrets(self):
        with patched_host_store():
            secrets = MagicMock()
            with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets), patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "gpu-pass-secret", "1", "gpu.example.com", "22", "root",
                    "3", "y", "", "n", "", "n",
                ],
            ), patch("trainsh.commands.host_interactive.getpass.getpass", return_value="supersecret"):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Stored SSH password in train secrets.", out)
            created = host.load_hosts()["gpu-pass-secret"]
            self.assertNotIn("ssh_password_secret", created.env_vars)
            secrets.set.assert_called_once_with("GPU_PASS_SECRET_SSH_PASSWORD", "supersecret")

    def test_cmd_add_cancellation_and_required_fields(self):
        with patched_host_store():
            with patch("trainsh.commands.host.prompt_input", side_effect=[None]):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertEqual(out, "Add new host\n----------------------------------------\n")

            with patch("trainsh.commands.host.prompt_input", side_effect=["",]):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Cancelled - name is required.", out)

            with patch("trainsh.commands.host.prompt_input", side_effect=["demo", "2", ""]):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Cancelled - hostname is required.", out)

            with patch("trainsh.commands.host.prompt_input", side_effect=["demo2", "1", "",]):
                out, code = capture_output(host.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Cancelled - hostname is required.", out)

            for side_effect in [
                ["demo2a", "2", None],
                ["demo3", None],
                ["demo4", "3", None],
                ["demo4a", "3", "", "2200"],
                ["demo5", "3", "ngrok.example.com", None],
                ["demo5a", "3", "ngrok.example.com", ""],
                ["demo6", "1", None],
                ["demo7", "1", "gpu.example.com", "22", None],
                ["demo8", "1", "gpu.example.com", "22", "root", None],
                ["demo9", "1", "gpu.example.com", "22", "root", "1", None],
                ["demo10", "1", "gpu.example.com", "22", "root", "1", "~/.ssh/id", None],
                ["demo11", "1", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", None],
                ["demo12", "1", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", None],
                ["demo12a", "1", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", "ssh.example.com", None],
                ["demo12b", "1", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", "", "cloudflared", ""],
                ["demo13", "1", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", "", "cloudflared", ""],
                ["demo14", "1", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", "ssh.example.com", "cloudflared", None],
            ]:
                with patch("trainsh.commands.host.prompt_input", side_effect=side_effect):
                    out, code = capture_output(host.cmd_add, [])
                self.assertIsNone(code)

    def test_cmd_tunnel_supports_background_mode(self):
        target = self._ssh_host()
        fake_process = SimpleNamespace(pid=12345)
        with patch("trainsh.commands.host.load_hosts", return_value={"gpu-box": target}), patch(
            "trainsh.commands.host.start_local_tunnel",
            return_value=fake_process,
        ) as mocked_start:
            out, code = capture_output(
                host.cmd_tunnel,
                ["gpu-box", "--local-port", "18000", "--remote-port", "8000", "--background"],
            )

        self.assertIsNone(code)
        self.assertIn("Tunnel ready in background", out)
        mocked_start.assert_called_once()

    def test_cmd_edit_ssh_branch_updates_and_reconfigures_candidates(self):
        with patched_host_store():
            host.save_hosts({"gpu-box": self._ssh_host()})
            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "gpu-renamed",         # new name
                    "gpu2.example.com",    # hostname
                    "2200",                # port
                    "alice",               # username
                    "2",                   # auth method -> agent
                    "",                    # jump host cleared
                    "n",                   # disable cloudflared
                    "",                    # clear proxy command
                    "y",                   # reconfigure candidates
                    "y", "1", "gpu-new", "2201", "", "", "n",  # one new candidate
                ],
            ):
                out, code = capture_output(host.cmd_edit, ["gpu-box"])
            self.assertIsNone(code)
            self.assertIn("Updated host: gpu-renamed", out)
            edited = host.load_hosts()["gpu-renamed"]
            self.assertEqual(edited.hostname, "gpu2.example.com")
            self.assertEqual(edited.port, 2200)
            self.assertEqual(edited.username, "alice")
            self.assertEqual(edited.auth_method, AuthMethod.AGENT)
            self.assertIsNone(edited.ssh_key_path)
            self.assertNotIn("tunnel_type", edited.env_vars)
            self.assertNotIn("proxy_command", edited.env_vars)
            self.assertEqual(edited.env_vars["connection_candidates"][0]["hostname"], "gpu-new")

    def test_cmd_show_hides_secret_names(self):
        with patched_host_store():
            host.save_hosts(
                {
                    "gpu-box": self._ssh_host(
                        ssh_key_path=None,
                        auth_method=AuthMethod.PASSWORD,
                        env_vars={"ssh_password_secret": "GPU_BOX_SSH_PASSWORD"},
                    )
                }
            )
            secrets = SimpleNamespace(exists=lambda key: key == "GPU_BOX_SSH_PASSWORD")
            with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets):
                out, code = capture_output(host.cmd_show, ["gpu-box"])
            self.assertIsNone(code)
            self.assertIn("SSH Password: managed by train secrets", out)
            self.assertNotIn("GPU_BOX_SSH_PASSWORD", out)

    def test_cmd_edit_ssh_conflict_and_validation_paths(self):
        with patched_host_store():
            host.save_hosts({"gpu-box": self._ssh_host(), "other": self._ssh_host(name="other")})

            with patch("trainsh.commands.host.prompt_input", side_effect=["other"]):
                out, code = capture_output(host.cmd_edit, ["gpu-box"])
            self.assertEqual(code, 1)
            self.assertIn("Host already exists: other", out)

            with patch("trainsh.commands.host.prompt_input", side_effect=["",]):
                out, code = capture_output(host.cmd_edit, ["gpu-box"])
            self.assertIsNone(code)
            self.assertIn("Cancelled - name is required.", out)

            with patch("trainsh.commands.host.prompt_input", side_effect=["gpu-box", "",]):
                out, code = capture_output(host.cmd_edit, ["gpu-box"])
            self.assertIsNone(code)
            self.assertIn("Cancelled - hostname is required.", out)

            cancel_cases = [
                ["gpu-box", None],
                ["gpu-box", "gpu.example.com", None],
                ["gpu-box", "gpu.example.com", "22", None],
                ["gpu-box", "gpu.example.com", "22", "root", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", "ssh.example.com", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", "", "cloudflared"],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "y", "ssh.example.com", "cloudflared", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "n", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "n", "", None],
                ["gpu-box", "gpu.example.com", "22", "root", "1", "~/.ssh/id", "", "n", "", "y", None],
            ]
            for side_effect in cancel_cases:
                with patch("trainsh.commands.host.prompt_input", side_effect=side_effect):
                    out, code = capture_output(host.cmd_edit, ["gpu-box"])
                self.assertIsNone(code)

    def test_cmd_edit_colab_branch_and_unsupported_type(self):
        with patched_host_store():
            host.save_hosts({"colab-box": self._colab_host()})
            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "colab-updated",
                    "ngrok.example.com",
                    "root",
                    "2",
                    "2200",
                ],
            ):
                out, code = capture_output(host.cmd_edit, ["colab-box"])
            self.assertIsNone(code)
            edited = host.load_hosts()["colab-updated"]
            self.assertEqual(edited.hostname, "ngrok.example.com")
            self.assertEqual(edited.port, 2200)
            self.assertEqual(edited.env_vars["tunnel_type"], "ngrok")

            host.save_hosts({"colab-cf": self._colab_host(name="colab-cf")})
            with patch(
                "trainsh.commands.host.prompt_input",
                side_effect=[
                    "colab-cf",
                    "cf2.example.com",
                    "root",
                    "1",
                    "cf2.example.com",
                    "cloudflared",
                    "",
                ],
            ):
                out, code = capture_output(host.cmd_edit, ["colab-cf"])
            self.assertIsNone(code)
            edited = host.load_hosts()["colab-cf"]
            self.assertEqual(edited.port, 22)
            self.assertEqual(edited.env_vars["cloudflared_hostname"], "cf2.example.com")

            host.save_hosts({"colab-box": self._colab_host()})
            for side_effect in [
                ["colab-box", None],
                ["colab-box", "",],
                ["colab-box", "host", None],
                ["colab-box", "host", "root", None],
                ["colab-box", "host", "root", "2", None],
                ["colab-box", "host", "root", "1", None],
                ["colab-box", "host", "root", "1", "",],
                ["colab-box", "host", "root", "1", "cf.example.com", None],
                ["colab-box", "host", "root", "1", "cf.example.com", "cloudflared", None],
            ]:
                with patch("trainsh.commands.host.prompt_input", side_effect=side_effect):
                    out, code = capture_output(host.cmd_edit, ["colab-box"])
                self.assertIsNone(code)

            vast_host = Host(name="vast-box", type=HostType.VASTAI, hostname="vast", username="root", vast_instance_id="77")
            host.save_hosts({"vast-box": vast_host})
            client = SimpleNamespace(label_instance=MagicMock())
            with patch("trainsh.commands.host.prompt_input", side_effect=["vast renamed"]), patch(
                "trainsh.services.vast_api.get_vast_client", return_value=client
            ):
                out, code = capture_output(host.cmd_edit, ["vast-box"])
            self.assertIsNone(code)
            self.assertIn("Updated Vast.ai label: vast renamed", out)
            self.assertIn("Host alias: vast-renamed", out)
            client.label_instance.assert_called_once_with(77, "vast renamed")

    def test_cmd_edit_missing_and_main_add_dispatch(self):
        with patched_host_store():
            out, code = capture_output(host.cmd_edit, [])
            self.assertEqual(code, 1)
            self.assertIn("Usage: train host edit <name>", out)

            out, code = capture_output(host.cmd_edit, ["missing"])
            self.assertEqual(code, 1)
            self.assertIn("Host not found: missing", out)

            with patch("trainsh.commands.host.cmd_add") as mocked_add:
                out, code = capture_output(host.main, ["add"])
            self.assertIsNone(code)
            mocked_add.assert_called_once_with([])

    def test_cmd_browse_loop_paths(self):
        with patched_host_store():
            host.save_hosts({"gpu-box": self._ssh_host()})
            browser = SimpleNamespace(
                navigate=lambda path: [
                    SimpleNamespace(name="logs", path="/tmp/logs", is_dir=True, icon="D", display_size="<DIR>"),
                    SimpleNamespace(name="train.txt", path="/tmp/train.txt", is_dir=False, icon="F", display_size="10 B", permissions="-rw-r--r--"),
                ],
                get_home_directory=lambda: "/home/demo",
                path_exists=lambda path: path == "/ok",
                read_file_head=lambda path, lines=30: "head\n",
            )
            ssh = SimpleNamespace(test_connection=lambda: True)
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh), patch(
                "trainsh.services.sftp_browser.RemoteFileBrowser", return_value=browser
            ), patch(
                "builtins.input",
                side_effect=[
                    "h",
                    "/train",
                    "v",
                    "0",
                    "c",
                    "5",
                    "cd /missing",
                    "cd /ok",
                    "..",
                    "~",
                    "q",
                ],
            ), patch("subprocess.run", side_effect=RuntimeError("pbcopy missing")):
                out, code = capture_output(host.cmd_browse, ["gpu-box", "/tmp"])
            self.assertIsNone(code)
            self.assertIn("Hidden files:", out)
            self.assertIn("Search: train", out)
            self.assertIn("File: /tmp/train.txt", out)
            self.assertIn("Permissions: -rw-r--r--", out)
            self.assertIn("Invalid index: 5", out)
            self.assertIn("Path not found: /missing", out)

            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=SimpleNamespace(test_connection=lambda: False)):
                out, code = capture_output(host.cmd_browse, ["gpu-box"])
            self.assertEqual(code, 1)
            self.assertIn("Connection failed.", out)

    def test_cmd_browse_usage_missing_host_and_eof_exit(self):
        with patched_host_store():
            out, code = capture_output(host.cmd_browse, [])
            self.assertEqual(code, 1)
            self.assertIn("Usage: train host files <name> [path]", out)

            out, code = capture_output(host.cmd_browse, ["missing"])
            self.assertEqual(code, 1)
            self.assertIn("Host not found: missing", out)

            host.save_hosts({"gpu-box": self._ssh_host()})
            browser = SimpleNamespace(
                navigate=lambda path: [
                    SimpleNamespace(name="logs", path="/tmp/logs", is_dir=True, icon="D", display_size="<DIR>"),
                ],
                get_home_directory=lambda: "/home/demo",
                path_exists=lambda path: False,
                read_file_head=lambda path, lines=30: "head\n",
            )
            ssh = SimpleNamespace(test_connection=lambda: True)
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh), patch(
                "trainsh.services.sftp_browser.RemoteFileBrowser", return_value=browser
            ), patch("builtins.input", side_effect=["0", EOFError()]):
                out, code = capture_output(host.cmd_browse, ["gpu-box", "/tmp"])
            self.assertIsNone(code)
            self.assertIn("Exiting.", out)

            browser = SimpleNamespace(
                navigate=lambda path: [
                    SimpleNamespace(name="train.txt", path="/tmp/train.txt", is_dir=False, icon="F", display_size="10 B", permissions="-rw-r--r--"),
                ],
                get_home_directory=lambda: "/home/demo",
                path_exists=lambda path: False,
                read_file_head=lambda path, lines=30: "line1\nline2\n",
            )
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh), patch(
                "trainsh.services.sftp_browser.RemoteFileBrowser", return_value=browser
            ), patch("builtins.input", side_effect=["0", "v", "q"]):
                out, code = capture_output(host.cmd_browse, ["gpu-box", "/tmp"])
            self.assertIsNone(code)
            self.assertIn("line1", out)

            browser = SimpleNamespace(
                navigate=lambda path: [
                    SimpleNamespace(name="train.txt", path="/tmp/train.txt", is_dir=False, icon="F", display_size="10 B", permissions="-rw-r--r--"),
                ],
                get_home_directory=lambda: "/home/demo",
                path_exists=lambda path: False,
                read_file_head=lambda path, lines=30: "head\n",
            )
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh), patch(
                "trainsh.services.sftp_browser.RemoteFileBrowser", return_value=browser
            ), patch("builtins.input", side_effect=["", "0", "c", "q"]), patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
                out, code = capture_output(host.cmd_browse, ["gpu-box", "/tmp"])
            self.assertIsNone(code)
            self.assertIn("Copied to clipboard!", out)

    def test_auto_discovered_vast_host_supports_host_commands(self):
        with patched_host_store():
            browser = SimpleNamespace(
                navigate=lambda path: [],
                get_home_directory=lambda: "/home/demo",
                path_exists=lambda path: False,
                read_file_head=lambda path, lines=30: "head\n",
            )
            ssh = SimpleNamespace(test_connection=lambda: True, connect_interactive=lambda: 0)
            client = SimpleNamespace(
                list_instances=lambda: [self._vast_instance()],
                rm_instance=MagicMock(),
            )

            with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
                loaded = host.load_hosts()
                self.assertIn("vast-exited", loaded)
                self.assertEqual(loaded["vast-exited"].vast_status, "exited")

                out, code = capture_output(host.cmd_list, [])
                self.assertIsNone(code)
                self.assertIn("vast-exited", out)
                self.assertIn("exited", out)
                self.assertIn("src=ports:22/tcp", out)

                out, code = capture_output(host.cmd_show, ["vast-exited"])
                self.assertIsNone(code)
                self.assertIn("Auto-discovered: yes", out)
                self.assertIn("Connection Source: ports:22/tcp", out)

                with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh):
                    out, code = capture_output(host.cmd_test, ["vast-exited"])
                    self.assertIsNone(code)
                    self.assertIn("Connection successful!", out)

                    out, code = capture_output(host.cmd_ssh, ["vast-exited"])
                    self.assertIsNone(code)
                    self.assertIn("Connecting to Vast.ai #123", out)

                    with patch("trainsh.services.sftp_browser.RemoteFileBrowser", return_value=browser), patch(
                        "builtins.input", side_effect=["q"]
                    ):
                        out, code = capture_output(host.cmd_browse, ["vast-exited"])
                    self.assertIsNone(code)
                    self.assertIn("File Browser: Vast.ai #123", out)

                with patch("trainsh.commands.host.prompt_input", return_value="y"):
                    out, code = capture_output(host.cmd_rm, ["vast-exited"])
                self.assertIsNone(code)
                self.assertIn("Vast.ai instance removed: 123", out)
                client.rm_instance.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
