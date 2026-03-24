import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from trainsh.commands import vast
from trainsh.core.executor_vast import VastControlHelper
from trainsh.core.models import VastInstance, VastOffer
from trainsh.services.vast_api import VastAPIClient, VastAPIError, get_vast_client
from trainsh.services.vast_connection import preferred_vast_ssh_target, vast_ssh_targets
from trainsh.utils import vast_formatter


def capture_output(fn, *args, **kwargs):
    stream = io.StringIO()
    with redirect_stdout(stream):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            return stream.getvalue(), exc.code
    return stream.getvalue(), None


class VastApiClientTests(unittest.TestCase):
    def test_request_and_parse_helpers(self):
        client = VastAPIClient("token")

        response = MagicMock()
        response.read.return_value = b'{"instances": [{"id": 1, "actual_status": "running"}]}'
        response.__enter__.return_value = response
        with patch("trainsh.services.vast_api.urlopen", return_value=response):
            data = client._request("instances")
        self.assertEqual(data["instances"][0]["id"], 1)

        http_error = VastAPIError(500, "boom")
        http_error = HTTPError("u", 500, "err", None, None)
        self.addCleanup(http_error.close)
        with patch("trainsh.services.vast_api.urlopen", side_effect=http_error):
            with self.assertRaises(VastAPIError):
                client._request("instances")

        with patch("trainsh.services.vast_api.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(VastAPIError):
                client._request("instances")

        with patch.object(client, "_request", return_value={"instances": [{"id": 1, "actual_status": "running"}]}):
            instances = client.list_instances()
        self.assertEqual(instances[0].id, 1)
        self.assertTrue(instances[0].is_running)

        with patch.object(client, "_request", return_value={"instances": {"id": 2, "ssh_host": "h", "ssh_port": 22}}):
            inst = client.get_instance(2)
        self.assertEqual(client.get_ssh_command(inst), "ssh -p 22 root@h")

        with patch.object(
            client,
            "_request",
            return_value={"instances": {"id": 3, "public_ipaddr": "1.2.3.4", "ports": {"22/tcp": [{"HostPort": "2201"}]}, "ssh_host": "proxy", "ssh_port": 2222}},
        ):
            inst = client.get_instance(3)
        self.assertEqual(client.get_ssh_command(inst), "ssh -p 2201 root@1.2.3.4")

        with patch.object(client, "_request", return_value={"offers": [{"id": 9, "gpu_name": "A100", "gpu_ram": 81920}]}):
            offers = client.search_offers(gpu_name="a100", num_gpus=2, min_gpu_ram=80, max_dph=4.5, limit=3)
        self.assertEqual(offers[0].id, 9)
        self.assertEqual(offers[0].display_gpu_ram, "80 GB")

        with patch.object(client, "_request", return_value={"new_contract": 99}) as mocked:
            new_id = client.create_instance(offer_id=7, image="pytorch/pytorch:latest", direct=True)
        self.assertEqual(new_id, 99)
        self.assertIn("ssh_direc ssh_proxy", mocked.call_args.kwargs["data"]["runtype"])

        with patch.object(client, "_request", return_value={}), self.assertRaises(VastAPIError):
            client.create_instance(offer_id=7, image="img")

        with patch.object(client, "_request", return_value=[{"ssh_key": "ssh-ed25519 AAA"}]):
            self.assertEqual(client.list_ssh_keys()[0]["ssh_key"], "ssh-ed25519 AAA")
        with patch.object(client, "_request", return_value={"ssh_keys": [{"ssh_key": "ssh-rsa BBB"}]}):
            self.assertEqual(client.list_ssh_keys()[0]["ssh_key"], "ssh-rsa BBB")

        with patch.object(client, "_request") as mocked:
            client.start_instance(1)
            client.stop_instance(1)
            client.rm_instance(1)
            client.reboot_instance(1)
            client.recycle_instance(1)
            client.label_instance(1, "demo")
            client.execute_command(1, "echo hi")
            client.add_ssh_key("ssh-rsa AAA")
            client.delete_ssh_key(3)
        self.assertGreaterEqual(mocked.call_count, 9)

    def test_get_vast_client_uses_secrets_manager(self):
        secrets = SimpleNamespace(get_vast_api_key=lambda: "token")
        with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets):
            client = get_vast_client()
        self.assertIsInstance(client, VastAPIClient)

        secrets = SimpleNamespace(get_vast_api_key=lambda: "")
        with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets):
            with self.assertRaises(RuntimeError):
                get_vast_client()


