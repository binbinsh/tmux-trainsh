import unittest

from trainsh.core.models import (
    AuthMethod,
    DiskInfo,
    Execution,
    ExecutionStatus,
    GPUInfo,
    GroupMode,
    Host,
    HostSystemInfo,
    HostType,
    HttpMethod,
    NotifyLevel,
    OperationType,
    Recipe,
    RecipeStep,
    StepResult,
    StepStatus,
    Storage,
    StorageType,
    Transfer,
    TransferEndpoint,
    TransferOperation,
    TransferStatus,
    VastInstance,
    VastOffer,
)


class ModelsMoreTests(unittest.TestCase):
    def test_host_and_storage_models(self):
        host = Host(
            name="gpu-box",
            type=HostType.SSH,
            hostname="gpu.example.com",
            port=2222,
            username="root",
            auth_method=AuthMethod.KEY,
            tags=["gpu"],
            env_vars={"x": 1},
        )
        self.assertEqual(host.display_name, "gpu-box")
        self.assertEqual(host.ssh_spec, "root@gpu.example.com -p 2222")
        data = host.to_dict()
        self.assertEqual(data["type"], "ssh")
        loaded = Host.from_dict(data)
        self.assertEqual(loaded.hostname, "gpu.example.com")

        vast_host = Host(type=HostType.VASTAI, vast_instance_id="7")
        self.assertEqual(vast_host.display_name, "Vast.ai #7")
        bare_host = Host(hostname="gpu.example.com", username="")
        self.assertEqual(bare_host.display_name, "gpu.example.com")

        self.assertEqual(StorageType.LOCAL.rclone_type, "local")
        self.assertEqual(StorageType.SSH.rclone_type, "sftp")
        self.assertEqual(StorageType.GOOGLE_DRIVE.rclone_type, "drive")
        self.assertEqual(StorageType.R2.rclone_type, "s3")
        self.assertEqual(StorageType.B2.rclone_type, "b2")
        self.assertEqual(StorageType.GCS.rclone_type, "google cloud storage")
        self.assertEqual(StorageType.S3.rclone_type, "s3")
        self.assertEqual(StorageType.SMB.rclone_type, "smb")

        storage = Storage(name="artifacts", type=StorageType.S3, config={"bucket": "x"}, is_default=True)
        payload = storage.to_dict()
        self.assertEqual(payload["type"], "s3")
        self.assertTrue(Storage.from_dict(payload).is_default)

    def test_recipe_execution_transfer_and_vast_models(self):
        step = RecipeStep(name="run", operation=OperationType.RUN_COMMANDS, params={"cmd": "echo hi"}, depends_on=["a"], retry_count=2, timeout=5.0, interactive=True)
        step_data = step.to_dict()
        self.assertEqual(step_data["operation"], "runCommands")
        self.assertEqual(RecipeStep.from_dict(step_data).operation, OperationType.RUN_COMMANDS)

        recipe = Recipe(name="demo", description="desc", steps=[step], variables={"A": "1"}, tags=["t"], version=2, is_template=True)
        recipe_data = recipe.to_dict()
        self.assertEqual(recipe_data["version"], 2)
        loaded_recipe = Recipe.from_dict(recipe_data)
        self.assertEqual(loaded_recipe.steps[0].name, "run")

        result = StepResult(step_id="1", status=StepStatus.COMPLETED, output="ok")
        execution = Execution(recipe_id="recipe-1", status=ExecutionStatus.RUNNING, step_results=[result])
        execution.append_log("hello")
        self.assertEqual(execution.logs, "hello")

        transfer = Transfer(
            source=TransferEndpoint(type="local", path="/tmp/in"),
            destination=TransferEndpoint(type="local", path="/tmp/out"),
            status=TransferStatus.RUNNING,
            operation=TransferOperation.SYNC,
            bytes_transferred=2048,
            total_bytes=4096,
        )
        self.assertIn("2.0 KB / 4.0 KB", transfer.formatted_progress)

        inst = VastInstance(id=7, actual_status="running", ssh_host="proxy", ssh_port=22, public_ipaddr="1.2.3.4", direct_port_start=2200, dph_total=1.5, gpu_ram=8192)
        self.assertTrue(inst.is_running)
        self.assertEqual(inst.display_name, "Vast.ai #7")
        self.assertIn("proxy", inst.ssh_proxy_command)
        self.assertIn("1.2.3.4", inst.ssh_direct_command)
        self.assertEqual(inst.hourly_rate, 1.5)
        self.assertEqual(inst.gpu_memory_gb, 8.0)
        self.assertEqual(inst.status_color, "green")

        self.assertEqual(VastInstance(id=8, actual_status="loading").status_color, "yellow")
        self.assertEqual(VastInstance(id=9, actual_status="stopped").status_color, "gray")
        self.assertEqual(VastInstance(id=10, actual_status="other").status_color, "gray")

        offer = VastOffer(id=1, gpu_ram=8192, dph_total=0.5)
        self.assertEqual(offer.display_gpu_ram, "8 GB")
        self.assertEqual(offer.display_price, "$0.500/hr")
        self.assertEqual(VastOffer(id=2).display_gpu_ram, "N/A")
        self.assertEqual(VastOffer(id=2).display_price, "N/A")

        self.assertEqual(HttpMethod.POST.value, "POST")
        self.assertEqual(NotifyLevel.ERROR.value, "error")
        self.assertEqual(GroupMode.PARALLEL.value, "parallel")

        sysinfo = HostSystemInfo(
            os="linux",
            kernel="6.x",
            arch="arm64",
            hostname="host",
            cpu_model="M",
            cpu_cores=8,
            memory_gb=32.0,
            gpu_info=[GPUInfo(name="A100", memory_gb=80.0)],
            disk_info=[DiskInfo(mount_point="/", total_gb=100.0, used_gb=10.0, free_gb=90.0)],
        )
        self.assertEqual(sysinfo.gpu_info[0].name, "A100")
        self.assertEqual(sysinfo.disk_info[0].mount_point, "/")


if __name__ == "__main__":
    unittest.main()
