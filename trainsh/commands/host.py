# tmux-trainsh host command
# Host management

import sys
import os
from typing import Optional, List

from ..cli_utils import prompt_input

usage = '''[subcommand] [args...]

Subcommands:
  list             - List configured hosts
  add              - Add a new host
  show <name>      - Show host details
  ssh <name>       - SSH into a host
  browse <name>    - Browse files on a host
  rm <name>        - Remove a host
  test <name>      - Test connection to a host

Host types:
  - SSH            Standard SSH host
  - Colab          Google Colab notebook (via cloudflared/ngrok)

For Vast.ai instances, use: train vast

Hosts are stored in: ~/.config/tmux-trainsh/hosts.toml
'''


def load_hosts() -> dict:
    """Load hosts from configuration."""
    from ..constants import HOSTS_FILE
    import tomllib

    if not HOSTS_FILE.exists():
        return {}

    with open(HOSTS_FILE, "rb") as f:
        data = tomllib.load(f)

    hosts = {}
    for host_data in data.get("hosts", []):
        from ..core.models import Host
        host = Host.from_dict(host_data)
        hosts[host.name or host.id] = host

    return hosts


def _host_to_toml(host) -> str:
    """Convert a host to TOML table format."""
    lines = ["[[hosts]]"]
    d = host.to_dict()
    for key, value in d.items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f'{key} = {"true" if value else "false"}')
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, (int, float)):
            lines.append(f'{key} = {value}')
    return "\n".join(lines)


def save_hosts(hosts: dict) -> None:
    """Save hosts to configuration."""
    from ..constants import HOSTS_FILE, CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    toml_lines = []
    for host in hosts.values():
        toml_lines.append(_host_to_toml(host))
        toml_lines.append("")

    with open(HOSTS_FILE, "w") as f:
        f.write("\n".join(toml_lines))


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


def cmd_add(args: List[str]) -> None:
    """Add a new host interactively."""
    from ..core.models import Host, HostType, AuthMethod

    print("Add new host")
    print("-" * 40)

    name = prompt_input("Host name: ")
    if name is None:
        return
    if not name:
        print("Cancelled - name is required.")
        return

    print("\nHost type:")
    print("  1. SSH (standard)")
    print("  2. Google Colab (via cloudflared)")
    print("  3. Google Colab (via ngrok)")
    type_choice = prompt_input("Choice [1]: ", default="1")
    if type_choice is None:
        return

    if type_choice == "2":
        # Colab via cloudflared
        print("\nIn your Colab notebook, run:")
        print("  !pip install colab-ssh")
        print("  from colab_ssh import launch_ssh_cloudflared")
        print("  launch_ssh_cloudflared(password='your_password')")
        print("")
        hostname = prompt_input("Cloudflared hostname (e.g., xxx.trycloudflare.com): ")
        if hostname is None:
            return
        if not hostname:
            print("Cancelled - hostname is required.")
            return

        host = Host(
            name=name,
            type=HostType.COLAB,
            hostname=hostname,
            port=22,
            username="root",
            auth_method=AuthMethod.PASSWORD,
            env_vars={"tunnel_type": "cloudflared"},
        )
        print("\nNote: Use password authentication when connecting.")

    elif type_choice == "3":
        # Colab via ngrok
        print("\nIn your Colab notebook, run:")
        print("  !pip install colab-ssh")
        print("  from colab_ssh import launch_ssh")
        print("  launch_ssh(ngrokToken='YOUR_NGROK_TOKEN', password='your_password')")
        print("")
        hostname = prompt_input("ngrok hostname (e.g., x.tcp.ngrok.io): ")
        if hostname is None:
            return
        port_str = prompt_input("ngrok port: ")
        if port_str is None:
            return
        if not hostname or not port_str:
            print("Cancelled - hostname and port are required.")
            return

        host = Host(
            name=name,
            type=HostType.COLAB,
            hostname=hostname,
            port=int(port_str),
            username="root",
            auth_method=AuthMethod.PASSWORD,
            env_vars={"tunnel_type": "ngrok"},
        )
        print("\nNote: Use password authentication when connecting.")

    else:
        # Standard SSH
        hostname = prompt_input("Hostname/IP: ")
        if hostname is None:
            return
        if not hostname:
            print("Cancelled - hostname is required.")
            return

        port_str = prompt_input("Port [22]: ", default="22")
        if port_str is None:
            return
        port = int(port_str) if port_str else 22

        username = prompt_input("Username [root]: ", default="root")
        if username is None:
            return

        print("\nAuth method:")
        print("  1. SSH Key (default)")
        print("  2. SSH Agent")
        print("  3. Password")
        auth_choice = prompt_input("Choice [1]: ", default="1")
        if auth_choice is None:
            return

        auth_method = {
            "1": AuthMethod.KEY,
            "2": AuthMethod.AGENT,
            "3": AuthMethod.PASSWORD,
        }.get(auth_choice, AuthMethod.KEY)

        ssh_key_path = None
        if auth_method == AuthMethod.KEY:
            default_key = "~/.ssh/id_rsa"
            ssh_key_path = prompt_input(f"SSH key path [{default_key}]: ", default=default_key)
            if ssh_key_path is None:
                return

        host = Host(
            name=name,
            type=HostType.SSH,
            hostname=hostname,
            port=port,
            username=username,
            auth_method=auth_method,
            ssh_key_path=ssh_key_path,
        )

    # Save
    hosts = load_hosts()
    hosts[name] = host
    save_hosts(hosts)

    print(f"\nAdded host: {name}")
    if host.type == HostType.COLAB:
        print("Use 'train host ssh' to connect.")
    else:
        print(f"SSH command: ssh -p {host.port} {host.username}@{host.hostname}")


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
            ssh_cmd = f"ssh -o ProxyCommand='cloudflared access ssh --hostname {host.hostname}' root@{host.hostname}"
        else:
            # ngrok - standard SSH with port
            ssh_cmd = f"ssh -p {host.port} {host.username}@{host.hostname}"
        os.system(ssh_cmd)
    else:
        from ..services.ssh import SSHClient
        ssh = SSHClient.from_host(host)
        ssh_cmd = ssh.get_ssh_command()
        os.system(ssh_cmd)