class VastFormatterTests(unittest.TestCase):
    def make_instance(self):
        return VastInstance(
            id=1,
            actual_status="running",
            gpu_name="A100",
            num_gpus=2,
            gpu_ram=81920,
            dph_total=1.5,
            storage_cost=0.1,
            cpu_name="EPYC",
            cpu_cores=16,
            cpu_ram=65536,
            disk_space=500,
            disk_usage=30,
            ssh_host="proxy",
            ssh_port=2222,
            public_ipaddr="1.2.3.4",
            direct_port_start=2200,
            geolocation="CN",
            reliability2=0.98,
            template_name="tmpl",
            label="demo",
        )

    def test_currency_settings_and_formatters(self):
        rates = SimpleNamespace(convert=lambda amount, _from, _to: amount * 7)
        settings = SimpleNamespace(exchange_rates=rates)
        with patch("trainsh.utils.vast_formatter.load_pricing_settings", return_value=settings), patch(
            "trainsh.utils.vast_formatter.load_config", return_value={"ui": {"currency": "CNY"}}
        ):
            currency = vast_formatter.get_currency_settings()
        self.assertEqual(currency.display_currency, "CNY")
        self.assertIn("$1.500", currency.format_price(1.5))

        inst = self.make_instance()
        row = vast_formatter.format_instance_row(inst, currency, show_index=True, index=1)
        header, sep = vast_formatter.format_instance_header(currency, show_index=True)
        detail = vast_formatter.format_instance_detail(inst, currency)
        brief = vast_formatter.format_instance_brief(inst, currency)
        self.assertIn("A100", row)
        self.assertIn("CNY/hr", header)
        self.assertTrue(sep.startswith("-"))
        self.assertIn("GPU: A100 x2", detail)
        self.assertIn("#1 running", brief)

        out = io.StringIO()
        with redirect_stdout(out), patch.object(vast_formatter, "get_currency_settings", return_value=currency):
            vast_formatter.print_instance_table([inst], show_index=True, title="Instances")
            vast_formatter.print_instance_detail(inst)
            vast_formatter.print_instance_table([])
        text = out.getvalue()
        self.assertIn("Instances", text)
        self.assertIn("No instances found.", text)


class VastConnectionTests(unittest.TestCase):
    def test_target_order_prefers_official_port_map_then_fallbacks(self):
        inst = VastInstance(
            id=1,
            public_ipaddr="1.2.3.4",
            ports={"22/tcp": [{"HostPort": "2201"}]},
            direct_port_start=2200,
            ssh_host="proxy",
            ssh_port=2222,
            image_runtype="jupyter",
        )

        targets = vast_ssh_targets(inst)
        self.assertEqual(
            [(target["hostname"], target["port"]) for target in targets],
            [("1.2.3.4", 2201), ("1.2.3.4", 2200), ("proxy", 2223), ("proxy", 2222)],
        )
        self.assertEqual(preferred_vast_ssh_target(inst)["port"], 2201)


