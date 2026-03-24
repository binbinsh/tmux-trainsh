import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from trainsh import flash_attn_install_script
from trainsh.commands.host_flash_attn import (
    HostFlashAttnOptions,
    parse_host_flash_attn_args,
    run_host_flash_attn,
)
from trainsh.core.models import Host
from trainsh.services.flash_attn_matrix import render_compatibility_matrix
from trainsh.services.flash_attn_support import (
    FlashAttnProbe,
    parse_flash_attn_probe_output,
    plan_flash_attn_install,
)


class FlashAttnSupportTests(unittest.TestCase):
    def test_plan_for_hopper_cuda_environment_with_explicit_v2(self):
        probe = FlashAttnProbe.from_dict(
            {
                "python_executable": "/usr/bin/python3",
                "python_version": "3.10.14",
                "platform_system": "Linux",
                "platform_machine": "x86_64",
                "torch_available": True,
                "torch_version": "2.4.1+cu121",
                "torch_cuda_version": "12.1",
                "torch_cxx11_abi": "FALSE",
                "gpu_names": ["NVIDIA H100 80GB HBM3"],
                "gpu_capabilities": ["9.0"],
                "nvcc_version": "12.1",
                "cpu_count": 64,
                "memory_gb": 80,
            }
        )

        plan = plan_flash_attn_install(probe, version="2.8.3")

        self.assertTrue(plan.ok)
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.backend, "cuda")
        self.assertEqual(plan.package_name, "flash-attn")
        self.assertEqual(plan.target, "flash-attn 2.x")
        self.assertEqual(plan.recommended_max_jobs, 10)
        self.assertIn("+cu12torch2.4cxx11abiFALSE-cp310-cp310-linux_x86_64.whl", plan.wheel_url)

    def test_plan_prefers_flash_attn_four_for_blackwell_auto(self):
        probe = FlashAttnProbe.from_dict(
            {
                "python_version": "3.12.13",
                "platform_system": "Linux",
                "platform_machine": "x86_64",
                "torch_available": True,
                "torch_version": "2.10.0+cu128",
                "torch_cuda_version": "12.8",
                "gpu_names": ["NVIDIA GeForce RTX 5090"],
                "gpu_capabilities": ["12.0"],
                "nvcc_version": "12.8",
            }
        )

        plan = plan_flash_attn_install(probe)

        self.assertTrue(plan.ok)
        self.assertEqual(plan.package_name, "flash-attn-4")
        self.assertEqual(plan.install_spec, "flash-attn-4==4.0.0b5")
        self.assertEqual(plan.target, "flash-attn-4")

    def test_plan_falls_back_to_fa2_when_vllm_still_uses_fa2_api(self):
        probe = FlashAttnProbe.from_dict(
            {
                "python_version": "3.12.3",
                "platform_system": "Linux",
                "platform_machine": "x86_64",
                "torch_available": True,
                "torch_version": "2.10.0+cu128",
                "torch_cuda_version": "12.8",
                "gpu_names": ["NVIDIA GeForce RTX 5090"],
                "gpu_capabilities": ["12.0"],
                "nvcc_version": "12.8",
                "vllm_version": "0.18.0",
                "vllm_flash_attn_api": "fa2",
            }
        )

        plan = plan_flash_attn_install(probe)

        self.assertTrue(plan.ok)
        self.assertEqual(plan.package_name, "flash-attn")
        self.assertEqual(plan.install_spec, "flash-attn==2.8.3")
        self.assertTrue(any("falling back to flash-attn 2.x" in warning for warning in plan.warnings))

    def test_plan_blocks_turing_entirely(self):
        probe = FlashAttnProbe.from_dict(
            {
                "python_version": "3.10.14",
                "platform_system": "Linux",
                "platform_machine": "x86_64",
                "torch_available": True,
                "torch_version": "2.4.1+cu118",
                "torch_cuda_version": "11.8",
                "gpu_names": ["NVIDIA T4"],
                "gpu_capabilities": ["7.5"],
                "nvcc_version": "11.8",
            }
        )

        plan = plan_flash_attn_install(probe, version="2.8.3")

        self.assertFalse(plan.ok)
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.target, "unsupported")
        self.assertTrue(any("unsupported" in reason.lower() for reason in plan.reasons))

    def test_probe_parser_prefers_torch_environment_over_system_python(self):
        output = "\n".join(
            [
                "__TRAINSH_FLASH_ATTN_PROBE__="
                + json.dumps(
                    {
                        "python_executable": "/usr/bin/python3",
                        "python_version": "3.12.3",
                        "platform_system": "Linux",
                        "platform_machine": "x86_64",
                        "torch_available": False,
                        "torch_error": "No module named 'torch'",
                    }
                ),
                "__TRAINSH_FLASH_ATTN_PROBE__="
                + json.dumps(
                    {
                        "python_executable": "/venv/main/bin/python",
                        "python_version": "3.12.13",
                        "platform_system": "Linux",
                        "platform_machine": "x86_64",
                        "torch_available": True,
                        "torch_version": "2.10.0+cu128",
                        "torch_cuda_version": "12.8",
                        "gpu_names": ["NVIDIA GeForce RTX 5090"],
                        "gpu_capabilities": ["12.0"],
                    }
                ),
            ]
        )

        probe = parse_flash_attn_probe_output(output)

        self.assertEqual(probe.python_executable, "/venv/main/bin/python")
        self.assertTrue(probe.torch_available)

    def test_install_script_export_contains_requested_options(self):
        script = flash_attn_install_script(
            version="2.8.3",
            python_bin=".venv/bin/python",
            force_build=True,
            max_jobs=4,
        )

        self.assertIn('PREFERRED_PY=.venv/bin/python', script)
        self.assertIn('export MAX_JOBS="4"', script)
        self.assertIn('export FLASH_ATTENTION_FORCE_BUILD="TRUE"', script)
        self.assertIn("flash-attn==2.8.3", script)

    def test_install_script_supports_flash_attn_four_and_extra_env(self):
        script = flash_attn_install_script(
            package_name="flash-attn-4",
            install_spec="flash-attn-4==4.0.0b5",
            python_bin="/venv/main/bin/python",
            extra_env={"FLASH_ATTN_CUDA_ARCHS": "120"},
        )

        self.assertIn("flash-attn-4==4.0.0b5", script)
        self.assertIn('export FLASH_ATTN_CUDA_ARCHS=120', script)
        self.assertNotIn("--no-build-isolation", script)

    def test_parse_host_flash_attn_args(self):
        name, options = parse_host_flash_attn_args(
            [
                "gpu-box",
                "--version",
                "2.8.3",
                "--python",
                ".venv/bin/python",
                "--package",
                "flash-attn",
                "--max-jobs",
                "6",
                "--force-build",
                "--apply",
                "--background",
                "--session",
                "fa-install",
                "--log",
                "/tmp/fa.log",
                "--tail-lines",
                "20",
                "--json",
            ]
        )

        self.assertEqual(name, "gpu-box")
        self.assertEqual(options.version, "2.8.3")
        self.assertEqual(options.package_name, "flash-attn")
        self.assertEqual(options.python_bin, ".venv/bin/python")
        self.assertEqual(options.max_jobs, 6)
        self.assertTrue(options.force_build)
        self.assertTrue(options.apply)
        self.assertTrue(options.background)
        self.assertEqual(options.session_name, "fa-install")
        self.assertEqual(options.log_path, "/tmp/fa.log")
        self.assertEqual(options.tail_lines, 20)
        self.assertTrue(options.json_output)

    def test_parse_host_flash_attn_matrix_args(self):
        name, options = parse_host_flash_attn_args(["--matrix"])
        self.assertEqual(name, "")
        self.assertTrue(options.show_matrix)

    def test_render_compatibility_matrix_mentions_supported_families(self):
        text = render_compatibility_matrix()
        self.assertIn("FlashAttention Compatibility Matrix", text)
        self.assertIn("CUDA Ampere / Ada", text)
        self.assertIn("Turing: unsupported", text)

    def test_host_flash_attn_runner_emits_json_plan(self):
        probe_payload = {
            "python_executable": "/usr/bin/python3",
            "python_version": "3.10.14",
            "platform_system": "Linux",
            "platform_machine": "x86_64",
            "torch_available": True,
            "torch_version": "2.4.1+cu121",
            "torch_cuda_version": "12.1",
            "torch_cxx11_abi": "FALSE",
            "gpu_names": ["NVIDIA H100 80GB HBM3"],
            "gpu_capabilities": ["9.0"],
            "nvcc_version": "12.1",
            "cpu_count": 64,
            "memory_gb": 80,
        }
        fake_probe = SimpleNamespace(
            exit_code=0,
            stdout="__TRAINSH_FLASH_ATTN_PROBE__=" + json.dumps(probe_payload),
            stderr="",
        )
        fake_ssh = SimpleNamespace(run=lambda *args, **kwargs: fake_probe)
        host = Host(name="gpu-box", hostname="gpu.example.com", username="root")
        out = io.StringIO()

        with patch("trainsh.commands.host_flash_attn.SSHClient.from_host", return_value=fake_ssh), patch(
            "trainsh.commands.host_flash_attn.load_install_record", return_value=None
        ):
            with redirect_stdout(out):
                run_host_flash_attn(
                    host,
                    label="gpu-box",
                    options=HostFlashAttnOptions(version="2.8.3", json_output=True),
                )

        payload = json.loads(out.getvalue())
        self.assertEqual(payload["host"], "gpu-box")
        self.assertEqual(payload["plan"]["status"], "ready")
        self.assertEqual(payload["probe"]["torch_version"], "2.4.1+cu121")
        self.assertEqual(payload["session_name"], "gpu-box-flash-attn-install")
        self.assertEqual(payload["log_path"], "/tmp/gpu-box-flash-attn-install.log")

    def test_host_flash_attn_apply_uses_bash_for_install(self):
        probe_payload = {
            "python_executable": "/venv/main/bin/python",
            "python_version": "3.12.13",
            "platform_system": "Linux",
            "platform_machine": "x86_64",
            "torch_available": True,
            "torch_version": "2.10.0+cu128",
            "torch_cuda_version": "12.8",
            "torch_cxx11_abi": "TRUE",
            "gpu_names": ["NVIDIA GeForce RTX 5090"],
            "gpu_capabilities": ["12.0"],
            "nvcc_version": "12.8",
        }

        calls = []

        def fake_run(command, timeout=None):
            calls.append((command, timeout))
            if len(calls) == 1:
                return SimpleNamespace(
                    exit_code=0,
                    stdout="__TRAINSH_FLASH_ATTN_PROBE__=" + json.dumps(probe_payload),
                    stderr="",
                )
            return SimpleNamespace(exit_code=0, stdout="installed\n", stderr="")

        fake_ssh = SimpleNamespace(run=fake_run)
        host = Host(name="gpu-box", hostname="gpu.example.com", username="root")
        out = io.StringIO()

        with patch("trainsh.commands.host_flash_attn.SSHClient.from_host", return_value=fake_ssh), patch(
            "trainsh.commands.host_flash_attn.load_install_record", return_value=None
        ):
            with redirect_stdout(out):
                run_host_flash_attn(
                    host,
                    label="gpu-box",
                    options=HostFlashAttnOptions(version="2.8.3", apply=True),
                )

        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1][0].startswith("bash -lc "))

    def test_host_flash_attn_background_apply_writes_script_and_starts_tmux(self):
        probe_payload = {
            "python_executable": "/venv/main/bin/python",
            "python_version": "3.12.13",
            "platform_system": "Linux",
            "platform_machine": "x86_64",
            "torch_available": True,
            "torch_version": "2.10.0+cu128",
            "torch_cuda_version": "12.8",
            "torch_cxx11_abi": "TRUE",
            "gpu_names": ["NVIDIA GeForce RTX 5090"],
            "gpu_capabilities": ["12.0"],
            "nvcc_version": "12.8",
        }
        calls = []

        def fake_run(command, timeout=None):
            calls.append((command, timeout))
            if len(calls) == 1:
                return SimpleNamespace(
                    exit_code=0,
                    stdout="__TRAINSH_FLASH_ATTN_PROBE__=" + json.dumps(probe_payload),
                    stderr="",
                )
            return SimpleNamespace(exit_code=0, stdout="mode=tmux\nsession=flash-attn\nlog=/tmp/flash-attn.log\n", stderr="")

        fake_ssh = SimpleNamespace(run=fake_run)
        host = Host(name="gpu-box", hostname="gpu.example.com", username="root")
        out = io.StringIO()

        with patch("trainsh.commands.host_flash_attn.SSHClient.from_host", return_value=fake_ssh), patch(
            "trainsh.commands.host_flash_attn.load_install_record", return_value=None
        ):
            with redirect_stdout(out):
                run_host_flash_attn(
                    host,
                    label="gpu-box",
                    options=HostFlashAttnOptions(apply=True, background=True, session_name="flash-attn", log_path="/tmp/flash-attn.log"),
                )

        self.assertEqual(len(calls), 3)
        self.assertIn("write_bytes(base64.b64decode", calls[1][0])
        self.assertIn("tmux new-session -d -s", calls[2][0])

    def test_host_flash_attn_matrix_prints_without_ssh(self):
        out = io.StringIO()
        with redirect_stdout(out):
            run_host_flash_attn(None, label="", options=HostFlashAttnOptions(show_matrix=True))
        self.assertIn("FlashAttention Compatibility Matrix", out.getvalue())


if __name__ == "__main__":
    unittest.main()