def cmd_test(args: List[str]) -> None:
    """Test connection to a host."""
    if not args:
        print("Usage: train host test <name>")
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
        print("Usage: train host rm <name>")
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


def cmd_browse(args: List[str]) -> None:
    """Browse files on a remote host."""
    if not args:
        print("Usage: train host browse <name> [path]")
        sys.exit(1)

    name = args[0]
    initial_path = args[1] if len(args) > 1 else "~"

    hosts = load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    host = hosts[name]
    print(f"Connecting to {host.display_name}...")

    from ..services.ssh import SSHClient
    from ..services.sftp_browser import RemoteFileBrowser

    ssh = SSHClient.from_host(host)

    # Test connection first
    if not ssh.test_connection():
        print("Connection failed.")
        sys.exit(1)

    browser = RemoteFileBrowser(ssh)

    # Interactive file browser loop
    print(f"\nFile Browser: {host.display_name}")
    print("Commands: Enter=open  ..=up  q=quit  /=search  h=toggle hidden")
    print("-" * 60)

    current_path = initial_path
    search_query = ""
    show_hidden = True

    while True:
        entries = browser.navigate(current_path)

        # Apply filters
        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]
        if search_query:
            entries = [e for e in entries if search_query.lower() in e.name.lower()]

        # Display current path
        print(f"\n{current_path}")
        print("-" * 40)

        # Display entries
        if not entries:
            print("  (empty)")
        else:
            for i, entry in enumerate(entries):
                icon = entry.icon
                size = entry.display_size
                print(f"  {i:3}. {icon} {entry.name:<30} {size:>10}")

        print("-" * 40)

        # Get user input
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not cmd:
            continue
        elif cmd == "q":
            break
        elif cmd == "..":
            # Go up
            if current_path not in ("/", "~"):
                current_path = "/".join(current_path.rstrip("/").split("/")[:-1]) or "/"
        elif cmd == "~":
            current_path = browser.get_home_directory()
        elif cmd == "h":
            show_hidden = not show_hidden
            print(f"Hidden files: {'shown' if show_hidden else 'hidden'}")
        elif cmd.startswith("/"):
            search_query = cmd[1:]
            print(f"Search: {search_query}" if search_query else "Search cleared")
        elif cmd.isdigit():
            idx = int(cmd)
            if 0 <= idx < len(entries):
                entry = entries[idx]
                if entry.is_dir:
                    current_path = entry.path
                else:
                    print(f"\nFile: {entry.path}")
                    print(f"Size: {entry.display_size}")
                    print(f"Permissions: {entry.permissions}")

                    # Ask what to do
                    action = input("Action: (c)opy path, (v)iew head, (b)ack: ").strip().lower()
                    if action == "c":
                        print(f"Path: {entry.path}")
                        try:
                            import subprocess
                            subprocess.run(["pbcopy"], input=entry.path.encode(), check=True)
                            print("Copied to clipboard!")
                        except:
                            pass
                    elif action == "v":
                        content = browser.read_file_head(entry.path, lines=30)
                        print("-" * 40)
                        print(content)
                        print("-" * 40)
            else:
                print(f"Invalid index: {idx}")
        elif cmd.startswith("cd "):
            new_path = cmd[3:].strip()
            if new_path:
                if browser.path_exists(new_path):
                    current_path = new_path
                else:
                    print(f"Path not found: {new_path}")
        else:
            print("Unknown command. Use: q, .., ~, h, /, or number to select")


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
        "show": cmd_show,
        "ssh": cmd_ssh,
        "browse": cmd_browse,
        "test": cmd_test,
        "rm": cmd_rm,
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
    cd["help_text"] = "Host management"
    cd["short_desc"] = "Manage SSH hosts"
