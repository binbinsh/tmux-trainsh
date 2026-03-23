# tmux-trainsh runpod command
# RunPod Pod management

from __future__ import annotations

import os
import sys
from typing import List, Optional

from ..cli_utils import SubcommandSpec, dispatch_subcommand, prompt_input
from .help_catalog import render_command_help
from .help_cmd import reject_subcommand_help
from ..core.models import AuthMethod, Host, HostType
from .remote_run import (
    parse_remote_clone_args,
    parse_remote_run_args,
    run_remote_command,
    run_remote_git_clone,
)

SUBCOMMAND_SPECS = (
    SubcommandSpec("list", "List your current RunPod Pods."),
    SubcommandSpec("show", "Inspect one Pod in detail."),
    SubcommandSpec("ssh", "Open SSH to a running Pod."),
    SubcommandSpec("run", "Run one remote shell command on a Pod."),
    SubcommandSpec("clone", "Clone one git repository on a Pod."),
    SubcommandSpec("start", "Start or resume a Pod."),
    SubcommandSpec("stop", "Stop a Pod."),
    SubcommandSpec("reboot", "Restart a Pod."),
    SubcommandSpec("remove", "Delete a Pod."),
    SubcommandSpec("search", "Search available GPU types and price hints."),
)

usage = render_command_help("runpod")


def _print_pod_table(pods) -> None:
    if not pods:
        print("No RunPod Pods found.")
        return

    print(f"{'ID':<18} {'Name':<20} {'GPU':<24} {'#GPU':<5} {'Status':<10} {'$/hr':<8} {'SSH'}")
    print("-" * 108)
    for pod in pods:
        gpu_text = str(getattr(pod, "gpu_display_name", "") or getattr(pod, "gpu_type_id", "") or "N/A")
        status = str(getattr(pod, "desired_status", "") or "unknown")
        price = float(getattr(pod, "cost_per_hr", 0.0) or 0.0)
        mappings = getattr(pod, "port_mappings", None) or {}
        ssh_port = mappings.get("22")
        ssh_text = f"{getattr(pod, 'public_ip', '')}:{ssh_port}" if getattr(pod, "public_ip", "") and ssh_port else "-"
        print(
            f"{str(pod.id):<18} "
            f"{str(getattr(pod, 'name', '') or '')[:20]:<20} "
            f"{gpu_text[:24]:<24} "
            f"{int(getattr(pod, 'gpu_count', 0) or 0):<5} "
            f"{status[:10]:<10} "
            f"${price:<7.3f} "
            f"{ssh_text}"
        )


def _print_pod_detail(pod) -> None:
    print(f"RunPod Pod: {pod.id}")
    print(f"  Name: {getattr(pod, 'name', '') or '(unnamed)'}")
    print(f"  Status: {getattr(pod, 'desired_status', '') or 'unknown'}")
    print(f"  GPU: {getattr(pod, 'gpu_display_name', '') or getattr(pod, 'gpu_type_id', '') or 'N/A'}")
    print(f"  GPU Count: {int(getattr(pod, 'gpu_count', 0) or 0)}")
    if getattr(pod, "gpu_memory_gb", None):
        print(f"  GPU Memory: {float(pod.gpu_memory_gb):.0f} GB")
    print(f"  Image: {getattr(pod, 'image_name', '') or 'N/A'}")
    print(f"  Cloud: {getattr(pod, 'cloud_type', '') or 'N/A'}")
    print(f"  Cost: ${float(getattr(pod, 'cost_per_hr', 0.0) or 0.0):.3f}/hr")
    if getattr(pod, "container_disk_in_gb", None) is not None:
        print(f"  Container Disk: {pod.container_disk_in_gb} GB")
    if getattr(pod, "volume_in_gb", None) is not None:
        print(f"  Volume: {pod.volume_in_gb} GB")
    print(f"  Public IP: {getattr(pod, 'public_ip', '') or '(not available)'}")
    mappings = getattr(pod, "port_mappings", None) or {}
    if mappings:
        print("  Port Mappings:")
        for internal, external in sorted(mappings.items(), key=lambda item: int(str(item[0])) if str(item[0]).isdigit() else str(item[0])):
            print(f"    {internal} -> {external}")
    ports = getattr(pod, "ports", None) or []
    if ports:
        print(f"  Exposed Ports: {', '.join(str(item) for item in ports)}")


