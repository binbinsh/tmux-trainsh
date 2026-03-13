# tmux-trainsh host command
# Host management

import sys
import os
from typing import Optional, List
import re

from ..cli_utils import SubcommandSpec, dispatch_subcommand, prompt_input, render_command_help
from .host_interactive import (
    _normalize_connection_candidates,
    _prompt_connection_candidates,
    _prompt_int,
    _render_connection_candidate_line,
    cmd_add,
    cmd_browse,
    cmd_edit,
)

SUBCOMMAND_SPECS = (
    SubcommandSpec("list", "List named reusable host definitions."),
    SubcommandSpec("add", "Add a new SSH or Colab-backed host interactively."),
    SubcommandSpec("edit", "Modify an existing named host."),
    SubcommandSpec("show", "Inspect one host definition."),
    SubcommandSpec("ssh", "Open an SSH session using the stored connection settings."),
    SubcommandSpec("files", "Browse remote files over SFTP."),
    SubcommandSpec("check", "Check whether a host is reachable."),
    SubcommandSpec("remove", "Delete a stored host definition."),
)

usage = render_command_help(
    command="train host",
    summary="Manage named SSH or Colab host definitions used by recipes and transfers.",
    usage_lines=(
        "train host <subcommand> [args...]",
        "train host ssh <name>",
        "train host files <name> [path]",
    ),
    subcommands=SUBCOMMAND_SPECS,
    notes=(
        "Hosts are stored in ~/.config/tmux-trainsh/hosts.yaml.",
        "Use train vast for provider-side instance lifecycle operations.",
        "Use train colab for quick one-off Colab tunnel helpers; prefer train host add for reusable configs.",
    ),
    examples=(
        "train host list",
        "train host add",
        "train host show gpu-box",
        "train host ssh gpu-box",
        "train host check gpu-box",
    ),
)


def load_hosts() -> dict:
    """Load hosts from configuration."""
    from ..constants import HOSTS_FILE
    import yaml

    if not HOSTS_FILE.exists():
        return {}

    with open(HOSTS_FILE, "r") as f:
        data = yaml.safe_load(f) or {}

    hosts = {}
    for host_data in data.get("hosts", []):
        from ..core.models import Host
        host = Host.from_dict(host_data)
        hosts[host.name or host.id] = host

    return hosts


def _host_to_dict(host) -> dict:
    """Convert a host to a filtered dict (no None values)."""
    return {k: v for k, v in host.to_dict().items() if v is not None}


