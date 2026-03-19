# tmux-trainsh host command
# Host management

import sys
import os
from typing import Optional, List
import re

from ..cli_utils import SubcommandSpec, dispatch_subcommand, prompt_input
from .help_catalog import render_command_help, render_top_level_help
from .remote_run import parse_remote_run_args, run_remote_command
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
    SubcommandSpec("run", "Run one remote shell command using the stored connection settings."),
    SubcommandSpec("files", "Browse remote files over SFTP."),
    SubcommandSpec("check", "Check whether a host is reachable."),
    SubcommandSpec("remove", "Delete a stored host definition or destroy a Vast.ai instance."),
)

usage = render_command_help("host")


AUTO_DISCOVERED_VAST_ENV = "_auto_discovered_vast"


def _load_configured_hosts() -> dict:
    """Load hosts stored on disk."""
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


def _sanitize_vast_host_name(value: str) -> str:
    """Normalize a Vast label into a CLI-friendly host alias."""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower())
    return normalized.strip("-.")


def _pick_vast_host_alias(instance, configured_hosts: dict, auto_hosts: dict) -> str:
    """Choose a stable alias for one Vast instance."""
    candidates = []
    raw_label = str(getattr(instance, "label", "") or "").strip()
    label_alias = _sanitize_vast_host_name(raw_label)
    if label_alias:
        candidates.append(label_alias)
        candidates.append(f"{label_alias}-{instance.id}")
    candidates.append(f"vast-{instance.id}")

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if candidate not in configured_hosts and candidate not in auto_hosts:
            return candidate
    return f"vast-{instance.id}"


def _build_vast_host(instance, name: str):
    """Convert a Vast instance into a temporary Host entry."""
    from ..services.host_resolver import build_host_from_vast_instance

    return build_host_from_vast_instance(instance, name=name, auto_discovered=True)


def _load_auto_vast_hosts(configured_hosts: dict) -> dict:
    """Load temporary host entries from current Vast.ai instances."""
    from ..services.vast_api import get_vast_client

    try:
        client = get_vast_client()
        instances = client.list_instances()
    except Exception:
        return {}

    auto_hosts = {}
    for instance in instances:
        alias = _pick_vast_host_alias(instance, configured_hosts, auto_hosts)
        auto_hosts[alias] = _build_vast_host(instance, alias)
    return auto_hosts


def load_hosts(include_auto_vast: bool = True) -> dict:
    """Load stored hosts plus auto-discovered Vast.ai instances."""
    hosts = _load_configured_hosts()
    if not include_auto_vast:
        return hosts
    hosts.update(_load_auto_vast_hosts(hosts))
    return hosts


def _is_auto_discovered_vast_host(host) -> bool:
    """Whether a host entry came from live Vast discovery."""
    return bool((host.env_vars or {}).get(AUTO_DISCOVERED_VAST_ENV))


def _host_location(host) -> str:
    """Render the best available endpoint for list/show output."""
    if host.hostname:
        user_part = f"{host.username}@" if host.username else ""
        return f"{user_part}{host.hostname}:{host.port}"
    if host.vast_instance_id:
        return f"vast:{host.vast_instance_id}"
    return "(hostname unavailable)"


def _host_to_dict(host) -> dict:
    """Convert a host to a filtered dict (no None values)."""
    return {k: v for k, v in host.to_dict().items() if v is not None}


