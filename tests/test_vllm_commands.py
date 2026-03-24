import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.commands import vllm
from trainsh.core.models import AuthMethod, Host, HostType
from trainsh.services import vllm_service


def capture(fn, *args, **kwargs):
    stream = StringIO()
    code = None
    with redirect_stdout(stream):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return stream.getvalue(), code


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class VllmCommandTests(unittest.TestCase):
    def _host(self, name="gpu-box"):
        return Host(
            name=name,
            type=HostType.SSH,
            hostname="gpu.example.com",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
        )

    def test_cmd_serve_starts_tmux_and_persists_service(self):
        host = self._host()
        fake_tmux = MagicMock()
        fake_tmux.has_session.return_value = False
        fake_tmux.new_session.return_value = _Result()
        fake_tmux.send_keys.return_value = _Result()

        with tempfile.TemporaryDirectory() as tmpdir, patch("trainsh.services.vllm_service.STATE_DIR", Path(tmpdir)), patch(
            "trainsh.commands.vllm._resolve_host", return_value=host
        ), patch(
            "trainsh.commands.vllm.resolve_service_host", return_value=host
        ), patch(
            "trainsh.commands.vllm.tmux_client_for_host", return_value=fake_tmux
        ), patch(
            "trainsh.commands.vllm.service_is_running", return_value=True
        ), patch(
            "trainsh.commands.vllm.service_is_ready", return_value=True
        ):
            out, code = capture(
                vllm.cmd_serve,
                ["gpu-box", "Qwen/Test", "--gpus", "0,1"],
            )

            saved = vllm_service.load_service("test")

        self.assertIsNone(code)
        self.assertIn("Started vLLM service: test", out)
        self.assertIn("Service is ready.", out)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.model, "Qwen/Test")
        self.assertEqual(saved.host_name, "gpu-box")
        self.assertIn("CUDA_VISIBLE_DEVICES=0,1", saved.command)
        self.assertIn("--tensor-parallel-size=2", saved.command)
        self.assertIn("--gpu-memory-utilization=0.95", saved.command)
        self.assertIn("--max-num-batched-tokens=16384", saved.command)
        self.assertIn("--max-num-seqs=64", saved.command)
        fake_tmux.new_session.assert_called_once()
        fake_tmux.send_keys.assert_called_once()

    def test_cmd_serve_preserves_explicit_tuning_args(self):
        host = self._host()
        fake_tmux = MagicMock()
        fake_tmux.has_session.return_value = False
        fake_tmux.new_session.return_value = _Result()
        fake_tmux.send_keys.return_value = _Result()

        with tempfile.TemporaryDirectory() as tmpdir, patch("trainsh.services.vllm_service.STATE_DIR", Path(tmpdir)), patch(
            "trainsh.commands.vllm._resolve_host", return_value=host
        ), patch(
            "trainsh.commands.vllm.resolve_service_host", return_value=host
        ), patch(
            "trainsh.commands.vllm.tmux_client_for_host", return_value=fake_tmux
        ), patch(
            "trainsh.commands.vllm.service_is_running", return_value=True
        ), patch(
            "trainsh.commands.vllm.service_is_ready", return_value=True
        ):
            out, code = capture(
                vllm.cmd_serve,
                [
                    "gpu-box",
                    "Qwen/Test",
                    "--arg=--gpu-memory-utilization=0.90",
                    "--arg=--max-num-batched-tokens=8192",
                    "--arg=--max-num-seqs=8",
                ],
            )

            saved = vllm_service.load_service("test")

        self.assertIsNone(code)
        self.assertIn("Started vLLM service: test", out)
        self.assertIsNotNone(saved)
        self.assertIn("--gpu-memory-utilization=0.90", saved.command)
        self.assertIn("--max-num-batched-tokens=8192", saved.command)
        self.assertIn("--max-num-seqs=8", saved.command)
        self.assertEqual(saved.command.count("--gpu-memory-utilization="), 1)
        self.assertEqual(saved.command.count("--max-num-batched-tokens="), 1)
        self.assertEqual(saved.command.count("--max-num-seqs="), 1)

    def test_cmd_batch_uses_service_tunnel_and_resume(self):
        host = self._host()
        service = vllm_service.VllmServiceRecord(
            name="demo",
            host_name="gpu-box",
            host=host.to_dict(),
            model="Qwen/Test",
            port=8000,
            session_name="trainsh-vllm-demo",
            status="ready",
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch("trainsh.services.vllm_service.STATE_DIR", Path(tmpdir)):
            vllm_service.save_service(service)
            root = Path(tmpdir)
            input_path = root / "requests.jsonl"
            output_path = root / "results.jsonl"
            input_path.write_text(
                "\n".join(
                    [
                        '{"custom_id":"a","body":{"model":"Qwen/Test","messages":[]}}',
                        '{"custom_id":"b","body":{"model":"Qwen/Test","messages":[]}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            output_path.write_text(
                '{"request_id":"a","custom_id":"a","ok":true,"status_code":200,"response":{"done":true}}\n',
                encoding="utf-8",
            )

            fake_proc = SimpleNamespace(pid=4321)
            with patch("trainsh.commands.vllm.resolve_service_host", return_value=host), patch(
                "trainsh.commands.vllm.start_local_tunnel",
                return_value=fake_proc,
            ) as mocked_tunnel, patch(
                "trainsh.commands.vllm.stop_process"
            ) as mocked_stop, patch(
                "trainsh.commands.vllm.run_batch_request",
                return_value={
                    "request_id": "b",
                    "custom_id": "b",
                    "ok": True,
                    "status_code": 200,
                    "url": "/chat/completions",
                    "response": {"done": True},
                },
            ) as mocked_request:
                out, code = capture(
                    vllm.cmd_batch,
                    ["demo", "--input", str(input_path), "--output", str(output_path), "--resume"],
                )
                written = output_path.read_text(encoding="utf-8").splitlines()

        self.assertIsNone(code)
        self.assertIn("Tunnel ready", out)
        self.assertIn("Batch complete: 1 succeeded, 0 failed.", out)
        self.assertEqual(mocked_request.call_count, 1)
        mocked_tunnel.assert_called_once()
        mocked_stop.assert_called_once_with(fake_proc)
        self.assertEqual(len(written), 2)
        self.assertIn('"request_id": "b"', written[-1])

    def test_cmd_batch_distributes_across_multiple_services(self):
        host = self._host()
        service0 = vllm_service.VllmServiceRecord(
            name="q0",
            host_name="gpu-box",
            host=host.to_dict(),
            model="Qwen/Test",
            port=8000,
            session_name="trainsh-vllm-q0",
            status="ready",
        )
        service1 = vllm_service.VllmServiceRecord(
            name="q1",
            host_name="gpu-box",
            host=host.to_dict(),
            model="Qwen/Test",
            port=8001,
            session_name="trainsh-vllm-q1",
            status="ready",
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch("trainsh.services.vllm_service.STATE_DIR", Path(tmpdir)):
            vllm_service.save_service(service0)
            vllm_service.save_service(service1)
            root = Path(tmpdir)
            input_path = root / "requests.jsonl"
            output_path = root / "results.jsonl"
            input_path.write_text(
                "\n".join(
                    [
                        '{"custom_id":"a","body":{"model":"Qwen/Test","messages":[]}}',
                        '{"custom_id":"b","body":{"model":"Qwen/Test","messages":[]}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            seen_urls = []

            def _fake_run(request, *, base_url, timeout, retries, api_key):
                seen_urls.append(base_url)
                return {
                    "request_id": request.request_id,
                    "custom_id": request.custom_id,
                    "ok": True,
                    "status_code": 200,
                    "url": request.url,
                    "response": {"done": True},
                }

            with patch("trainsh.commands.vllm.resolve_service_host", return_value=host), patch(
                "trainsh.commands.vllm.start_local_tunnel",
                side_effect=[SimpleNamespace(pid=1), SimpleNamespace(pid=2)],
            ) as mocked_tunnel, patch(
                "trainsh.commands.vllm.stop_process"
            ) as mocked_stop, patch(
                "trainsh.commands.vllm.is_local_port_open",
                return_value=False,
            ), patch(
                "trainsh.commands.vllm.run_batch_request",
                side_effect=_fake_run,
            ):
                out, code = capture(
                    vllm.cmd_batch,
                    ["q0", "q1", "--input", str(input_path), "--output", str(output_path)],
                )

        self.assertIsNone(code)
        self.assertIn("Tunnel ready for q0", out)
        self.assertIn("Tunnel ready for q1", out)
        self.assertEqual(mocked_tunnel.call_count, 2)
        self.assertEqual(mocked_stop.call_count, 2)
        self.assertEqual(sorted(seen_urls), ["http://127.0.0.1:8000/v1", "http://127.0.0.1:8001/v1"])

    def test_cmd_status_falls_back_to_list_without_name(self):
        with patch("trainsh.commands.vllm.cmd_list") as mocked_list:
            out, code = capture(vllm.cmd_status, [])
        self.assertIsNone(code)
        self.assertEqual(out, "")
        mocked_list.assert_called_once_with([])
