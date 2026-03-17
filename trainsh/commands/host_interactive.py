"""Interactive host workflows and helper prompts."""

from __future__ import annotations

import sys
from typing import List, Optional


def _host_module():
    from . import host as host_cmd

    return host_cmd


def _prompt_int(prompt: str, default: int) -> Optional[int]:
    host_cmd = _host_module()
    while True:
        raw = host_cmd.prompt_input(prompt, default=str(default))
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print("Please enter a valid integer.")


def _normalize_connection_candidates(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return []


def _render_connection_candidate_line(index: int, candidate) -> str:
    if isinstance(candidate, dict):
        candidate_type = str(candidate.get("type", "ssh")).strip().lower()
        if candidate_type == "cloudflared":
            cloudflared_hostname = candidate.get("hostname") or candidate.get("cloudflared_hostname", "")
            line = f"{index}. cloudflared://{cloudflared_hostname}"
            if candidate.get("cloudflared_bin"):
                line += f" (bin={candidate.get('cloudflared_bin')})"
            return line

        candidate_hostname = candidate.get("hostname", "")
        candidate_port = candidate.get("port", 22)
        line = f"{index}. ssh://{candidate_hostname}:{candidate_port}"
        if candidate.get("jump_host"):
            line += f" (jump={candidate.get('jump_host')})"
        if candidate.get("proxy_command"):
            line += " (proxy)"
        return line

    return f"{index}. {candidate}"


def _prompt_connection_candidates() -> Optional[list]:
    host_cmd = _host_module()
    candidates = []

    while True:
        add_candidate = host_cmd.prompt_input(
            "Add connection candidate? (y/N): ",
            default="N",
        )
        if add_candidate is None:
            return None
        if add_candidate.strip().lower() not in ("y", "yes"):
            break

        print("\nCandidate type:")
        print("  1. SSH")
        print("  2. Cloudflared Access")
        candidate_type = host_cmd.prompt_input("Choice [1]: ", default="1")
        if candidate_type is None:
            return None

        if candidate_type.strip() == "2":
            cloudflared_hostname = host_cmd.prompt_input(
                "Cloudflared hostname (e.g. ssh-access.example.com): ",
            )
            if cloudflared_hostname is None:
                return None
            cloudflared_hostname = cloudflared_hostname.strip()
            if not cloudflared_hostname:
                print("Skipped - cloudflared hostname is required.")
                continue

            cloudflared_bin = host_cmd.prompt_input(
                "cloudflared binary [cloudflared]: ",
                default="cloudflared",
            )
            if cloudflared_bin is None:
                return None
            cloudflared_bin = cloudflared_bin.strip() or "cloudflared"

            candidate = {
                "type": "cloudflared",
                "hostname": cloudflared_hostname,
            }
            if cloudflared_bin != "cloudflared":
                candidate["cloudflared_bin"] = cloudflared_bin
            candidates.append(candidate)
            print(f"Added candidate #{len(candidates)}: cloudflared://{cloudflared_hostname}")
            continue

        candidate_hostname = host_cmd.prompt_input("Candidate hostname/IP: ")
        if candidate_hostname is None:
            return None
        candidate_hostname = candidate_hostname.strip()
        if not candidate_hostname:
            print("Skipped - candidate hostname is required.")
            continue

        candidate_port = _prompt_int("Candidate port [22]: ", default=22)
        if candidate_port is None:
            return None

        candidate_jump = host_cmd.prompt_input(
            "Candidate jump host (optional): ",
            default="",
        )
        if candidate_jump is None:
            return None
        candidate_jump = candidate_jump.strip()

        candidate_proxy = host_cmd.prompt_input(
            "Candidate ProxyCommand (optional): ",
            default="",
        )
        if candidate_proxy is None:
            return None
        candidate_proxy = candidate_proxy.strip()

        candidate = {
            "type": "ssh",
            "hostname": candidate_hostname,
        }
        if candidate_port != 22:
            candidate["port"] = candidate_port
        if candidate_jump:
            candidate["jump_host"] = candidate_jump
        if candidate_proxy:
            candidate["proxy_command"] = candidate_proxy
        candidates.append(candidate)
        print(
            f"Added candidate #{len(candidates)}: "
            f"ssh://{candidate_hostname}:{candidate_port}"
        )

    return candidates


def cmd_add(args: List[str]) -> None:
    """Add a new host interactively."""
    del args
    host_cmd = _host_module()
    from ..core.models import AuthMethod, Host, HostType

    print("Add new host")
    print("-" * 40)

    name = host_cmd.prompt_input("Host name: ")
    if name is None:
        return
    if not name:
        print("Cancelled - name is required.")
        return

    print("\nHost type:")
    print("  1. SSH (standard)")
    print("  2. Google Colab (via cloudflared)")
    print("  3. Google Colab (via ngrok)")
    type_choice = host_cmd.prompt_input("Choice [1]: ", default="1")
    if type_choice is None:
        return

    if type_choice == "2":
        print("\nIn your Colab notebook, run:")
        print("  !pip install colab-ssh")
        print("  from colab_ssh import launch_ssh_cloudflared")
        print("  launch_ssh_cloudflared(password='your_password')")
        print("")
        hostname = host_cmd.prompt_input("Cloudflared hostname (e.g., xxx.trycloudflare.com): ")
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
        print("\nIn your Colab notebook, run:")
        print("  !pip install colab-ssh")
        print("  from colab_ssh import launch_ssh")
        print("  launch_ssh(ngrokToken='YOUR_NGROK_TOKEN', password='your_password')")
        print("")
        hostname = host_cmd.prompt_input("ngrok hostname (e.g., x.tcp.ngrok.io): ")
        if hostname is None:
            return
        port_str = host_cmd.prompt_input("ngrok port: ")
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
        hostname = host_cmd.prompt_input("Hostname/IP: ")
        if hostname is None:
            return
        if not hostname:
            print("Cancelled - hostname is required.")
            return

        port_str = host_cmd.prompt_input("Port [22]: ", default="22")
        if port_str is None:
            return
        port = int(port_str) if port_str else 22

        username = host_cmd.prompt_input("Username [root]: ", default="root")
        if username is None:
            return

        print("\nAuth method:")
        print("  1. SSH Key (default)")
        print("  2. SSH Agent")
        print("  3. Password")
        auth_choice = host_cmd.prompt_input("Choice [1]: ", default="1")
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
            ssh_key_path = host_cmd.prompt_input(f"SSH key path [{default_key}]: ", default=default_key)
            if ssh_key_path is None:
                return

        jump_host = host_cmd.prompt_input(
            "Jump host (optional, e.g. root@bastion.example.com): ",
            default="",
        )
        if jump_host is None:
            return
        jump_host = jump_host.strip() or None

        env_vars = {}

        use_cloudflared = host_cmd.prompt_input(
            "Use cloudflared Access tunnel? (y/N): ",
            default="N",
        )
        if use_cloudflared is None:
            return

        if use_cloudflared.strip().lower() in ("y", "yes"):
            cloudflared_hostname = host_cmd.prompt_input(
                f"Cloudflared hostname [{hostname}]: ",
                default=hostname,
            )
            if cloudflared_hostname is None:
                return
            cloudflared_hostname = cloudflared_hostname.strip()
            if not cloudflared_hostname:
                print("Cancelled - cloudflared hostname is required when enabled.")
                return

            cloudflared_bin = host_cmd.prompt_input(
                "cloudflared binary [cloudflared]: ",
                default="cloudflared",
            )
            if cloudflared_bin is None:
                return
            cloudflared_bin = cloudflared_bin.strip() or "cloudflared"

            env_vars["tunnel_type"] = "cloudflared"
            env_vars["cloudflared_hostname"] = cloudflared_hostname
            if cloudflared_bin != "cloudflared":
                env_vars["cloudflared_bin"] = cloudflared_bin

        proxy_command = host_cmd.prompt_input(
            "ProxyCommand override (optional, e.g. wstunnel/cloudflared ...): ",
            default="",
        )
        if proxy_command is None:
            return
        proxy_command = proxy_command.strip() or None

        if proxy_command:
            env_vars["proxy_command"] = proxy_command

        connection_candidates = _prompt_connection_candidates()
        if connection_candidates is None:
            return
        if connection_candidates:
            env_vars["connection_candidates"] = connection_candidates

        host = Host(
            name=name,
            type=HostType.SSH,
            hostname=hostname,
            port=port,
            username=username,
            auth_method=auth_method,
            ssh_key_path=ssh_key_path,
            jump_host=jump_host,
            env_vars=env_vars,
        )

    hosts = host_cmd.load_hosts()
    hosts[name] = host
    host_cmd.save_hosts(hosts)

    print(f"\nAdded host: {name}")
    if host.type == HostType.COLAB:
        print("Use 'train host ssh' to connect.")
    else:
        print(f"SSH command: ssh -p {host.port} {host.username}@{host.hostname}")


def cmd_edit(args: List[str]) -> None:
    """Edit an existing host interactively."""
    host_cmd = _host_module()
    from ..core.models import AuthMethod, HostType

    if not args:
        print("Usage: train host edit <name>")
        sys.exit(1)

    name = args[0]
    hosts = host_cmd.load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    host = hosts[name]
    print(f"Edit host: {host.display_name}")
    print("-" * 40)

    current_name = host.name or name
    new_name = host_cmd.prompt_input(f"Host name [{current_name}]: ", default=current_name)
    if new_name is None:
        return
    new_name = new_name.strip()
    if not new_name:
        print("Cancelled - name is required.")
        return
    if new_name != name and new_name in hosts:
        print(f"Host already exists: {new_name}")
        sys.exit(1)

    if host.type == HostType.SSH:
        hostname = host_cmd.prompt_input(f"Hostname/IP [{host.hostname}]: ", default=host.hostname)
        if hostname is None:
            return
        hostname = hostname.strip()
        if not hostname:
            print("Cancelled - hostname is required.")
            return

        port = _prompt_int(f"Port [{host.port}]: ", default=host.port)
        if port is None:
            return

        username_default = host.username or "root"
        username = host_cmd.prompt_input(f"Username [{username_default}]: ", default=username_default)
        if username is None:
            return
        username = username.strip() or username_default

        print("\nAuth method:")
        print("  1. SSH Key")
        print("  2. SSH Agent")
        print("  3. Password")
        auth_to_choice = {
            AuthMethod.KEY: "1",
            AuthMethod.AGENT: "2",
            AuthMethod.PASSWORD: "3",
        }
        auth_default = auth_to_choice.get(host.auth_method, "1")
        auth_choice = host_cmd.prompt_input(f"Choice [{auth_default}]: ", default=auth_default)
        if auth_choice is None:
            return
        auth_method = {
            "1": AuthMethod.KEY,
            "2": AuthMethod.AGENT,
            "3": AuthMethod.PASSWORD,
        }.get(auth_choice.strip(), host.auth_method)

        if auth_method == AuthMethod.KEY:
            key_default = host.ssh_key_path or "~/.ssh/id_rsa"
            ssh_key_path = host_cmd.prompt_input(f"SSH key path [{key_default}]: ", default=key_default)
            if ssh_key_path is None:
                return
            ssh_key_path = ssh_key_path.strip() or key_default
        else:
            ssh_key_path = None

        jump_host = host_cmd.prompt_input(
            f"Jump host [{host.jump_host or ''}]: ",
            default=host.jump_host or "",
        )
        if jump_host is None:
            return
        jump_host = jump_host.strip() or None

        env_vars = dict(host.env_vars or {})
        current_tunnel = str(env_vars.get("tunnel_type", "")).strip().lower()
        tunnel_default = "Y" if current_tunnel == "cloudflared" else "N"
        use_cloudflared = host_cmd.prompt_input(
            "Use cloudflared Access tunnel? (y/N): ",
            default=tunnel_default,
        )
        if use_cloudflared is None:
            return
        if use_cloudflared.strip().lower() in ("y", "yes"):
            cloudflared_hostname_default = str(env_vars.get("cloudflared_hostname", hostname)).strip() or hostname
            cloudflared_hostname = host_cmd.prompt_input(
                f"Cloudflared hostname [{cloudflared_hostname_default}]: ",
                default=cloudflared_hostname_default,
            )
            if cloudflared_hostname is None:
                return
            cloudflared_hostname = cloudflared_hostname.strip()
            if not cloudflared_hostname:
                print("Cancelled - cloudflared hostname is required when enabled.")
                return

            cloudflared_bin_default = str(env_vars.get("cloudflared_bin", "cloudflared")).strip() or "cloudflared"
            cloudflared_bin = host_cmd.prompt_input(
                f"cloudflared binary [{cloudflared_bin_default}]: ",
                default=cloudflared_bin_default,
            )
            if cloudflared_bin is None:
                return
            cloudflared_bin = cloudflared_bin.strip() or cloudflared_bin_default

            env_vars["tunnel_type"] = "cloudflared"
            env_vars["cloudflared_hostname"] = cloudflared_hostname
            if cloudflared_bin != "cloudflared":
                env_vars["cloudflared_bin"] = cloudflared_bin
            else:
                env_vars.pop("cloudflared_bin", None)
        else:
            env_vars.pop("tunnel_type", None)
            env_vars.pop("cloudflared_hostname", None)
            env_vars.pop("cloudflared_bin", None)

        proxy_default = str(env_vars.get("proxy_command", ""))
        proxy_command = host_cmd.prompt_input(
            "ProxyCommand override (optional): ",
            default=proxy_default,
        )
        if proxy_command is None:
            return
        proxy_command = proxy_command.strip()
        if proxy_command:
            env_vars["proxy_command"] = proxy_command
        else:
            env_vars.pop("proxy_command", None)

        existing_candidates = _normalize_connection_candidates(env_vars.get("connection_candidates", []))
        if existing_candidates:
            print("\nCurrent connection candidates:")
            for idx, candidate in enumerate(existing_candidates, start=1):
                print(f"  {_render_connection_candidate_line(idx, candidate)}")

        reconfigure_candidates = host_cmd.prompt_input(
            "Reconfigure connection candidates? (y/N): ",
            default="N",
        )
        if reconfigure_candidates is None:
            return
        if reconfigure_candidates.strip().lower() in ("y", "yes"):
            new_candidates = _prompt_connection_candidates()
            if new_candidates is None:
                return
            if new_candidates:
                env_vars["connection_candidates"] = new_candidates
            else:
                env_vars.pop("connection_candidates", None)

        host.hostname = hostname
        host.port = port
        host.username = username
        host.auth_method = auth_method
        host.ssh_key_path = ssh_key_path
        host.jump_host = jump_host
        host.env_vars = env_vars

    elif host.type == HostType.COLAB:
        hostname = host_cmd.prompt_input(f"Hostname [{host.hostname}]: ", default=host.hostname)
        if hostname is None:
            return
        hostname = hostname.strip()
        if not hostname:
            print("Cancelled - hostname is required.")
            return

        username_default = host.username or "root"
        username = host_cmd.prompt_input(f"Username [{username_default}]: ", default=username_default)
        if username is None:
            return
        username = username.strip() or username_default

        env_vars = dict(host.env_vars or {})
        current_tunnel = str(env_vars.get("tunnel_type", "cloudflared")).strip().lower()
        print("\nTunnel type:")
        print("  1. cloudflared")
        print("  2. ngrok")
        tunnel_default = "2" if current_tunnel == "ngrok" else "1"
        tunnel_choice = host_cmd.prompt_input(f"Choice [{tunnel_default}]: ", default=tunnel_default)
        if tunnel_choice is None:
            return

        if tunnel_choice.strip() == "2":
            port = _prompt_int(f"Port [{host.port}]: ", default=host.port)
            if port is None:
                return
            env_vars["tunnel_type"] = "ngrok"
            env_vars.pop("cloudflared_hostname", None)
            env_vars.pop("cloudflared_bin", None)
            env_vars.pop("proxy_command", None)
        else:
            port = 22
            env_vars["tunnel_type"] = "cloudflared"
            cloudflared_hostname_default = str(env_vars.get("cloudflared_hostname", hostname)).strip() or hostname
            cloudflared_hostname = host_cmd.prompt_input(
                f"Cloudflared hostname [{cloudflared_hostname_default}]: ",
                default=cloudflared_hostname_default,
            )
            if cloudflared_hostname is None:
                return
            cloudflared_hostname = cloudflared_hostname.strip()
            if not cloudflared_hostname:
                print("Cancelled - cloudflared hostname is required.")
                return
            env_vars["cloudflared_hostname"] = cloudflared_hostname

            cloudflared_bin_default = str(env_vars.get("cloudflared_bin", "cloudflared")).strip() or "cloudflared"
            cloudflared_bin = host_cmd.prompt_input(
                f"cloudflared binary [{cloudflared_bin_default}]: ",
                default=cloudflared_bin_default,
            )
            if cloudflared_bin is None:
                return
            cloudflared_bin = cloudflared_bin.strip() or cloudflared_bin_default
            if cloudflared_bin != "cloudflared":
                env_vars["cloudflared_bin"] = cloudflared_bin
            else:
                env_vars.pop("cloudflared_bin", None)

            proxy_default = str(env_vars.get("proxy_command", ""))
            proxy_command = host_cmd.prompt_input(
                "ProxyCommand override (optional): ",
                default=proxy_default,
            )
            if proxy_command is None:
                return
            proxy_command = proxy_command.strip()
            if proxy_command:
                env_vars["proxy_command"] = proxy_command
            else:
                env_vars.pop("proxy_command", None)

        host.hostname = hostname
        host.port = port
        host.username = username
        host.env_vars = env_vars
    elif host.type == HostType.VASTAI and host.vast_instance_id:
        from ..services.vast_api import get_vast_client

        new_alias = host_cmd._sanitize_vast_host_name(new_name) or f"vast-{host.vast_instance_id}"
        if new_alias != name and new_alias in hosts:
            print(f"Host already exists: {new_alias}")
            sys.exit(1)

        client = get_vast_client()
        client.label_instance(int(host.vast_instance_id), new_name)
        print(f"Updated Vast.ai label: {new_name}")
        print(f"Host alias: {new_alias}")
        return
    else:
        print(f"Edit is not supported for host type: {host.type.value}")
        sys.exit(1)

    host.name = new_name

    if new_name != name:
        del hosts[name]
    hosts[new_name] = host
    host_cmd.save_hosts(hosts)
    print(f"Updated host: {new_name}")


def cmd_browse(args: List[str]) -> None:
    """Browse files on a remote host."""
    host_cmd = _host_module()
    if not args:
        print("Usage: train host files <name> [path]")
        sys.exit(1)

    name = args[0]
    initial_path = args[1] if len(args) > 1 else "~"

    hosts = host_cmd.load_hosts()

    if name not in hosts:
        print(f"Host not found: {name}")
        sys.exit(1)

    host = hosts[name]
    print(f"Connecting to {host.display_name}...")

    from ..services.sftp_browser import RemoteFileBrowser
    from ..services.ssh import SSHClient

    try:
        ssh = SSHClient.from_host(host)
    except Exception as exc:
        print(f"Connection setup failed: {exc}")
        sys.exit(1)

    if not ssh.test_connection():
        print("Connection failed.")
        sys.exit(1)

    browser = RemoteFileBrowser(ssh)

    print(f"\nFile Browser: {host.display_name}")
    print("Commands: Enter=open  ..=up  q=quit  /=search  h=toggle hidden")
    print("-" * 60)

    current_path = initial_path
    search_query = ""
    show_hidden = True

    while True:
        entries = browser.navigate(current_path)

        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]
        if search_query:
            entries = [e for e in entries if search_query.lower() in e.name.lower()]

        print(f"\n{current_path}")
        print("-" * 40)

        if not entries:
            print("  (empty)")
        else:
            for i, entry in enumerate(entries):
                icon = entry.icon
                size = entry.display_size
                print(f"  {i:3}. {icon} {entry.name:<30} {size:>10}")

        print("-" * 40)

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

                    action = input("Action: (c)opy path, (v)iew head, (b)ack: ").strip().lower()
                    if action == "c":
                        print(f"Path: {entry.path}")
                        try:
                            import subprocess

                            subprocess.run(["pbcopy"], input=entry.path.encode(), check=True)
                            print("Copied to clipboard!")
                        except Exception:
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