def save_hosts(hosts: dict) -> None:
    """Save hosts to configuration."""
    from ..constants import HOSTS_FILE, CONFIG_DIR
    import yaml

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    persisted_hosts = [
        _host_to_dict(host)
        for host in hosts.values()
        if not _is_auto_discovered_vast_host(host)
    ]
    data = {"hosts": persisted_hosts}

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

    auto_vast_count = 0
    for name, host in hosts.items():
        status = ""
        if host.type == HostType.VASTAI and host.vast_instance_id:
            auto_vast_count += int(_is_auto_discovered_vast_host(host))
            status_parts = [f"Vast.ai #{host.vast_instance_id}"]
            if host.vast_status:
                status_parts.append(str(host.vast_status))
            if _is_auto_discovered_vast_host(host):
                status_parts.append("auto")
            status = f" [{' / '.join(status_parts)}]"
        elif host.type == HostType.COLAB:
            tunnel = host.env_vars.get("tunnel_type", "cloudflared")
            status = f" [Colab/{tunnel}]"
        print(f"  {name:<20} {_host_location(host)}{status}")

    print("-" * 60)
    print(f"Total: {len(hosts)} hosts")
    if auto_vast_count:
        print(f"Auto-discovered Vast.ai hosts: {auto_vast_count}")


def cmd_show(args: List[str]) -> None:
    """Show host details."""
    from ..core.models import HostType
    from ..core.secrets import get_secrets_manager
    from ..services.secret_materialize import resolve_resource_secret_name

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
    print(f"  Hostname: {host.hostname or '(not available until instance is running)'}")
    print(f"  Port: {host.port}")
    print(f"  Username: {host.username}")
    print(f"  Auth: {host.auth_method.value}")
    if _is_auto_discovered_vast_host(host):
        print("  Auto-discovered: yes")
    if host.ssh_key_path:
        print(f"  SSH Key: {host.ssh_key_path}")
    secrets = get_secrets_manager()
    ssh_key_secret = resolve_resource_secret_name(host.name or name, host.env_vars.get("ssh_key_secret"), "SSH_PRIVATE_KEY")
    ssh_password_secret = resolve_resource_secret_name(host.name or name, host.env_vars.get("ssh_password_secret"), "SSH_PASSWORD")
    if secrets.exists(ssh_key_secret):
        print("  SSH Key: managed by train secrets")
    if secrets.exists(ssh_password_secret):
        print("  SSH Password: managed by train secrets")
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
        try:
            ssh = SSHClient.from_host(host)
        except Exception as exc:
            print(f"Connection setup failed: {exc}")
            sys.exit(1)
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
    try:
        ssh = SSHClient.from_host(host)
    except Exception as exc:
        print(f"Connection setup failed: {exc}")
        sys.exit(1)

    if ssh.test_connection():
        print("Connection successful!")
    else:
        print("Connection failed.")
        sys.exit(1)


def cmd_run(args: List[str]) -> None:
    """Run one command on a stored host."""
    name, command = parse_remote_run_args(args, usage="train host run <name> -- <command>")
    hosts = load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    run_remote_command(hosts[name], command, label=name)


def cmd_rm(args: List[str]) -> None:
    """Remove a host."""
    if not args:
        print("Usage: train host remove <name>")
        sys.exit(1)

    name = args[0]
    hosts = load_hosts(include_auto_vast=False)
    target_host = hosts.get(name)

    if target_host is None:
        all_hosts = load_hosts()
        target_host = all_hosts.get(name)
        if target_host is None:
            print(f"Host not found: {name}")
            sys.exit(1)

    confirm = prompt_input(f"Remove host '{name}'? (y/N): ")
    if confirm is None or confirm.lower() != "y":
        print("Cancelled.")
        return

    if target_host.vast_instance_id:
        from ..services.vast_api import get_vast_client

        client = get_vast_client()
        client.rm_instance(int(target_host.vast_instance_id))
        if name in hosts:
            del hosts[name]
            save_hosts(hosts)
        print(f"Vast.ai instance removed: {target_host.vast_instance_id}")
        return

    del hosts[name]
    save_hosts(hosts)
    print(f"Host removed: {name}")


def main(args: List[str]) -> Optional[str]:
    """Main entry point for host command."""
    if not args:
        print(usage)
        return None
    if args[0] in ("-h", "--help", "help"):
        print(render_top_level_help())
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "add": cmd_add,
        "edit": cmd_edit,
        "show": cmd_show,
        "ssh": cmd_ssh,
        "run": cmd_run,
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
