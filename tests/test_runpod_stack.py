import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from trainsh.commands import runpod
from trainsh.core.executor_runpod import RunpodControlHelper
from trainsh.core.models import RunpodGPUType, RunpodPod
from trainsh.services.runpod_api import RunpodAPIClient, RunpodAPIError, get_runpod_client
from trainsh.services.runpod_connection import preferred_runpod_ssh_target, runpod_ssh_targets


def capture_output(fn, *args, **kwargs):
    stream = io.StringIO()
    with redirect_stdout(stream):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            return stream.getvalue(), exc.code
    return stream.getvalue(), None


class RunpodApiClientTests(unittest.TestCase):
    def test_rest_and_graphql_helpers(self):
        client = RunpodAPIClient("token")

        response = MagicMock()
        response.read.return_value = b'{"items": [{"id": "pod-1", "desiredStatus": "RUNNING"}]}'
        response.__enter__.return_value = response
        with patch("trainsh.services.runpod_api.urlopen", return_value=response):
            data = client._rest_request("pods")
        self.assertEqual(data["items"][0]["id"], "pod-1")

        http_error = HTTPError("u", 500, "err", None, None)
        self.addCleanup(http_error.close)
        with patch("trainsh.services.runpod_api.urlopen", side_effect=http_error):
            with self.assertRaises(RunpodAPIError):
                client._rest_request("pods")

        with patch("trainsh.services.runpod_api.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(RunpodAPIError):
                client._rest_request("pods")

        with patch.object(client, "_rest_request", return_value={"items": [{"id": "pod-1", "desiredStatus": "RUNNING", "gpu": {"displayName": "A100", "count": 1}, "portMappings": {"22": 2201}, "publicIp": "1.2.3.4"}]}):
            pods = client.list_pods()
        self.assertEqual(pods[0].id, "pod-1")
        self.assertTrue(pods[0].is_running)

        with patch.object(client, "_rest_request", return_value={"id": "pod-2", "desiredStatus": "RUNNING", "gpu": {"id": "NVIDIA A100", "displayName": "A100", "count": 1}, "portMappings": {"22": 2202}, "publicIp": "1.2.3.4"}):
            pod = client.get_pod("pod-2")
        self.assertEqual(pod.gpu_display_name, "A100")

        with patch.object(client, "_rest_request", return_value={"id": "pod-3", "desiredStatus": "EXITED"}):
            created = client.create_pod(name="demo", gpu_type_id="NVIDIA A100")
        self.assertEqual(created.id, "pod-3")

        gql = {
            "gpuTypes": [
                {
                    "id": "NVIDIA A100 80GB PCIe",
                    "displayName": "A100",
                    "memoryInGb": 80,
                    "securePrice": 2.5,
                    "communityPrice": 1.8,
                    "secureSpotPrice": 1.2,
                    "lowestPrice": {
                        "minimumBidPrice": 1.2,
                        "uninterruptablePrice": 2.5,
                        "minVcpu": 8,
                        "minMemory": 64,
                        "stockStatus": "High",
                        "availableGpuCounts": [1, 2, 4],
                    },
                }
            ]
        }
        with patch.object(client, "_graphql_request", return_value=gql):
            gpu_types = client.list_gpu_types(gpu_name="A100", max_dph=3.0, min_gpu_ram=40, gpu_count=1)
        self.assertEqual(gpu_types[0].display_name, "A100")
        self.assertEqual(gpu_types[0].stock_status, "High")

    def test_get_runpod_client_uses_secrets_manager(self):
        secrets = SimpleNamespace(get_runpod_api_key=lambda: "token")
        with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets):
            client = get_runpod_client()
        self.assertIsInstance(client, RunpodAPIClient)

        secrets = SimpleNamespace(get_runpod_api_key=lambda: "")
        with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets):
            with self.assertRaises(RuntimeError):
                get_runpod_client()


class RunpodConnectionTests(unittest.TestCase):
    def test_target_order_prefers_public_ip_mapping(self):
        pod = RunpodPod(
            id="pod-1",
            desired_status="RUNNING",
            public_ip="1.2.3.4",
            port_mappings={"22": 2201},
        )
        targets = runpod_ssh_targets(pod)
        self.assertEqual(
            [(target["hostname"], target["port"]) for target in targets],
            [("1.2.3.4", 2201)],
        )
        self.assertEqual(preferred_runpod_ssh_target(pod)["port"], 2201)