class VastCommandTests(unittest.TestCase):
    def make_instance(self, **overrides):
        data = dict(id=1, actual_status="running", ssh_host="proxy", ssh_port=2222, public_ipaddr="1.2.3.4", direct_port_start=2200)
        data.update(overrides)
        return VastInstance(**data)

    def test_command_paths(self):
        client = SimpleNamespace(
            list_instances=lambda: [self.make_instance()],
            get_instance=lambda instance_id: self.make_instance(id=instance_id),
            start_instance=lambda instance_id: None,
            stop_instance=lambda instance_id: None,
            rm_instance=lambda instance_id: None,
            reboot_instance=lambda instance_id: None,
            search_offers=lambda: [VastOffer(id=1, gpu_name="A100", num_gpus=1, gpu_ram=81920, dph_total=1.2)],
            list_ssh_keys=lambda: [{"ssh_key": "ssh-rsa AAA BBB"}],
            add_ssh_key=lambda key: None,
        )
        currency = SimpleNamespace(display_currency="USD", rates=SimpleNamespace(convert=lambda amount, _from, _to: amount))

        out, code = capture_output(vast.main, ["--help"])
        self.assertEqual(code, 1)
        self.assertIn("Use `train help` or `train --help`.", out)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.print_instance_table"
        ) as table_mock:
            out, code = capture_output(vast.cmd_list, [])
        self.assertIsNone(code)
        table_mock.assert_called_once()
        self.assertIn("Vast.ai instances:", out)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.print_instance_detail"
        ) as detail_mock:
            out, code = capture_output(vast.cmd_show, ["1"])
        self.assertIsNone(code)
        detail_mock.assert_called_once()

        stopped_client = SimpleNamespace(get_instance=lambda instance_id: self.make_instance(id=instance_id, actual_status="stopped"))
        with patch("trainsh.services.vast_api.get_vast_client", return_value=stopped_client):
            out, code = capture_output(vast.cmd_ssh, ["1"])
        self.assertEqual(code, 1)
        self.assertIn("Instance not running", out)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch("os.system") as os_system:
            out, code = capture_output(vast.cmd_ssh, ["1"])
        self.assertIsNone(code)
        os_system.assert_called_once()
        self.assertIn("Connecting to 1.2.3.4:2200", out)

        mapped_client = SimpleNamespace(
            get_instance=lambda instance_id: self.make_instance(
                id=instance_id,
                ports={"22/tcp": [{"HostPort": "2201"}]},
                direct_port_start=2200,
                ssh_host="proxy",
                ssh_port=2222,
            )
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=mapped_client), patch("os.system") as os_system:
            out, code = capture_output(vast.cmd_ssh, ["1"])
        self.assertIsNone(code)
        self.assertIn("Connecting to 1.2.3.4:2201", out)
        self.assertIn("2201", os_system.call_args.args[0])

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            out, code = capture_output(vast.cmd_start, ["1"])
            self.assertIn("Instance started.", out)
            out, code = capture_output(vast.cmd_stop, ["1"])
            self.assertIn("Instance stopped.", out)
            out, code = capture_output(vast.cmd_reboot, ["1"])
            self.assertIn("Instance rebooting.", out)

        with patch("trainsh.commands.vast.prompt_input", return_value="y"), patch(
            "trainsh.services.vast_api.get_vast_client", return_value=client
        ):
            out, code = capture_output(vast.cmd_rm, ["1"])
        self.assertIn("Instance removed.", out)

        with patch("trainsh.utils.vast_formatter.get_currency_settings", return_value=currency), patch(
            "trainsh.services.vast_api.get_vast_client", return_value=client
        ), patch("trainsh.services.pricing.format_currency", side_effect=lambda amount, currency: f"{currency}{amount:.2f}"):
            out, code = capture_output(vast.cmd_search, [])
        self.assertIn("Searching for GPU offers", out)
        self.assertIn("A100", out)

        empty_client = SimpleNamespace(search_offers=lambda: [])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=empty_client):
            out, code = capture_output(vast.cmd_search, [])
        self.assertIn("No offers found.", out)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            out, code = capture_output(vast.cmd_keys, [])
        self.assertIn("Registered SSH keys:", out)

        no_keys_client = SimpleNamespace(list_ssh_keys=lambda: [])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=no_keys_client):
            out, code = capture_output(vast.cmd_keys, [])
        self.assertIn("No SSH keys registered.", out)

        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "id.pub"
            key_path.write_text("ssh-ed25519 AAA demo\n", encoding="utf-8")
            with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
                out, code = capture_output(vast.cmd_attach_key, [str(key_path)])
            self.assertIn("SSH key attached successfully.", out)

        out, code = capture_output(vast.cmd_attach_key, ["/missing/key.pub"])
        self.assertEqual(code, 1)
        self.assertIn("Key file not found", out)

        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("VAST_API_KEY missing")):
            out, code = capture_output(vast.main, ["list"])
        self.assertIsNone(code)
        self.assertIn("VAST_API_KEY", out)