def save_hosts(hosts: dict) -> None:
    """Save hosts to configuration."""
    from ..constants import HOSTS_FILE, CONFIG_DIR
    import yaml

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {"hosts": [_host_to_dict(h) for h in hosts.values()]}

    with open(HOSTS_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def cmd_list(args: List[str]) -> None:
    """List configured hosts."""
    from ..core.models import HostType

    hosts = load_hosts()

    if not hosts:
        print("No hosts configured.")
        print("Use 'train host add' to add a host.")
        return

    print("Configured hosts:")
    print("-" * 60)

    for name, host in hosts.items():
        status = ""
        if host.type == HostType.VASTAI and host.vast_instance_id:
            status = f" [Vast.ai #{host.vast_instance_id}]"
        elif host.type == HostType.COLAB:
            tunnel = host.env_vars.get("tunnel_type", "cloudflared")
            status = f" [Colab/{tunnel}]"
        print(f"  {name:<20} {host.username}@{host.hostname}:{host.port}{status}")

    print("-" * 60)
    print(f"Total: {len(hosts)} hosts")


def cmd_show(args: List[str]) -> None:
    """Show host details."""
    from ..core.models import HostType

    if not args:
        print("Usage: train host show <name>")
        sys.exit(1)

    name = args[0]
    hosts = load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    host = hosts[name]
    print(f"Host: {host.display_name}")
    print(f"  Type: {host.type.value}")
    print(f"  Hostname: {host.hostname}")
    print(f"  Port: {host.port}")
    print(f"  Username: {host.username}")
    print(f"  Auth: {host.auth_method.value}")
    if host.ssh_key_path:
        print(f"  SSH Key: {host.ssh_key_path}")
    if host.jump_host:
        print(f"  Jump Host: {host.jump_host}")
    tunnel_type = host.env_vars.get("tunnel_type", "")
    if host.type == HostType.SSH and tunnel_type == "cloudflared":
        print("  Tunnel: cloudflared")
        print(f"  Cloudflared Hostname: {host.env_vars.get('cloudflared_hostname', host.hostname)}")
        if host.env_vars.get("cloudflared_bin"):
            print(f"  Cloudflared Bin: {host.env_vars.get('cloudflared_bin')}")
    proxy_command = host.env_vars.get("proxy_command", "")
    if proxy_command:
        print(f"  ProxyCommand: {proxy_command}")
    connection_candidates = _normalize_connection_candidates(host.env_vars.get("connection_candidates", []))
    if connection_candidates:
        print("  Connection candidates:")
        for idx, candidate in enumerate(connection_candidates, start=1):
            print(f"    {_render_connection_candidate_line(idx, candidate)}")
    if host.tags:
        print(f"  Tags: {', '.join(host.tags)}")
    if host.type == HostType.COLAB:
        tunnel = host.env_vars.get("tunnel_type", "cloudflared")
        print(f"  Tunnel: {tunnel}")
    if host.vast_instance_id:
        print(f"  Vast.ai ID: {host.vast_instance_id}")
        print(f"  Vast Status: {host.vast_status}")


def cmd_ssh(args: List[str]) -> None:
    """SSH into a host."""
    from ..core.models import HostType

    if not args:
        print("Usage: train host ssh <name>")
        sys.exit(1)

    name = args[0]
    hosts = load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    host = hosts[name]
    print(f"Connecting to {host.display_name}...")

    if host.type == HostType.COLAB:
        tunnel_type = host.env_vars.get("tunnel_type", "cloudflared")
        if tunnel_type == "cloudflared":
            # Use cloudflared access ssh
            proxy_command = host.env_vars.get("proxy_command", "").strip()
            if not proxy_command:
                cloudflared_bin = host.env_vars.get("cloudflared_bin", "cloudflared")
                cloudflared_hostname = host.env_vars.get("cloudflared_hostname", host.hostname)
                proxy_command = f"{cloudflared_bin} access ssh --hostname {cloudflared_hostname}"
            ssh_user = host.username or "root"
            ssh_cmd = f"ssh -o ProxyCommand='{proxy_command}' {ssh_user}@{host.hostname}"
        else:
            # ngrok - standard SSH with port
            ssh_cmd = f"ssh -p {host.port} {host.username}@{host.hostname}"
        os.system(ssh_cmd)
    else:
        from ..services.ssh import SSHClient
        ssh = SSHClient.from_host(host)
        exit_code = ssh.connect_interactive()
        if exit_code != 0:
            sys.exit(exit_code)


def cmd_test(args: List[str]) -> None:
    """Test connection to a host."""
    if not args:
        print("Usage: train host check <name>")
        sys.exit(1)

    name = args[0]
    hosts = load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    host = hosts[name]
    print(f"Testing connection to {host.display_name}...")

    from ..services.ssh import SSHClient
    ssh = SSHClient.from_host(host)

    if ssh.test_connection():
        print("Connection successful!")
    else:
        print("Connection failed.")
        sys.exit(1)


def cmd_rm(args: List[str]) -> None:
    """Remove a host."""
    if not args:
        print("Usage: train host remove <name>")
        sys.exit(1)

    name = args[0]
    hosts = load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    confirm = prompt_input(f"Remove host '{name}'? (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    del hosts[name]
    save_hosts(hosts)
    print(f"Host removed: {name}")


def main(args: List[str]) -> Optional[str]:
    """Main entry point for host command."""
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "add": cmd_add,
        "edit": cmd_edit,
        "show": cmd_show,
        "ssh": cmd_ssh,
        "files": cmd_browse,
        "check": cmd_test,
        "remove": cmd_rm,
    }

    try:
        handler = dispatch_subcommand(subcommand, commands=commands)
    except KeyError:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    handler(subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Host management"
    cd["short_desc"] = "Manage SSH hosts"
