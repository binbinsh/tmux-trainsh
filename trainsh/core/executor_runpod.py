# tmux-trainsh RunPod control helpers
# Encapsulates runpod.* command logic from executor main.

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, List, Optional


class RunpodControlHelper:
    """Helper for runpod.* control commands."""

    def __init__(
        self,
        executor: Any,
        build_ssh_args: Callable[..., list[str]],
        format_duration: Callable[[float], str],
    ):
        self.executor = executor
        self.build_ssh_args = build_ssh_args
        self.format_duration = format_duration

    def _resolve_pod_id(self, value: Any) -> Optional[str]:
        """Resolve a RunPod Pod ID from a direct id or a recipe host alias."""
        text = str(value or "").strip()
        if not text:
            return None
        if text.startswith("@"):
            text = text[1:].strip()
        if not text:
            return None

        alias_var = self.executor.ctx.variables.get(f"RUNPOD_ID_{text}")
        if alias_var:
            return str(alias_var).strip()

        host_value = str(self.executor.recipe.hosts.get(text, "")).strip()
        if host_value.startswith("runpod:"):
            return host_value.split(":", 1)[1].strip()
        return text

    def _set_tracking(
        self,
        pod_id: str,
        *,
        host_name: Optional[str] = None,
        set_start_time: bool = False,
    ) -> None:
        self.executor.ctx.variables["_runpod_pod_id"] = str(pod_id)
        self.executor.ctx.variables["RUNPOD_ID"] = str(pod_id)
        if host_name:
            self.executor.ctx.variables[f"RUNPOD_ID_{host_name}"] = str(pod_id)
        if set_start_time:
            self.executor.ctx.variables["_runpod_start_time"] = datetime.now().isoformat()
        if self.executor.logger:
            self.executor.logger.log_variable("_runpod_pod_id", str(pod_id), "runpod")
            self.executor.logger.log_variable("RUNPOD_ID", str(pod_id), "runpod")
            if host_name:
                self.executor.logger.log_variable(f"RUNPOD_ID_{host_name}", str(pod_id), "runpod")

    def cmd_runpod_start(self, args: List[str]) -> tuple[bool, str]:
        """Handle: runpod.start <pod_id>"""
        from ..services.runpod_api import RunpodAPIError, get_runpod_client

        if not args:
            return False, "No Pod ID provided for runpod.start"

        try:
            client = get_runpod_client()
            pod_id = self._resolve_pod_id(self.executor._interpolate(args[0]))
            if not pod_id:
                return False, "No Pod ID provided for runpod.start"

            pod = client.get_pod(pod_id)
            if pod.is_running:
                self._set_tracking(pod_id, set_start_time=not bool(self.executor.ctx.variables.get("_runpod_start_time")))
                return True, f"Pod already running: {pod_id}"

            client.start_pod(pod_id)
            self._set_tracking(pod_id, set_start_time=True)
            if self.executor.logger:
                self.executor.logger.log_detail("runpod_start", f"Started Pod {pod_id}", {"pod_id": pod_id})
            return True, f"Started Pod: {pod_id}"
        except (RunpodAPIError, RuntimeError) as exc:
            return False, str(exc)

    def cmd_runpod_stop(self, args: List[str]) -> tuple[bool, str]:
        """Handle: runpod.stop <pod_id>"""
        from ..services.runpod_api import RunpodAPIError, get_runpod_client

        if not args:
            return False, "No Pod ID provided for runpod.stop"

        try:
            client = get_runpod_client()
            pod_id = self._resolve_pod_id(self.executor._interpolate(args[0]))
            if not pod_id:
                return False, "No Pod ID provided for runpod.stop"
            client.stop_pod(pod_id)
            if self.executor.logger:
                self.executor.logger.log_detail("runpod_stop", f"Stopped Pod {pod_id}", {"pod_id": pod_id})
            return True, f"Stopped Pod: {pod_id}"
        except (RunpodAPIError, RuntimeError) as exc:
            return False, str(exc)

    def cmd_runpod_pick(self, args: List[str]) -> tuple[bool, str]:
        """Handle: runpod.pick @host ..."""
        from ..constants import DEFAULT_RUNPOD_IMAGE, DEFAULT_RUNPOD_VOLUME_GB
        from ..services.runpod_api import RunpodAPIError, get_runpod_client

        host_name = None
        gpu_name = None
        num_gpus = None
        min_gpu_ram = None
        max_dph = None
        limit = 20
        skip_if_set = True
        auto_select = False
        create_if_missing = False
        image = DEFAULT_RUNPOD_IMAGE
        disk_gb = 50.0
        volume_gb = float(DEFAULT_RUNPOD_VOLUME_GB)
        label = None
        cloud_type = "SECURE"

        for arg in args:
            if "=" in arg:
                key, _, value = arg.partition("=")
                value = self.executor._interpolate(value)
                if key in ("host", "host_name"):
                    host_name = value
                elif key in ("gpu", "gpu_name"):
                    gpu_name = value
                elif key in ("num_gpus", "gpus"):
                    try:
                        num_gpus = int(value)
                    except ValueError:
                        return False, f"Invalid num_gpus: {value}"
                elif key in ("min_gpu_ram", "min_vram_gb"):
                    try:
                        min_gpu_ram = float(value)
                    except ValueError:
                        return False, f"Invalid min_gpu_ram: {value}"
                elif key in ("max_dph", "max_price"):
                    try:
                        max_dph = float(value)
                    except ValueError:
                        return False, f"Invalid max_dph: {value}"
                elif key == "limit":
                    try:
                        limit = int(value)
                    except ValueError:
                        return False, f"Invalid limit: {value}"
                elif key == "skip_if_set":
                    skip_if_set = value.lower() in ("1", "true", "yes", "y")
                elif key == "auto_select":
                    auto_select = value.lower() in ("1", "true", "yes", "y")
                elif key == "create_if_missing":
                    create_if_missing = value.lower() in ("1", "true", "yes", "y")
                elif key == "image":
                    image = value or image
                elif key in ("disk_gb", "disk"):
                    try:
                        disk_gb = float(value)
                    except ValueError:
                        return False, f"Invalid disk_gb: {value}"
                elif key == "volume_gb":
                    try:
                        volume_gb = float(value)
                    except ValueError:
                        return False, f"Invalid volume_gb: {value}"
                elif key == "label":
                    label = value or None
                elif key == "cloud_type":
                    cloud_type = value.strip().upper() or cloud_type
                continue
            if host_name is None:
                host_name = self.executor._interpolate(arg)

        if host_name:
            if host_name.startswith("@"):
                host_name = host_name[1:]
        elif "gpu" in self.executor.recipe.hosts:
            host_name = "gpu"
        else:
            return False, "No host alias provided for runpod.pick"

        existing_id = None
        if skip_if_set:
            for key in ("_runpod_pod_id", "RUNPOD_ID"):
                value = str(self.executor.ctx.variables.get(key, "")).strip()
                if value:
                    existing_id = value
                    break

        if existing_id:
            self.executor.recipe.hosts[host_name] = f"runpod:{existing_id}"
            self._set_tracking(existing_id, host_name=host_name)
            return True, f"Using existing Pod: {existing_id}"

        try:
            client = get_runpod_client()
            pods = client.list_pods()

            gpu_memory = {}
            if min_gpu_ram is not None:
                for gpu in client.list_gpu_types():
                    if gpu.id:
                        gpu_memory[gpu.id] = gpu.memory_gb
                    if gpu.display_name:
                        gpu_memory[gpu.display_name] = gpu.memory_gb

            def matches_filters(pod: Any) -> bool:
                gpu_text = f"{getattr(pod, 'gpu_display_name', '')} {getattr(pod, 'gpu_type_id', '')}".strip().lower()
                if gpu_name and gpu_name.strip().lower() not in gpu_text:
                    return False
                if num_gpus and int(getattr(pod, "gpu_count", 0) or 0) < num_gpus:
                    return False
                if min_gpu_ram is not None:
                    memory_gb = getattr(pod, "gpu_memory_gb", None)
                    if memory_gb in (None, 0):
                        memory_gb = gpu_memory.get(getattr(pod, "gpu_type_id", "")) or gpu_memory.get(getattr(pod, "gpu_display_name", ""))
                    if memory_gb not in (None, 0) and float(memory_gb) < float(min_gpu_ram):
                        return False
                if max_dph is not None:
                    price = float(getattr(pod, "cost_per_hr", 0.0) or 0.0)
                    if price > float(max_dph):
                        return False
                return True

            pods = [pod for pod in pods if matches_filters(pod)]
            if not pods:
                if not create_if_missing:
                    return False, "No RunPod Pods match filters"

                gpu_types = client.list_gpu_types(
                    gpu_name=gpu_name,
                    max_dph=max_dph,
                    min_gpu_ram=min_gpu_ram,
                    gpu_count=num_gpus or 1,
                    secure_cloud=cloud_type != "COMMUNITY",
                )
                if num_gpus:
                    gpu_types = [
                        gpu
                        for gpu in gpu_types
                        if not gpu.available_gpu_counts or num_gpus in gpu.available_gpu_counts or max(gpu.available_gpu_counts) >= num_gpus
                    ]
                if not gpu_types:
                    return False, "No RunPod GPU types match filters"

                gpu_types = sorted(
                    gpu_types,
                    key=lambda item: (
                        float(item.best_hourly_price or 0.0),
                        -(float(item.memory_gb or 0.0)),
                    ),
                )
                selected_gpu = gpu_types[0]
                pod = client.create_pod(
                    name=label or host_name,
                    gpu_type_id=selected_gpu.id,
                    gpu_count=num_gpus or 1,
                    image_name=image,
                    cloud_type=cloud_type,
                    container_disk_in_gb=int(disk_gb),
                    volume_in_gb=int(volume_gb),
                    ports=["22/tcp"],
                    support_public_ip=True,
                )
                self.executor.recipe.hosts[host_name] = f"runpod:{pod.id}"
                self._set_tracking(pod.id, host_name=host_name)
                return True, f"Created Pod {pod.id} ({selected_gpu.display_name or selected_gpu.id})"

            if limit and limit > 0:
                pods = pods[:limit]

            def status_rank(pod: Any) -> int:
                status = str(getattr(pod, "desired_status", "") or "").upper()
                if status == "RUNNING":
                    return 0
                if status == "EXITED":
                    return 1
                return 2

            pods = sorted(
                pods,
                key=lambda item: (
                    status_rank(item),
                    float(getattr(item, "cost_per_hr", 0.0) or 0.0),
                ),
            )

            if auto_select:
                selected = pods[0]
                self.executor.recipe.hosts[host_name] = f"runpod:{selected.id}"
                self._set_tracking(selected.id, host_name=host_name)
                return True, f"Selected Pod {selected.id}"

            print("\nSelect a RunPod Pod:")
            print("-" * 96)
            print(f"{'#':<4} {'ID':<18} {'Name':<20} {'GPU':<24} {'#GPU':<5} {'Status':<10} {'$/hr':<8}")
            print("-" * 96)
            for index, pod in enumerate(pods, 1):
                gpu_text = str(getattr(pod, "gpu_display_name", "") or getattr(pod, "gpu_type_id", "") or "N/A")
                price = float(getattr(pod, "cost_per_hr", 0.0) or 0.0)
                print(
                    f"{index:<4} {str(pod.id):<18} "
                    f"{str(getattr(pod, 'name', '') or '')[:20]:<20} "
                    f"{gpu_text[:24]:<24} "
                    f"{int(getattr(pod, 'gpu_count', 0) or 0):<5} "
                    f"{str(getattr(pod, 'desired_status', '') or 'unknown')[:10]:<10} "
                    f"${price:<7.3f}"
                )
            print("-" * 96)

            try:
                choice = input(f"Enter number (1-{len(pods)}) or Pod ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                return False, "Selection cancelled"

            selected = None
            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(pods):
                    selected = pods[num - 1]
            if selected is None:
                for pod in pods:
                    if str(pod.id) == choice:
                        selected = pod
                        break
            if selected is None:
                return False, "Invalid selection"

            self.executor.recipe.hosts[host_name] = f"runpod:{selected.id}"
            self._set_tracking(selected.id, host_name=host_name)
            return True, f"Selected Pod {selected.id}"
        except (RunpodAPIError, RuntimeError) as exc:
            return False, str(exc)

    def cmd_runpod_wait(self, args: List[str]) -> tuple[bool, str]:
        """Handle: runpod.wait <pod_id> timeout=10m ..."""
        from ..services.runpod_api import RunpodAPIError, get_runpod_client
        from ..services.runpod_connection import runpod_ssh_targets, ssh_target_to_command, ssh_target_to_spec

        pod_id = None
        timeout = 600
        poll_interval = 10
        stop_on_fail = True

        for arg in args:
            if "=" in arg:
                key, _, value = arg.partition("=")
                if key == "timeout":
                    timeout = self.executor._parse_duration(self.executor._interpolate(value))
                elif key in ("poll", "poll_interval"):
                    poll_interval = self.executor._parse_duration(self.executor._interpolate(value))
                elif key == "stop_on_fail":
                    stop_on_fail = value.lower() in ("1", "true", "yes", "y")
                continue
            if pod_id is None:
                pod_id = self._resolve_pod_id(self.executor._interpolate(arg))

        if not pod_id:
            return False, "No Pod ID provided for runpod.wait"

        self._set_tracking(pod_id)
        start_time = time.time()
        last_status = "unknown"

        try:
            client = get_runpod_client()
            while time.time() - start_time < timeout:
                pod = client.get_pod(pod_id)
                last_status = str(getattr(pod, "desired_status", "") or "unknown")
                targets = runpod_ssh_targets(pod)
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed

                if self.executor.logger:
                    self.executor.logger.log_wait(
                        f"runpod:{pod_id}",
                        f"status={last_status},ssh_ready={bool(targets)}",
                        elapsed,
                        remaining,
                        f"status={last_status}",
                    )

                if pod.is_running and targets:
                    self.executor.log(f"  Connection details for Pod {pod_id}:")
                    for target in targets:
                        source = str(target.get("source") or "ssh").replace("_", " ")
                        self.executor.log(f"    {source}: {ssh_target_to_command(target)}")

                    ssh_spec = ssh_target_to_spec(targets[0])
                    if self.verify_ssh_connection(ssh_spec, timeout=10):
                        if not self.executor.ctx.variables.get("_runpod_start_time"):
                            self.executor.ctx.variables["_runpod_start_time"] = datetime.now().isoformat()
                        return True, f"Pod is SSH-ready: {pod_id}"

                time.sleep(max(poll_interval, 1))

            message = (
                f"RunPod Pod {pod_id} did not become SSH-ready within {timeout}s "
                f"(status: {last_status}). Make sure 22/tcp is exposed."
            )
            if stop_on_fail:
                try:
                    client.stop_pod(pod_id)
                    message += "; Pod stopped"
                except Exception:
                    pass
            return False, message
        except (RunpodAPIError, RuntimeError) as exc:
            return False, str(exc)

    def cmd_runpod_cost(self, args: List[str]) -> tuple[bool, str]:
        """Handle: runpod.cost [pod_id]"""
        from ..services.runpod_api import RunpodAPIError, get_runpod_client

        pod_id = None
        if args:
            pod_id = self._resolve_pod_id(self.executor._interpolate(args[0]))
        if not pod_id:
            pod_id = str(self.executor.ctx.variables.get("RUNPOD_ID") or self.executor.ctx.variables.get("_runpod_pod_id") or "").strip()
        if not pod_id:
            return False, "No Pod ID provided for runpod.cost"

        try:
            client = get_runpod_client()
            pod = client.get_pod(pod_id)
            hourly = float(getattr(pod, "cost_per_hr", 0.0) or 0.0)
            if hourly <= 0:
                return True, f"RunPod Pod {pod_id}: hourly cost unavailable"

            start_text = str(self.executor.ctx.variables.get("_runpod_start_time", "") or "").strip()
            if not start_text:
                return True, f"RunPod Pod {pod_id}: ${hourly:.3f}/hr"

            try:
                started_at = datetime.fromisoformat(start_text)
            except ValueError:
                return True, f"RunPod Pod {pod_id}: ${hourly:.3f}/hr"

            elapsed_seconds = max((datetime.now() - started_at).total_seconds(), 0.0)
            estimated_cost = hourly * (elapsed_seconds / 3600.0)
            return True, (
                f"RunPod Pod {pod_id}: ${hourly:.3f}/hr, "
                f"estimated ${estimated_cost:.3f} over {self.format_duration(elapsed_seconds)}"
            )
        except (RunpodAPIError, RuntimeError) as exc:
            return False, str(exc)

    def verify_ssh_connection(self, ssh_spec: str, timeout: int = 10) -> bool:
        """Verify SSH connectivity for a given host spec."""
        return self.executor._verify_ssh_connection(ssh_spec, timeout=timeout)
