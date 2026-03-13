import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.executor_vast import VastControlHelper


def make_executor():
    logger = SimpleNamespace(
        log_detail=lambda *a, **k: None,
        log_vast=lambda *a, **k: None,
        log_variable=lambda *a, **k: None,
        log_wait=lambda *a, **k: None,
        log_ssh=lambda *a, **k: None,
    )
    return SimpleNamespace(
        _interpolate=lambda value: value,
        _parse_duration=lambda value: 600 if value == "10m" else 10,
        ctx=SimpleNamespace(variables={}),
        recipe=SimpleNamespace(hosts={}),
        logger=logger,
        log=lambda message: None,
    )


def make_helper(executor=None):
    executor = executor or make_executor()
    return VastControlHelper(
        executor,
        build_ssh_args=lambda spec, command=None, tty=False: ["ssh", spec, command or "echo ok"],
        format_duration=lambda seconds: f"{int(seconds)}s",
    )


class ExecutorVastMoreTests(unittest.TestCase):
    def test_logger_and_additional_vast_branches(self):
        logger = SimpleNamespace(
            log_detail=MagicMock(),
            log_vast=MagicMock(),
            log_variable=MagicMock(),
            log_wait=MagicMock(),
            log_ssh=MagicMock(),
        )
        executor = make_executor()
        executor.logger = logger
        helper = make_helper(executor)

        class VastAPIError(RuntimeError):
            pass

        stopped = SimpleNamespace(
            id=7,
            actual_status="stopped",
            is_running=False,
            gpu_name="A100",
            num_gpus=1,
            ssh_host="proxy",
            ssh_port=22,
            dph_total=1.0,
            start_date=None,
        )
        client = SimpleNamespace(
            get_instance=lambda inst_id: stopped,
            start_instance=lambda inst_id: (_ for _ in ()).throw(VastAPIError("no quota")),
            stop_instance=lambda inst_id: None,
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.services.vast_api.VastAPIError", VastAPIError
        ):
            ok, msg = helper.cmd_vast_start(["7"])
        self.assertFalse(ok)
        logger.log_vast.assert_called()
        self.assertIn("instance stopped", msg)

        helper.executor.ctx.variables.clear()
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(stop_instance=lambda inst_id: None)):
            ok, msg = helper.cmd_vast_stop([])
        self.assertFalse(ok)
        self.assertIn("No instance to stop", msg)

        helper.executor.recipe.hosts = {"gpu": "vast:1"}
        instance_bad = SimpleNamespace(id=4, actual_status="stopped", gpu_name="T4", num_gpus=1, gpu_memory_gb=8, dph_total=2.0)
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(list_instances=lambda: [instance_bad])):
            ok, msg = helper.cmd_vast_pick(["gpu_name=A100"])
        self.assertFalse(ok)
        self.assertIn("No Vast.ai instances match filters", msg)

        inst1 = SimpleNamespace(id=9, actual_status="starting", gpu_name="A100", num_gpus=1, gpu_memory_gb=80, dph_total=0.8)
        inst2 = SimpleNamespace(id=11, actual_status="stopped", gpu_name="A100", num_gpus=2, gpu_memory_gb=80, dph_total=0.7)
        client = SimpleNamespace(list_instances=lambda: [inst1, inst2])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD", rates=SimpleNamespace(convert=lambda amount, _from, _to: amount))
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", return_value="11"):
            ok, msg = helper.cmd_vast_pick(["@gpu", "num_gpus=1", "min_gpu_ram=16", "max_dph=1.0", "limit=5"])
        self.assertTrue(ok)
        self.assertIn("Selected instance 11", msg)
        logger.log_detail.assert_called()

        helper.executor.ctx.variables.clear()
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_pick(["host=gpu", "auto_select=true"])
        self.assertTrue(ok)
        self.assertIn("Selected instance 11", msg)
        self.assertEqual(helper.executor.ctx.variables["VAST_ID"], "11")

        helper.executor.ctx.variables.clear()
        created = {}
        offer = SimpleNamespace(id=77, gpu_name="H200", num_gpus=8, dph_total=19.5, reliability2=0.99)

        def create_instance(**kwargs):
            created["kwargs"] = kwargs
            return 901

        client = SimpleNamespace(
            list_instances=lambda: [],
            search_offers=lambda **kwargs: [offer],
            create_instance=create_instance,
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_pick(
                [
                    "host=gpu",
                    "gpu_name=H200",
                    "num_gpus=8",
                    "min_gpu_ram=80",
                    "create_if_missing=true",
                    "auto_select=true",
                    "disk_gb=200",
                    "direct=true",
                ]
            )
        self.assertTrue(ok)
        self.assertIn("Created instance 901", msg)
        self.assertEqual(helper.executor.ctx.variables["VAST_ID"], "901")
        self.assertEqual(helper.executor.recipe.hosts["gpu"], "vast:901")
        self.assertEqual(created["kwargs"]["offer_id"], 77)
        self.assertEqual(created["kwargs"]["disk"], 200.0)
        self.assertTrue(created["kwargs"]["direct"])

        helper.executor.ctx.variables.clear()
        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("pick boom")):
            ok, msg = helper.cmd_vast_pick(["host=gpu"])
        self.assertFalse(ok)
        self.assertIn("pick boom", msg)

    def test_start_stop_and_pick_success_paths(self):
        helper = make_helper()
        running = SimpleNamespace(
            id=7,
            actual_status="running",
            is_running=True,
            gpu_name="A100",
            num_gpus=1,
            ssh_host="proxy",
            ssh_port=22,
            dph_total=1.0,
            start_date=1710200000,
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda inst_id: running)):
            ok, msg = helper.cmd_vast_start(["7"])
        self.assertTrue(ok)
        self.assertIn("already running", msg)
        self.assertEqual(helper.executor.ctx.variables["_vast_instance_id"], "7")

        stopped = SimpleNamespace(
            id=8,
            actual_status="stopped",
            is_running=False,
            gpu_name="A100",
            num_gpus=1,
            ssh_host="proxy",
            ssh_port=22,
            dph_total=1.0,
            start_date=None,
        )
        client = SimpleNamespace(get_instance=lambda inst_id: stopped, start_instance=lambda inst_id: None)
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_start(["8"])
        self.assertTrue(ok)
        self.assertIn("Started instance: 8", msg)

        helper.executor.ctx.variables.clear()
        offers = [SimpleNamespace(id=11)]
        client = SimpleNamespace(search_offers=lambda limit=1: offers, create_instance=lambda **kwargs: 99)
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_start([])
        self.assertTrue(ok)
        self.assertIn("Created instance: 99", msg)

        helper.executor.ctx.variables["_vast_instance_id"] = "9"
        client = SimpleNamespace(stop_instance=lambda inst_id: None)
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            ok, msg = helper.cmd_vast_stop([])
        self.assertTrue(ok)
        self.assertIn("Stopped instance: 9", msg)

        helper.executor.recipe.hosts = {"gpu": "vast:1"}
        helper.executor.ctx.variables.clear()
        helper.executor.ctx.variables["VAST_ID"] = "5"
        ok, msg = helper.cmd_vast_pick(["host=gpu"])
        self.assertTrue(ok)
        self.assertIn("Using existing instance: 5", msg)

        helper.executor.ctx.variables.clear()
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(list_instances=lambda: [])):
            ok, msg = helper.cmd_vast_pick(["host=gpu"])
        self.assertFalse(ok)
        self.assertIn("No Vast.ai instances found", msg)

    def test_start_failure_wait_ready_and_pick_selection_success(self):
        helper = make_helper()
        stopped = SimpleNamespace(
            id=7,
            actual_status="stopped",
            is_running=False,
            gpu_name="A100",
            num_gpus=1,
            ssh_host="proxy",
            ssh_port=22,
            dph_total=1.0,
            start_date=None,
        )

        class VastAPIError(RuntimeError):
            pass

        client = SimpleNamespace(
            get_instance=lambda inst_id: stopped,
            start_instance=lambda inst_id: (_ for _ in ()).throw(VastAPIError("no quota")),
            stop_instance=lambda inst_id: (_ for _ in ()).throw(VastAPIError("stop failed")),
        )
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.services.vast_api.VastAPIError", VastAPIError
        ):
            ok, msg = helper.cmd_vast_start(["7"])
        self.assertFalse(ok)
        self.assertIn("no quota", msg)
        self.assertIn("stop failed", msg)

        ready = SimpleNamespace(
            id=7,
            actual_status="running",
            is_running=True,
            ssh_host="proxy",
            ssh_port=22,
            ssh_proxy_command="ssh proxy",
            ssh_direct_command=None,
            public_ipaddr=None,
            direct_port_start=None,
            direct_port_end=None,
            gpu_name="A100",
            num_gpus=1,
        )
        helper.executor.recipe.hosts = {"gpu": "vast:7"}
        helper.executor.ctx.variables["VAST_ID"] = "7"
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda instance_id: ready)), patch(
            "trainsh.config.load_config", return_value={"vast": {"auto_attach_ssh_key": False}, "defaults": {"ssh_key_path": "~/.ssh/id_rsa"}}
        ), patch.object(helper, "verify_ssh_connection", return_value=True), patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")), patch(
            "time.time", side_effect=[0, 0, 1, 1]
        ):
            ok, msg = helper.cmd_vast_wait(["7", "timeout=10m", "poll=10s"])
        self.assertTrue(ok)
        self.assertIn("ready", msg)
        self.assertEqual(helper.executor.recipe.hosts["gpu"], "root@proxy -p 22")

        helper = make_helper()
        helper.executor.recipe.hosts = {"gpu": "vast:1"}
        instance = SimpleNamespace(id=3, actual_status="running", gpu_name="A100", num_gpus=1, gpu_memory_gb=80, dph_total=1.2)
        client = SimpleNamespace(list_instances=lambda: [instance])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD", rates=SimpleNamespace(convert=lambda amount, _from, _to: amount))
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", return_value="1"):
            ok, msg = helper.cmd_vast_pick(["host=gpu"])
        self.assertTrue(ok)
        self.assertIn("Selected instance 3", msg)
        self.assertEqual(helper.executor.recipe.hosts["gpu"], "vast:3")

    def test_start_stop_pick_simple_error_branches(self):
        helper = make_helper()
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace()):
            ok, msg = helper.cmd_vast_start(["bad"])
        self.assertFalse(ok)
        self.assertIn("Invalid instance ID", msg)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(search_offers=lambda limit=1: [])):
            ok, msg = helper.cmd_vast_start([])
        self.assertFalse(ok)
        self.assertIn("No GPU offers available", msg)

        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom")):
            ok, msg = helper.cmd_vast_start([])
        self.assertFalse(ok)
        self.assertIn("boom", msg)

        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom")):
            ok, msg = helper.cmd_vast_stop(["1"])
        self.assertFalse(ok)
        self.assertIn("boom", msg)

        helper = make_helper()
        ok, msg = helper.cmd_vast_pick([])
        self.assertFalse(ok)
        self.assertIn("No host alias provided", msg)

        helper.executor.recipe.hosts = {"gpu": "vast:1"}
        ok, msg = helper.cmd_vast_pick(["num_gpus=bad"])
        self.assertFalse(ok)
        ok, msg = helper.cmd_vast_pick(["min_gpu_ram=bad"])
        self.assertFalse(ok)
        ok, msg = helper.cmd_vast_pick(["max_dph=bad"])
        self.assertFalse(ok)
        ok, msg = helper.cmd_vast_pick(["limit=bad"])
        self.assertFalse(ok)

    def test_pick_selection_and_wait_branches(self):
        helper = make_helper()
        helper.executor.recipe.hosts = {"gpu": "vast:1"}
        instance = SimpleNamespace(id=3, actual_status="running", gpu_name="A100", num_gpus=1, gpu_memory_gb=80, dph_total=1.2)
        client = SimpleNamespace(list_instances=lambda: [instance])
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD", rates=SimpleNamespace(convert=lambda amount, _from, _to: amount))
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", side_effect=EOFError()):
            ok, msg = helper.cmd_vast_pick(["host=gpu"])
        self.assertFalse(ok)
        self.assertIn("cancelled", msg.lower())

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="USD", rates=SimpleNamespace(convert=lambda amount, _from, _to: amount))
        ), patch("trainsh.utils.vast_formatter.format_instance_header", return_value=("HEADER", "---")), patch(
            "trainsh.utils.vast_formatter.format_instance_row", return_value="ROW"
        ), patch("builtins.input", return_value="bad"):
            ok, msg = helper.cmd_vast_pick(["host=gpu"])
        self.assertFalse(ok)
        self.assertIn("Invalid selection", msg)

        helper = make_helper()
        ok, msg = helper.cmd_vast_wait([])
        self.assertFalse(ok)
        self.assertIn("No instance ID provided", msg)
        ok, msg = helper.cmd_vast_wait(["bad"])
        self.assertFalse(ok)
        self.assertIn("Invalid instance ID", msg)

        helper.executor.ctx.variables["VAST_ID"] = "7"
        stopped_instance = SimpleNamespace(
            id=7,
            actual_status="starting",
            is_running=False,
            ssh_host="proxy",
            ssh_port=2222,
            ssh_proxy_command="ssh proxy",
            ssh_direct_command=None,
            public_ipaddr=None,
            direct_port_start=None,
            direct_port_end=None,
        )
        client = SimpleNamespace(get_instance=lambda instance_id: stopped_instance, stop_instance=lambda instance_id: None)
        calls = {"n": 0}

        def fake_time():
            calls["n"] += 1
            return 0 if calls["n"] <= 3 else 1000

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.config.load_config", return_value={"vast": {"auto_attach_ssh_key": False}, "defaults": {"ssh_key_path": "~/.ssh/id_rsa"}}
        ), patch("time.time", side_effect=fake_time), patch("time.sleep"):
            ok, msg = helper.cmd_vast_wait(["timeout=10m", "poll_interval=10s", "stop_on_fail=false"])
        self.assertFalse(ok)
        self.assertNotIn("instance stopped", msg)

        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom")), patch(
            "trainsh.config.load_config", return_value={"vast": {"auto_attach_ssh_key": False}, "defaults": {"ssh_key_path": "~/.ssh/id_rsa"}}
        ):
            ok, msg = helper.cmd_vast_wait(["7"])
        self.assertFalse(ok)
        self.assertIn("Vast wait failed", msg)

    def test_wait_more_timeout_and_unreachable_paths(self):
        logger = SimpleNamespace(
            log_detail=MagicMock(),
            log_vast=MagicMock(),
            log_variable=MagicMock(),
            log_wait=MagicMock(),
            log_ssh=MagicMock(),
        )
        executor = make_executor()
        executor.logger = logger
        helper = make_helper(executor)
        helper.executor.recipe.hosts = {"gpu": "vast:7"}

        ready_direct = SimpleNamespace(
            id=7,
            actual_status="running",
            is_running=True,
            ssh_host="proxy",
            ssh_port=22,
            ssh_proxy_command="ssh proxy",
            ssh_direct_command="ssh direct",
            public_ipaddr="1.2.3.4",
            direct_port_start=2200,
            direct_port_end=2201,
            gpu_name="A100",
            num_gpus=1,
        )
        helper.executor.ctx.variables["VAST_ID"] = "7"
        calls = {"n": 0}

        def time_after_one_loop():
            calls["n"] += 1
            return 0 if calls["n"] <= 3 else 700

        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda instance_id: ready_direct, stop_instance=lambda instance_id: None)), patch(
            "trainsh.config.load_config", return_value={"vast": {"auto_attach_ssh_key": True}, "defaults": {"ssh_key_path": "~/.ssh/id_rsa"}}
        ), patch.object(helper, "ensure_ssh_key_attached") as mocked_attach, patch.object(
            helper, "verify_ssh_connection", return_value=False
        ), patch("time.time", side_effect=time_after_one_loop), patch("time.sleep"):
            ok, msg = helper.cmd_vast_wait(["7", "timeout=10m", "poll=10s"])
        self.assertFalse(ok)
        self.assertIn("not ready", msg)
        mocked_attach.assert_called_once()
        logger.log_detail.assert_called()

        timeout_inst = SimpleNamespace(
            id=7,
            actual_status="starting",
            is_running=False,
            ssh_host="proxy",
            ssh_port=22,
            ssh_proxy_command="ssh proxy",
            ssh_direct_command=None,
            public_ipaddr=None,
            direct_port_start=None,
            direct_port_end=None,
        )
        client = SimpleNamespace(get_instance=lambda instance_id: timeout_inst, stop_instance=lambda instance_id: None)
        calls = {"n": 0}

        def time_timeout():
            calls["n"] += 1
            return 0 if calls["n"] <= 3 else 1000

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.config.load_config", return_value={"vast": {"auto_attach_ssh_key": False}, "defaults": {"ssh_key_path": "~/.ssh/id_rsa"}}
        ), patch("time.time", side_effect=time_timeout), patch("time.sleep"):
            ok, msg = helper.cmd_vast_wait(["7"])
        self.assertFalse(ok)
        self.assertIn("instance stopped", msg)
        logger.log_vast.assert_called()

        class VastAPIError(RuntimeError):
            pass

        client = SimpleNamespace(get_instance=lambda instance_id: timeout_inst, stop_instance=lambda instance_id: (_ for _ in ()).throw(VastAPIError("stop boom")))
        calls = {"n": 0}
        with patch("trainsh.services.vast_api.get_vast_client", return_value=client), patch(
            "trainsh.config.load_config", return_value={"vast": {"auto_attach_ssh_key": False}, "defaults": {"ssh_key_path": "~/.ssh/id_rsa"}}
        ), patch("trainsh.services.vast_api.VastAPIError", VastAPIError), patch(
            "time.time", side_effect=lambda: 0 if (calls.__setitem__('n', calls['n'] + 1) or calls['n']) <= 3 else 1000
        ), patch("time.sleep"):
            ok, msg = helper.cmd_vast_wait(["7"])
        self.assertFalse(ok)
        self.assertIn("failed to stop instance", msg)

    def test_verify_key_attach_and_cost_branches(self):
        helper = make_helper()
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")):
            self.assertTrue(helper.verify_ssh_connection("root@example"))
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="bad")):
            self.assertFalse(helper.verify_ssh_connection("root@example"))
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            self.assertFalse(helper.verify_ssh_connection("root@example"))

        client = SimpleNamespace(list_ssh_keys=lambda: [])
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "id_rsa"
            helper.ensure_ssh_key_attached(client, str(key_path))
            key_path.with_suffix(".pub").write_text("", encoding="utf-8")
            helper.ensure_ssh_key_attached(client, str(key_path))
            key_path.with_suffix(".pub").write_text("badkey", encoding="utf-8")
            helper.ensure_ssh_key_attached(client, str(key_path))
            key_path.with_suffix(".pub").write_text("ssh-rsa AAA demo\n", encoding="utf-8")
            dup_client = SimpleNamespace(list_ssh_keys=lambda: [{"ssh_key": "ssh-rsa AAA existing"}], add_ssh_key=lambda content, label="tmux-trainsh": None)
            helper.ensure_ssh_key_attached(dup_client, str(key_path))
            err_client = SimpleNamespace(list_ssh_keys=lambda: [], add_ssh_key=lambda content, label="tmux-trainsh": (_ for _ in ()).throw(RuntimeError("duplicate key")))
            helper.ensure_ssh_key_attached(err_client, str(key_path))
            warn_client = SimpleNamespace(list_ssh_keys=lambda: [], add_ssh_key=lambda content, label="tmux-trainsh": (_ for _ in ()).throw(RuntimeError("boom")))
            helper.ensure_ssh_key_attached(warn_client, str(key_path))

        helper.executor.ctx.variables.clear()
        ok, msg = helper.cmd_vast_cost([])
        self.assertTrue(ok)
        self.assertIn("no instance ID provided", msg)
        helper.executor.ctx.variables["VAST_ID"] = "bad"
        ok, msg = helper.cmd_vast_cost([])
        self.assertTrue(ok)
        self.assertIn("invalid instance ID", msg)
        helper.executor.ctx.variables["VAST_ID"] = "7"
        ok, msg = helper.cmd_vast_cost([])
        self.assertTrue(ok)
        self.assertIn("no start time recorded", msg)

        helper.executor.ctx.variables["_vast_start_time"] = "2026-03-12T00:00:00"
        zero_instance = SimpleNamespace(dph_total=0.0, gpu_name="A100")
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda inst_id: zero_instance)):
            ok, msg = helper.cmd_vast_cost([])
        self.assertTrue(ok)
        self.assertIn("no pricing", msg)

        priced_instance = SimpleNamespace(dph_total=1.0, gpu_name="A100")
        with patch("trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(get_instance=lambda inst_id: priced_instance)), patch(
            "trainsh.services.pricing.load_pricing_settings", return_value=SimpleNamespace(exchange_rates=SimpleNamespace(convert=lambda amount, _from, _to: amount * 7))
        ), patch("trainsh.utils.vast_formatter.get_currency_settings", return_value=SimpleNamespace(display_currency="CNY")), patch(
            "trainsh.services.pricing.format_currency", side_effect=lambda amount, currency: f"{currency}{amount:.2f}"
        ), patch("trainsh.core.executor_vast.datetime") as mocked_datetime:
            mocked_datetime.fromisoformat.return_value = __import__("datetime").datetime(2026, 3, 12, 0, 0, 0)
            mocked_datetime.now.return_value = __import__("datetime").datetime(2026, 3, 12, 1, 0, 0)
            ok, msg = helper.cmd_vast_cost([])
        self.assertTrue(ok)
        self.assertIn("CNY7.00", msg)

        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom")):
            ok, msg = helper.cmd_vast_cost([])
        self.assertTrue(ok)
        self.assertIn("boom", msg)

        helper.executor.ctx.variables.clear()
        helper.executor.ctx.variables["_vast_start_time"] = "2026-03-12T00:00:00"
        with patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom arg")):
            ok, msg = helper.cmd_vast_cost(["7"])
        self.assertTrue(ok)
        self.assertIn("boom arg", msg)


if __name__ == "__main__":
    unittest.main()