def cmd_list(args: List[str]) -> None:
    """List RunPod Pods."""
    from ..services.runpod_api import get_runpod_client

    print("RunPod Pods:")
    client = get_runpod_client()
    _print_pod_table(client.list_pods())


def cmd_show(args: List[str]) -> None:
    """Show Pod details."""
    if not args:
        print("Usage: train runpod show <pod_id>")
        sys.exit(1)

    from ..services.runpod_api import get_runpod_client

    client = get_runpod_client()
    pod = client.get_pod(str(args[0]).strip())
    _print_pod_detail(pod)


def cmd_ssh(args: List[str]) -> None:
    """SSH into a Pod."""
    if not args:
        print("Usage: train runpod ssh <pod_id>")
        sys.exit(1)

    from ..services.runpod_api import get_runpod_client
    from ..services.runpod_connection import preferred_runpod_ssh_target, ssh_target_to_command

    pod_id = str(args[0]).strip()
    client = get_runpod_client()
    pod = client.get_pod(pod_id)

    if not pod.is_running:
        print(f"Pod not running (status: {pod.desired_status})")
        print("Use 'train runpod start <id>' to start the Pod.")
        sys.exit(1)

    target = preferred_runpod_ssh_target(pod)
    if target is None:
        print("SSH host not available for this Pod.")
        print("Make sure the Pod exposes 22/tcp and has a public IP.")
        sys.exit(1)

    print(f"Connecting to {target['hostname']}:{int(target['port'])}...")
    os.system(ssh_target_to_command(target))


def cmd_run(args: List[str]) -> None:
    """Run one command on a RunPod Pod."""
    pod_id, command = parse_remote_run_args(args, usage="train runpod run <pod-id> -- <command>")
    host = Host(
        name=f"runpod-{pod_id}",
        type=HostType.RUNPOD,
        username="root",
        auth_method=AuthMethod.KEY,
        runpod_pod_id=str(pod_id),
    )
    run_remote_command(host, command, label=f"RunPod #{pod_id}")


def cmd_clone(args: List[str]) -> None:
    """Clone one repository on a RunPod Pod."""
    pod_id, request = parse_remote_clone_args(
        args,
        usage=(
            "train runpod clone <pod-id> <repo-url> [destination] "
            "[--branch <name>] [--depth <n>] [--auth auto|github_token|plain] "
            "[--token-secret <name>]"
        ),
    )
    host = Host(
        name=f"runpod-{pod_id}",
        type=HostType.RUNPOD,
        username="root",
        auth_method=AuthMethod.KEY,
        runpod_pod_id=str(pod_id),
    )
    run_remote_git_clone(host, request, label=f"RunPod #{pod_id}")


def cmd_start(args: List[str]) -> None:
    """Start a Pod."""
    if not args:
        print("Usage: train runpod start <pod_id>")
        sys.exit(1)

    from ..services.runpod_api import get_runpod_client

    pod_id = str(args[0]).strip()
    print(f"Starting Pod {pod_id}...")
    get_runpod_client().start_pod(pod_id)
    print("Pod started.")


def cmd_stop(args: List[str]) -> None:
    """Stop a Pod."""
    if not args:
        print("Usage: train runpod stop <pod_id>")
        sys.exit(1)

    from ..services.runpod_api import get_runpod_client

    pod_id = str(args[0]).strip()
    print(f"Stopping Pod {pod_id}...")
    get_runpod_client().stop_pod(pod_id)
    print("Pod stopped.")


