# kitten-trainsh colab command
# Google Colab integration

import sys
from typing import Optional, List

usage = '''[subcommand] [args...]

Subcommands:
  list, ls         - List connected Colab notebooks
  connect          - Connect to a Colab runtime
  run <cmd>        - Run command on Colab
  ssh              - SSH into Colab (requires ngrok/cloudflared)

Note: Google Colab integration requires:
  1. A running Colab notebook with SSH enabled
  2. ngrok or cloudflared for tunneling
  3. The tunnel URL/connection info

Example Colab setup code:
  !pip install colab_ssh
  from colab_ssh import launch_ssh_cloudflared
  launch_ssh_cloudflared(password="your_password")
'''


def cmd_list(args: List[str]) -> None:
    """List connected Colab instances."""
    from ..constants import CONFIG_DIR
    import yaml

    colab_file = CONFIG_DIR / "colab.yaml"

    if not colab_file.exists():
        print("No Colab connections configured.")
        print("Use 'kitty +kitten trainsh colab connect' to add one.")
        return

    with open(colab_file) as f:
        data = yaml.safe_load(f) or {}

    connections = data.get("connections", [])

    if not connections:
        print("No Colab connections configured.")
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
    from ..constants import CONFIG_DIR
    import yaml

    print("Connect to Google Colab")
    print("-" * 40)
    print("\nIn your Colab notebook, run:")
    print("  !pip install colab-ssh")
    print("  from colab_ssh import launch_ssh_cloudflared")
    print("  launch_ssh_cloudflared(password='your_password')")
    print("\nThen copy the connection info here.\n")

    name = input("Connection name: ").strip()
    if not name:
        print("Cancelled.")
        return

    print("\nTunnel type:")
    print("  1. Cloudflared (recommended)")
    print("  2. ngrok")
    tunnel_choice = input("Choice [1]: ").strip() or "1"
    tunnel_type = "cloudflared" if tunnel_choice == "1" else "ngrok"

    if tunnel_type == "cloudflared":
        hostname = input("Cloudflared hostname (e.g., xxx.trycloudflare.com): ").strip()
        if not hostname:
            print("Cancelled.")
            return
        config = {"hostname": hostname}
    else:
        hostname = input("ngrok hostname (e.g., x.tcp.ngrok.io): ").strip()
        port = input("ngrok port: ").strip()
        if not hostname or not port:
            print("Cancelled.")
            return
        config = {"hostname": hostname, "port": int(port)}

    password = input("SSH password: ").strip()

    # Save connection
    colab_file = CONFIG_DIR / "colab.yaml"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {}
    if colab_file.exists():
        with open(colab_file) as f:
            data = yaml.safe_load(f) or {}

    connections = data.get("connections", [])
    connections.append({
        "name": name,
        "tunnel_type": tunnel_type,
        "config": config,
        "password": password,  # Note: stored in plain text - consider using secrets
    })

    data["connections"] = connections

    with open(colab_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False)

    print(f"\nAdded Colab connection: {name}")
    print("Use 'kitty +kitten trainsh colab ssh' to connect.")


def cmd_ssh(args: List[str]) -> None:
    """SSH into Colab."""
    import os
    from ..constants import CONFIG_DIR
    import yaml

    colab_file = CONFIG_DIR / "colab.yaml"

    if not colab_file.exists():
        print("No Colab connections configured.")
        print("Use 'kitty +kitten trainsh colab connect' first.")
        sys.exit(1)

    with open(colab_file) as f:
        data = yaml.safe_load(f) or {}

    connections = data.get("connections", [])

    if not connections:
        print("No Colab connections configured.")
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
        choice = input("Select connection: ").strip()
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
        print("Usage: kitty +kitten trainsh colab run <command>")
        sys.exit(1)

    from ..constants import CONFIG_DIR
    import yaml
    import subprocess

    command = " ".join(args)

    colab_file = CONFIG_DIR / "colab.yaml"

    if not colab_file.exists():
        print("No Colab connections configured.")
        sys.exit(1)

    with open(colab_file) as f:
        data = yaml.safe_load(f) or {}

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
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "ls": cmd_list,
        "connect": cmd_connect,
        "ssh": cmd_ssh,
        "run": cmd_run,
    }

    if subcommand not in commands:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    commands[subcommand](subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Google Colab integration"
    cd["short_desc"] = "Connect and run commands on Google Colab"