class VastControlHelperTests(unittest.TestCase):
    def make_executor(self):
        logger = SimpleNamespace(
            log_detail=lambda *args, **kwargs: None,
            log_vast=lambda *args, **kwargs: None,
            log_variable=lambda *args, **kwargs: None,
            log_wait=lambda *args, **kwargs: None,
            log_ssh=lambda *args, **kwargs: None,
        )
        executor = SimpleNamespace(
            _interpolate=lambda value: value,
            _parse_duration=lambda value: 600 if value == "10m" else 10,
            ctx=SimpleNamespace(variables={}),
            recipe=SimpleNamespace(hosts={"gpu": "vast:1"}),
            logger=logger,
            log=lambda message: None,
        )
        return executor

    def helper(self):
        return VastControlHelper(
            self.make_executor(),
            build_ssh_args=lambda spec, command=None, tty=False: ["ssh", spec, command or "echo ok"],
            format_duration=lambda seconds: f"{int(seconds)}s",
        )

    def test_start_stop_pick_wait_verify_key_and_cost_paths(self):
        helper = self.helper()
        client = SimpleNamespace(
            get_instance=lambda instance_id: VastInstance(id=instance_id, actual_status="running", ssh_host="proxy", ssh_port=2222, dph_total=1.2),
            start_instance=lambda instance_id: None,
            search_offers=lambda limit=1: [VastOffer(id=5, gpu_name="A100")],
            create_instance=lambda offer_id, image, disk: 77,
            stop_instance=lambda instance_id: None,
            list_instances=lambda: [VastInstance(id=1, actual_status="running", gpu_name="A100", num_gpus=1, dph_total=1.0)],
            list_ssh_keys=lambda: [],
            add_ssh_key=lambda content, label="tmux-trainsh": None,
        )

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_start(["1"])
        self.assertTrue(ok)
        self.assertIn("already running", msg)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_stop(["1"])
        self.assertTrue(ok)
        self.assertIn("Stopped instance", msg)

        helper.executor.ctx.variables["_vast_instance_id"] = "1"
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_pick(["host=gpu"])
        self.assertTrue(ok)
        self.assertIn("Using existing instance", msg)

        picker_client = SimpleNamespace(
            list_instances=lambda: [VastInstance(id=8, actual_status="running", gpu_name="A100", num_gpus=1, dph_total=0.5)],
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=picker_client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings",
            return_value=SimpleNamespace(display_currency="USD", rates=SimpleNamespace(convert=lambda amount, _from, _to: amount)),
        ), patch("builtins.input", return_value="1"):
            helper.executor.ctx.variables.clear()
            ok, msg = helper.cmd_vast_pick(["host=gpu", "skip_if_set=false"])
        self.assertTrue(ok)
        self.assertIn("Selected instance 8", msg)
        self.assertEqual(helper.executor.ctx.variables["VAST_ID"], "8")

        waiter_client = SimpleNamespace(
            get_instance=lambda instance_id: VastInstance(
                id=instance_id,
                actual_status="running",
                ssh_host="proxy",
                ssh_port=2222,
                public_ipaddr="1.2.3.4",
                direct_port_start=2200,
                dph_total=1.5,
                gpu_name="A100",
            ),
            stop_instance=lambda instance_id: None,
            list_ssh_keys=lambda: [],
            add_ssh_key=lambda content, label="tmux-trainsh": None,
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=waiter_client), patch(
            "trainsh.config.load_config",
            return_value={"vast": {"auto_attach_ssh_key": False}, "defaults": {"ssh_key_path": "~/.ssh/id_rsa"}},
        ), patch.object(helper, "verify_ssh_connection", return_value=True), patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
            ok, msg = helper.cmd_vast_wait(["1", "timeout=10m", "poll=10"])
        self.assertTrue(ok)
        self.assertIn("ready", msg)

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")):
            self.assertTrue(helper.verify_ssh_connection("root@example.com"))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)):
            self.assertFalse(helper.verify_ssh_connection("root@example.com"))

        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "id_rsa.pub"
            key_path.write_text("ssh-ed25519 AAA demo\n", encoding="utf-8")
            helper.ensure_ssh_key_attached(client, str(key_path))

        helper.executor.ctx.variables.update({"_vast_start_time": (datetime.now() - timedelta(hours=1)).isoformat()})
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.services.pricing.load_pricing_settings",
            return_value=SimpleNamespace(exchange_rates=SimpleNamespace(convert=lambda amount, _from, _to: amount)),
        ), patch(
            "trainsh.utils.vast_formatter.get_currency_settings",
            return_value=SimpleNamespace(display_currency="USD", rates=SimpleNamespace(convert=lambda amount, _from, _to: amount)),
        ), patch("trainsh.services.pricing.format_currency", side_effect=lambda amount, currency: f"{currency}{amount:.2f}"):
            ok, msg = helper.cmd_vast_cost(["1"])
        self.assertTrue(ok)
        self.assertIn("total cost", msg)

        helper.executor.ctx.variables.clear()
        ok, msg = helper.cmd_vast_cost([])
        self.assertFalse(ok)
        self.assertIn("No instance ID provided for vast.cost", msg)


if __name__ == "__main__":
    unittest.main()