def cmd_reboot(args: List[str]) -> None:
    """Restart a Pod."""
    if not args:
        print("Usage: train runpod reboot <pod_id>")
        sys.exit(1)

    from ..services.runpod_api import get_runpod_client

    pod_id = str(args[0]).strip()
    print(f"Restarting Pod {pod_id}...")
    get_runpod_client().restart_pod(pod_id)
    print("Pod restarting.")


def cmd_rm(args: List[str]) -> None:
    """Delete a Pod."""
    if not args:
        print("Usage: train runpod remove <pod_id>")
        sys.exit(1)

    pod_id = str(args[0]).strip()
    confirm = prompt_input(f"Delete Pod {pod_id}? This cannot be undone. (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    from ..services.runpod_api import get_runpod_client

    print(f"Deleting Pod {pod_id}...")
    get_runpod_client().delete_pod(pod_id)
    print("Pod removed.")


def cmd_search(args: List[str]) -> None:
    """Search available GPU types and price hints."""
    from ..services.runpod_api import get_runpod_client

    gpu_name = None
    num_gpus = 1
    min_gpu_ram = None
    max_dph = None
    cloud_type = "SECURE"

    for arg in args:
        if "=" not in arg:
            if gpu_name is None:
                gpu_name = arg.strip()
            continue
        key, _, value = arg.partition("=")
        value = value.strip()
        if key in ("gpu", "gpu_name"):
            gpu_name = value
        elif key in ("gpus", "num_gpus"):
            num_gpus = int(value)
        elif key in ("min_gpu_ram", "min_vram_gb"):
            min_gpu_ram = float(value)
        elif key in ("max_dph", "max_price"):
            max_dph = float(value)
        elif key == "cloud_type":
            cloud_type = value.upper() or cloud_type

    print("Searching RunPod GPU types...")
    client = get_runpod_client()
    gpu_types = client.list_gpu_types(
        gpu_name=gpu_name,
        max_dph=max_dph,
        min_gpu_ram=min_gpu_ram,
        gpu_count=num_gpus,
        secure_cloud=cloud_type != "COMMUNITY",
    )
    if not gpu_types:
        print("No GPU types found.")
        return

    print(f"{'GPU':<28} {'VRAM':<6} {'Best $/hr':<10} {'Cloud $/hr':<11} {'Stock'}")
    print("-" * 78)
    for gpu in sorted(gpu_types, key=lambda item: (float(item.best_hourly_price or 0.0), -(float(item.memory_gb or 0.0)))):
        cloud_price = gpu.secure_price if cloud_type != "COMMUNITY" else gpu.community_price
        print(
            f"{str(gpu.display_name or gpu.id)[:28]:<28} "
            f"{int(float(gpu.memory_gb or 0.0)):<6} "
            f"${float(gpu.best_hourly_price or 0.0):<9.3f} "
            f"${float(cloud_price or 0.0):<10.3f} "
            f"{str(gpu.stock_status or 'unknown')}"
        )


def main(args: List[str]) -> Optional[str]:
    """Main entry point for runpod command."""
    if not args:
        print(usage)
        return None
    if args[0] in ("-h", "--help", "help"):
        reject_subcommand_help()

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "ssh": cmd_ssh,
        "run": cmd_run,
        "clone": cmd_clone,
        "start": cmd_start,
        "stop": cmd_stop,
        "reboot": cmd_reboot,
        "search": cmd_search,
        "remove": cmd_rm,
    }

    try:
        handler = dispatch_subcommand(subcommand, commands=commands)
    except KeyError:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    try:
        handler(subargs)
    except Exception as exc:
        if "RUNPOD_API_KEY" in str(exc) or "runpod api key" in str(exc).lower():
            print(f"Error: {exc}")
            print("\nMake sure RUNPOD_API_KEY is set:")
            print("  train secrets set RUNPOD_API_KEY")
        else:
            raise

    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "RunPod Pod management"
    cd["short_desc"] = "Manage RunPod GPU Pods"
