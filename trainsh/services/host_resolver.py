"""Host resolution helpers, including on-demand Vast.ai activation."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Optional

from ..core.models import AuthMethod, Host, HostType
from .vast_connection import vast_ssh_targets

AUTO_DISCOVERED_VAST_ENV = "_auto_discovered_vast"


def _instance_connection_targets(instance) -> list[dict]:
    """Build ordered SSH connection targets for a Vast instance."""
    return vast_ssh_targets(instance)


def _apply_connection_targets(host: Host, targets: list[dict]) -> Host:
    """Apply SSH connection targets to a Host model."""
    env_vars = dict(host.env_vars or {})
    if targets:
        primary = targets[0]
        host.hostname = primary["hostname"]
        host.port = int(primary.get("port", 22) or 22)
        if len(targets) > 1:
            env_vars["connection_candidates"] = targets[1:]
        else:
            env_vars.pop("connection_candidates", None)
        env_vars["vast_ssh_ready"] = True
    else:
        host.hostname = ""
        host.port = 22
        env_vars.pop("connection_candidates", None)
        env_vars.pop("vast_ssh_ready", None)
    host.env_vars = env_vars
    return host


def build_host_from_vast_instance(
    instance,
    *,
    name: str,
    base_host: Optional[Host] = None,
    auto_discovered: bool = False,
) -> Host:
    """Convert one Vast instance into a Host model."""
    if base_host is not None:
        host = Host.from_dict(base_host.to_dict())
    else:
        host = Host(
            name=name,
            type=HostType.VASTAI,
            username="root",
            auth_method=AuthMethod.KEY,
        )

    host.name = name
    host.type = HostType.VASTAI
    host.username = host.username or "root"
    host.auth_method = host.auth_method or AuthMethod.KEY
    host.vast_instance_id = str(instance.id)
    host.vast_template_name = getattr(instance, "template_name", None)
    host.vast_status = getattr(instance, "actual_status", None)
    host.gpu_count = getattr(instance, "num_gpus", None)
    host.hourly_rate = getattr(instance, "dph_total", None)

    disk_space = getattr(instance, "disk_space", None)
    if disk_space is not None:
        try:
            host.disk_gb = int(float(disk_space))
        except (TypeError, ValueError):
            host.disk_gb = None

    env_vars = dict(host.env_vars or {})
    if auto_discovered:
        env_vars[AUTO_DISCOVERED_VAST_ENV] = True
    elif AUTO_DISCOVERED_VAST_ENV not in env_vars:
        env_vars.pop(AUTO_DISCOVERED_VAST_ENV, None)
    env_vars["vast_label"] = str(getattr(instance, "label", "") or "")
    host.env_vars = env_vars

    return _apply_connection_targets(host, _instance_connection_targets(instance))


def _test_ssh_connection(
    hostname: str,
    port: int,
    *,
    username: str = "root",
    key_path: Optional[str] = None,
    timeout: int = 5,
) -> bool:
    """Check whether an SSH target is reachable with the current key settings."""
    if not hostname:
        return False

    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "StrictHostKeyChecking=no",
        "-p",
        str(port),
    ]

    if key_path:
        expanded = os.path.expanduser(key_path)
        if os.path.exists(expanded):
            args.extend(["-i", expanded])

    args.extend([f"{username}@{hostname}", "echo ok"])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
    except Exception:
        return False
    return result.returncode == 0 and "ok" in result.stdout


def _pick_reachable_targets(
    targets: list[dict],
    *,
    username: str,
    key_path: Optional[str],
) -> Optional[list[dict]]:
    """Pick a working SSH target and keep the others as fallbacks."""
    for index, target in enumerate(targets):
        if _test_ssh_connection(
            target.get("hostname", ""),
            int(target.get("port", 22) or 22),
            username=username,
            key_path=key_path,
        ):
            return [targets[index], *targets[:index], *targets[index + 1 :]]
    return None


def prepare_vast_host(
    host: Host,
    *,
    auto_start: bool = True,
    timeout_seconds: int = 300,
    poll_seconds: int = 5,
) -> Host:
    """Resolve a Vast host into a concrete SSH-ready Host, starting it if needed."""
    if host.type != HostType.VASTAI or not host.vast_instance_id:
        return host

    from .vast_api import get_vast_client

    client = get_vast_client()
    instance_id = int(host.vast_instance_id)
    instance = client.get_instance(instance_id)
    started = False
    deadline = time.monotonic() + max(timeout_seconds, 1)

    while True:
        status = str(getattr(instance, "actual_status", "") or "").lower()
        if auto_start and not started and status in {"stopped", "exited"}:
            client.start_instance(instance_id)
            started = True
            time.sleep(min(max(poll_seconds, 1), 10))
            instance = client.get_instance(instance_id)
            continue

        targets = _instance_connection_targets(instance)
        if status == "running" and targets:
            ordered_targets = _pick_reachable_targets(
                targets,
                username=host.username or "root",
                key_path=host.ssh_key_path,
            )
            if ordered_targets is not None:
                resolved = build_host_from_vast_instance(
                    instance,
                    name=host.name or f"vast-{instance_id}",
                    base_host=host,
                    auto_discovered=bool((host.env_vars or {}).get(AUTO_DISCOVERED_VAST_ENV)),
                )
                return _apply_connection_targets(resolved, ordered_targets)

        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Vast.ai instance {instance_id} did not become SSH-ready within "
                f"{timeout_seconds}s (status: {status or 'unknown'})."
            )

        time.sleep(max(poll_seconds, 1))
        instance = client.get_instance(instance_id)