class RunpodCommandTests(unittest.TestCase):
    def make_pod(self, **overrides):
        data = dict(
            id="pod-1",
            desired_status="RUNNING",
            name="demo",
            gpu_display_name="A100",
            gpu_count=1,
            cost_per_hr=1.2,
            public_ip="1.2.3.4",
            port_mappings={"22": 2201},
            ports=["22/tcp"],
        )
        data.update(overrides)
        return RunpodPod(**data)

    def test_command_paths(self):
        client = SimpleNamespace(
            list_pods=lambda: [self.make_pod()],
            get_pod=lambda pod_id: self.make_pod(id=pod_id),
            start_pod=lambda pod_id: None,
            stop_pod=lambda pod_id: None,
            restart_pod=lambda pod_id: None,
            delete_pod=lambda pod_id: None,
            list_gpu_types=lambda **kwargs: [
                RunpodGPUType(id="NVIDIA A100 80GB PCIe", display_name="A100", memory_gb=80, secure_price=2.5, community_price=1.8, uninterruptable_price=2.5, stock_status="High")
            ],
        )

        out, code = capture_output(runpod.main, ["--help"])
        self.assertEqual(code, 1)
        self.assertIn("Use `train help` or `train --help`.", out)

        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=client):
            out, code = capture_output(runpod.cmd_list, [])
        self.assertIsNone(code)
        self.assertIn("RunPod Pods:", out)
        self.assertIn("pod-1", out)

        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=client):
            out, code = capture_output(runpod.cmd_show, ["pod-1"])
        self.assertIsNone(code)
        self.assertIn("RunPod Pod: pod-1", out)

        stopped_client = SimpleNamespace(get_pod=lambda pod_id: self.make_pod(id=pod_id, desired_status="EXITED"))
        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=stopped_client):
            out, code = capture_output(runpod.cmd_ssh, ["pod-1"])
        self.assertEqual(code, 1)
        self.assertIn("Pod not running", out)

        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=client), patch("os.system") as os_system:
            out, code = capture_output(runpod.cmd_ssh, ["pod-1"])
        self.assertIsNone(code)
        os_system.assert_called_once()
        self.assertIn("Connecting to 1.2.3.4:2201", out)

        with patch("trainsh.commands.runpod.run_remote_command") as run_remote:
            out, code = capture_output(runpod.cmd_run, ["pod-2", "--", "nvidia-smi"])
        self.assertIsNone(code)
        self.assertEqual(run_remote.call_args.args[0].runpod_pod_id, "pod-2")

        with patch("trainsh.commands.runpod.run_remote_git_clone") as run_clone:
            out, code = capture_output(runpod.cmd_clone, ["pod-2", "https://github.com/org/repo.git"])
        self.assertIsNone(code)
        self.assertEqual(run_clone.call_args.args[0].runpod_pod_id, "pod-2")

        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=client):
            out, code = capture_output(runpod.cmd_start, ["pod-1"])
            self.assertIsNone(code)
            self.assertIn("Pod started", out)
            out, code = capture_output(runpod.cmd_stop, ["pod-1"])
            self.assertIsNone(code)
            self.assertIn("Pod stopped", out)
            out, code = capture_output(runpod.cmd_reboot, ["pod-1"])
            self.assertIsNone(code)
            self.assertIn("Pod restarting", out)

        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=client), patch("trainsh.commands.runpod.prompt_input", return_value="y"):
            out, code = capture_output(runpod.cmd_rm, ["pod-1"])
        self.assertIsNone(code)
        self.assertIn("Pod removed", out)

        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=client):
            out, code = capture_output(runpod.cmd_search, ["gpu_name=A100"])
        self.assertIsNone(code)
        self.assertIn("A100", out)


class RunpodControlHelperTests(unittest.TestCase):
    def _helper(self):
        executor = SimpleNamespace(
            ctx=SimpleNamespace(variables={}),
            recipe=SimpleNamespace(hosts={"gpu": "runpod:pod-1"}),
            logger=None,
            _interpolate=lambda text: text,
            _parse_duration=lambda text: 10 if text == "10s" else 600,
            log=lambda *args, **kwargs: None,
            _verify_ssh_connection=lambda spec, timeout=10: True,
        )
        return executor, RunpodControlHelper(executor, lambda *args, **kwargs: ["ssh"], lambda seconds: f"{int(seconds)}s")

    def test_helper_paths(self):
        executor, helper = self._helper()
        ready_pod = RunpodPod(
            id="pod-1",
            desired_status="RUNNING",
            name="demo",
            gpu_display_name="A100",
            gpu_count=1,
            cost_per_hr=1.5,
            public_ip="1.2.3.4",
            port_mappings={"22": 2201},
            ports=["22/tcp"],
        )
        client = SimpleNamespace(
            get_pod=lambda pod_id: ready_pod,
            start_pod=lambda pod_id: None,
            stop_pod=lambda pod_id: None,
            list_pods=lambda: [ready_pod],
            list_gpu_types=lambda **kwargs: [RunpodGPUType(id="NVIDIA A100 80GB PCIe", display_name="A100", memory_gb=80, secure_price=2.5, community_price=1.8, uninterruptable_price=2.5, stock_status="High")],
            create_pod=lambda **kwargs: ready_pod,
        )

        with patch("trainsh.services.runpod_api.get_runpod_client", return_value=client):
            ok, msg = helper.cmd_runpod_start(["pod-1"])
            self.assertTrue(ok)
            self.assertIn("Pod already running", msg)
            self.assertEqual(executor.ctx.variables["RUNPOD_ID"], "pod-1")

            ok, msg = helper.cmd_runpod_pick(["host=gpu", "auto_select=true"])
            self.assertTrue(ok)
            self.assertEqual(executor.recipe.hosts["gpu"], "runpod:pod-1")

            ok, msg = helper.cmd_runpod_wait(["pod-1", "timeout=10m", "poll=10s"])
            self.assertTrue(ok)
            self.assertIn("SSH-ready", msg)

            ok, msg = helper.cmd_runpod_cost(["pod-1"])
            self.assertTrue(ok)
            self.assertIn("/hr", msg)
