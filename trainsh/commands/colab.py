# tmux-trainsh colab command
# Google Colab integration

import getpass
import os
import shlex
import shutil
import yaml
import sys
from typing import Optional, List

from ..cli_utils import SubcommandSpec, dispatch_subcommand, prompt_input
from .help_catalog import render_command_help
from .help_cmd import reject_subcommand_help
from ..constants import CONFIG_DIR
from ..core.secrets import get_secrets_manager
from ..services.secret_materialize import materialize_secret_file, suggest_secret_name

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


def _password_secret_name(connection_name: str) -> str:
    return suggest_secret_name(connection_name, "SSH_PASSWORD")


def _store_password_secret(connection_name: str) -> Optional[str]:
    password = getpass.getpass("SSH password: ").strip()
    if not password:
        print("Cancelled - password is required.")
        return None

    secret_name = _password_secret_name(connection_name)
    try:
        get_secrets_manager().set(secret_name, password)
    except Exception as exc:
        print(f"Failed to store SSH password in TrainVault: {exc}")
        return None

    print("Stored SSH password in TrainVault.")
    return secret_name


def _select_connection(connections: list, args: List[str]) -> dict:
    if len(connections) == 1:
        return connections[0]
    if args:
        conn = next((c for c in connections if c.get("name") == args[0]), None)
        if not conn:
            print(f"Connection not found: {args[0]}")
            sys.exit(1)
        return conn

    print("Available connections:")
    for i, c in enumerate(connections, 1):
        print(f"  {i}. {c.get('name')}")
    choice = prompt_input("Select connection: ")
    if choice is None:
        raise KeyboardInterrupt
    try:
        return connections[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        sys.exit(1)


def _ssh_auth_prefix(conn: dict) -> str:
    if conn.get("password"):
        print(
            "Legacy plaintext Colab password is no longer accepted. "
            "Re-run 'train colab connect' to store it in TrainVault."
        )
        sys.exit(1)

    password_secret = str(conn.get("password_secret") or "").strip()
    if not password_secret:
        return ""

    try:
        password_file = materialize_secret_file(password_secret, suffix=".pass")
    except Exception as exc:
        print(f"Failed to resolve Colab SSH password from TrainVault: {exc}")
        sys.exit(1)

    if not password_file:
        print(f"Colab SSH password secret is missing: {password_secret}")
        sys.exit(1)

    if not shutil.which("sshpass"):
        print(
            "sshpass is required for TrainVault-managed Colab password SSH. "
            "Install sshpass or recreate the Colab connection with SSH key authentication."
        )
        sys.exit(1)

    return f"sshpass -f {shlex.quote(password_file)} "


def _build_ssh_command(conn: dict, remote_command: Optional[str] = None) -> str:
    tunnel_type = conn.get("tunnel_type")
    config = conn.get("config", {})
    auth_prefix = _ssh_auth_prefix(conn)

    if tunnel_type == "cloudflared":
        hostname = str(config.get("hostname") or "").strip()
        if not hostname:
            print("Error: Missing tunnel hostname.")
            sys.exit(1)
        proxy_command = f"ProxyCommand=cloudflared access ssh --hostname {shlex.quote(hostname)}"
        ssh_cmd = f"{auth_prefix}ssh -o {shlex.quote(proxy_command)} root@{shlex.quote(hostname)}"
    else:
        hostname = str(config.get("hostname") or "").strip()
        port = str(config.get("port", 22)).strip() or "22"
        if not hostname:
            print("Error: Missing ngrok hostname.")
            sys.exit(1)
        ssh_cmd = f"{auth_prefix}ssh -p {shlex.quote(port)} root@{shlex.quote(hostname)}"

    if remote_command is not None:
        ssh_cmd = f"{ssh_cmd} {shlex.quote(remote_command)}"

    return ssh_cmd


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
        tunnel_label = "secure tunnel" if tunnel_type == "cloudflared" else tunnel_type
        print(f"  {name:<20} via {tunnel_label}")

    print("-" * 50)


def cmd_connect(args: List[str]) -> None:
    """Add a new Colab connection."""
    print("Connect to Google Colab")
    print("-" * 40)
    print("\nIn your Colab notebook, run:")
    print("  !pip install colab-ssh")
    print("  Start an SSH tunnel, then copy the generated hostname.")
    print("\nThen copy the connection info here.\n")

    name = prompt_input("Connection name: ")
    if name is None:
        return
    if not name:
        print("Cancelled.")
        return

    print("\nTunnel type:")
    print("  1. Secure tunnel (recommended)")
    print("  2. ngrok")
    tunnel_choice = prompt_input("Choice [1]: ", default="1")
    if tunnel_choice is None:
        return
    tunnel_type = "cloudflared" if tunnel_choice == "1" else "ngrok"

    if tunnel_type == "cloudflared":
        hostname = prompt_input("Tunnel hostname: ")
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

    store_password = prompt_input("Store SSH password in TrainVault now? (Y/n): ", default="Y")
    if store_password is None:
        return
    if store_password.strip().lower() in ("n", "no"):
        print("Cancelled - Colab password authentication must use TrainVault.")
        return
    password_secret = _store_password_secret(name)
    if not password_secret:
        return

    # Save connection
    data = _load_colab_data()

    connections = data.get("connections", [])
    connections.append({
        "name": name,
        "tunnel_type": tunnel_type,
        "config": config,
        "password_secret": password_secret,
    })

    data["connections"] = connections

    _save_colab_data(data)

    print(f"\nAdded Colab connection: {name}")
    print("Use 'train colab ssh' to connect.")


def cmd_ssh(args: List[str]) -> None:
    """SSH into Colab."""
    data = _load_colab_data()

    connections = data.get("connections", [])

    if not connections:
        print("No Colab connections configured.")
        print("Use 'train colab connect' first.")
        sys.exit(1)

    try:
        conn = _select_connection(connections, args)
    except KeyboardInterrupt:
        return

    tunnel_type = conn.get("tunnel_type")
    config = conn.get("config", {})

    if tunnel_type == "cloudflared":
        hostname = config.get("hostname")
        print("Connecting to Colab via secure tunnel...")
        print(f"Hostname: {hostname}")
    else:
        print("Connecting to Colab via ngrok...")
    os.system(_build_ssh_command(conn))


def cmd_run(args: List[str]) -> None:
    """Run a command on Colab."""
    if not args:
        print("Usage: train colab run <command>")
        sys.exit(1)

    command = " ".join(args)

    data = _load_colab_data()

    connections = data.get("connections", [])
    if not connections:
        print("No Colab connections configured.")
        sys.exit(1)

    conn = connections[0]  # Use first connection
    print(f"Running on Colab: {command}")
    os.system(_build_ssh_command(conn, command))


def main(args: List[str]) -> Optional[str]:
    """Main entry point for colab command."""
    if not args:
        print(usage)
        return None
    if args[0] in ("-h", "--help", "help"):
        reject_subcommand_help()

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
