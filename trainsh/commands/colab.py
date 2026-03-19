# tmux-trainsh colab command
# Google Colab integration

import yaml
import sys
from typing import Optional, List

from ..cli_utils import SubcommandSpec, dispatch_subcommand, prompt_input
from .help_catalog import render_command_help, render_top_level_help
from ..constants import CONFIG_DIR

SUBCOMMAND_SPECS = (
    SubcommandSpec("list", "List saved Colab tunnel definitions."),
    SubcommandSpec("connect", "Add a Colab tunnel definition."),
    SubcommandSpec("ssh", "Open SSH to one saved Colab runtime."),
    SubcommandSpec("run", "Run one remote shell command over SSH."),
)

usage = render_command_help("colab")

COLAB_FILE = CONFIG_DIR / "colab.yaml"


def _load_colab_data() -> dict:
    if not COLAB_FILE.exists():
        return {}
    try:
        with open(COLAB_FILE, "r") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError:
        print(f"Error: Invalid YAML in {COLAB_FILE}")
        raise SystemExit(1)


def _save_colab_data(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(COLAB_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def cmd_list(args: List[str]) -> None:
    """List connected Colab instances."""
    data = _load_colab_data()

    connections = data.get("connections", [])

    if not connections:
        print("No Colab connections configured.")
        print("Use 'train colab connect' to add one.")
        return

    print("Colab connections:")
    print("-" * 50)

    for conn in connections:
        name = conn.get("name", "unnamed")
        tunnel_type = conn.get("tunnel_type", "unknown")
        print(f"  {name:<20} via {tunnel_type}")

    print("-" * 50)


def cmd_connect(args: List[str]) -> None:
    """Add a new Colab connection."""
    print("Connect to Google Colab")
    print("-" * 40)
    print("\nIn your Colab notebook, run:")
    print("  !pip install colab-ssh")
    print("  from colab_ssh import launch_ssh_cloudflared")
    print("  launch_ssh_cloudflared(password='your_password')")
    print("\nThen copy the connection info here.\n")

    name = prompt_input("Connection name: ")
    if name is None:
        return
    if not name:
        print("Cancelled.")
        return

    print("\nTunnel type:")
    print("  1. Cloudflared (recommended)")
    print("  2. ngrok")
    tunnel_choice = prompt_input("Choice [1]: ", default="1")
    if tunnel_choice is None:
        return
    tunnel_type = "cloudflared" if tunnel_choice == "1" else "ngrok"

    if tunnel_type == "cloudflared":
        hostname = prompt_input("Cloudflared hostname (e.g., xxx.trycloudflare.com): ")
        if hostname is None:
            return
        if not hostname:
            print("Cancelled.")
            return
        config = {"hostname": hostname}
    else:
        hostname = prompt_input("ngrok hostname (e.g., x.tcp.ngrok.io): ")
        if hostname is None:
            return
        port = prompt_input("ngrok port: ")
        if port is None:
            return
        if not hostname or not port:
            print("Cancelled.")
            return
        config = {"hostname": hostname, "port": int(port)}

    password = prompt_input("SSH password: ")
    if password is None:
        return

    # Save connection
    data = _load_colab_data()

    connections = data.get("connections", [])
    connections.append({
        "name": name,
        "tunnel_type": tunnel_type,
        "config": config,
        "password": password,  # Note: stored in plain text - consider using secrets
    })

    data["connections"] = connections

    _save_colab_data(data)

    print(f"\nAdded Colab connection: {name}")
    print("Use 'train colab ssh' to connect.")


def cmd_ssh(args: List[str]) -> None:
    """SSH into Colab."""
    import os
    data = _load_colab_data()

    connections = data.get("connections", [])

    if not connections:
        print("No Colab connections configured.")
        print("Use 'train colab connect' first.")
        sys.exit(1)

    # Select connection
    if len(connections) == 1:
        conn = connections[0]
    elif args:
        conn = next((c for c in connections if c.get("name") == args[0]), None)
        if not conn:
            print(f"Connection not found: {args[0]}")
            sys.exit(1)
    else:
        print("Available connections:")
        for i, c in enumerate(connections, 1):
            print(f"  {i}. {c.get('name')}")
        choice = prompt_input("Select connection: ")
        if choice is None:
            return
        try:
            conn = connections[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            sys.exit(1)

    tunnel_type = conn.get("tunnel_type")
    config = conn.get("config", {})

    if tunnel_type == "cloudflared":
        hostname = config.get("hostname")
        # cloudflared SSH command
        print(f"Connecting to Colab via cloudflared...")
        print(f"Hostname: {hostname}")
        os.system(f"ssh -o ProxyCommand='cloudflared access ssh --hostname {hostname}' root@{hostname}")
    else:
        hostname = config.get("hostname")
        port = config.get("port", 22)
        print(f"Connecting to Colab via ngrok...")
        os.system(f"ssh -p {port} root@{hostname}")


def cmd_run(args: List[str]) -> None:
    """Run a command on Colab."""
    if not args:
        print("Usage: train colab run <command>")
        sys.exit(1)

    import os
    import subprocess

    command = " ".join(args)

    data = _load_colab_data()

    connections = data.get("connections", [])
    if not connections:
        print("No Colab connections configured.")
        sys.exit(1)

    conn = connections[0]  # Use first connection
    tunnel_type = conn.get("tunnel_type")
    config = conn.get("config", {})

    if tunnel_type == "cloudflared":
        hostname = config.get("hostname")
        ssh_cmd = f"ssh -o ProxyCommand='cloudflared access ssh --hostname {hostname}' root@{hostname} '{command}'"
    else:
        hostname = config.get("hostname")
        port = config.get("port", 22)
        ssh_cmd = f"ssh -p {port} root@{hostname} '{command}'"

    print(f"Running on Colab: {command}")
    os.system(ssh_cmd)


def main(args: List[str]) -> Optional[str]:
    """Main entry point for colab command."""
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
        "connect": cmd_connect,
        "ssh": cmd_ssh,
        "run": cmd_run,
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
    cd["help_text"] = "Google Colab integration"
    cd["short_desc"] = "Connect and run commands on Google Colab"
