# tmux-trainsh executor utility functions
# Shared parsing, SSH args, and Vast host resolution helpers.

import shlex
import subprocess
from typing import Dict, List, Optional, Tuple

from .dsl_parser import DSLRecipe, StepType
from .models import Host, HostType


SSH_OPTION_ARGS = {
    "-p",
    "-i",
    "-J",
    "-o",
    "-F",
    "-S",
    "-L",
    "-R",
    "-D",
}


def _split_ssh_spec(spec: str) -> Tuple[str, List[str]]:
    """Split SSH spec into host and option args."""
    tokens = shlex.split(spec) if spec else []
    host = ""
    options: List[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            options.append(token)
            if token in SSH_OPTION_ARGS and i + 1 < len(tokens):
                options.append(tokens[i + 1])
                i += 1
            i += 1
            continue
        if not host:
            host = token
        else:
            options.append(token)
        i += 1
    if not host:
        host = spec
    return host, options


def _build_ssh_args(spec: str, command: Optional[str] = None, tty: bool = False, set_term: bool = False) -> List[str]:
    """Build SSH command args from a host spec and optional command."""
    host, options = _split_ssh_spec(spec)
    args = ["ssh"]
    if tty:
        args.append("-t")
    args.extend(options)
    args.append(host)

    env_prefix = "TERM=xterm-256color LC_ALL=en_US.UTF-8"

    if set_term:
        if command:
            args.append(f"{env_prefix} {command}")
        else:
            args.append(f"{env_prefix} exec bash -l")
    elif command:
        args.append(command)

    return args


def _host_from_ssh_spec(spec: str) -> Host:
    """Parse SSH spec into a Host object for rsync/ssh."""
    host_token, options = _split_ssh_spec(spec)
    username = ""
    hostname = host_token
    if "@" in host_token:
        username, hostname = host_token.split("@", 1)

    port = 22
    key_path = None
    jump_host = None
    proxy_command = None
    i = 0
    while i < len(options):
        opt = options[i]
        if opt == "-p" and i + 1 < len(options):
            try:
                port = int(options[i + 1])
            except ValueError:
                port = 22
            i += 2
            continue
        if opt == "-i" and i + 1 < len(options):
            key_path = options[i + 1]
            i += 2
            continue
        if opt == "-J" and i + 1 < len(options):
            jump_host = options[i + 1]
            i += 2
            continue
        if opt == "-o" and i + 1 < len(options):
            opt_value = options[i + 1]
            if opt_value.startswith("ProxyCommand="):
                proxy_command = opt_value.split("=", 1)[1]
            i += 2
            continue
        if opt in SSH_OPTION_ARGS:
            i += 2
            continue
        i += 1

    env_vars = {}
    if proxy_command:
        env_vars["proxy_command"] = proxy_command

    return Host(
        id=spec,
        name=spec,
        type=HostType.SSH,
        hostname=hostname,
        port=port,
        username=username,
        ssh_key_path=key_path,
        jump_host=jump_host,
        env_vars=env_vars,
    )


def _format_duration(seconds: float) -> str:
    """Format seconds into a compact duration string."""
    total_seconds = int(seconds)
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _infer_window_hosts_from_recipe(recipe: DSLRecipe, upto_step: int) -> Dict[str, str]:
    """Infer window->host mapping from tmux.open steps up to a step index."""
    mapping: Dict[str, str] = {}
    for idx, step in enumerate(recipe.steps):
        if idx > upto_step:
            break
        if step.type != StepType.CONTROL or step.command != "tmux.open":
            continue
        if len(step.args) < 3 or step.args[1] != "as":
            continue

        host_ref = step.args[0]
        window_name = step.args[2]

        if host_ref.startswith("@"):
            host_name = host_ref[1:]
            mapping[window_name] = recipe.hosts.get(host_name, host_name)
        else:
            mapping[window_name] = host_ref

    return mapping


def _test_ssh_connection(host: str, port: int, timeout: int = 5) -> bool:
    """Test if SSH connection works."""
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={timeout}",
                "-o",
                "StrictHostKeyChecking=no",
                "-p",
                str(port),
                f"root@{host}",
                "echo ok",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def _resolve_vast_host(instance_id: str) -> str:
    """Resolve vast.ai instance ID to SSH host spec."""
    from ..services.vast_api import get_vast_client

    try:
        client = get_vast_client()
        instance = client.get_instance(int(instance_id))

        if instance.public_ipaddr and instance.direct_port_start:
            if _test_ssh_connection(instance.public_ipaddr, instance.direct_port_start):
                return f"root@{instance.public_ipaddr} -p {instance.direct_port_start}"

        if instance.ssh_host and instance.ssh_port:
            if _test_ssh_connection(instance.ssh_host, instance.ssh_port):
                return f"root@{instance.ssh_host} -p {instance.ssh_port}"

        if instance.ssh_host and instance.ssh_port:
            return f"root@{instance.ssh_host} -p {instance.ssh_port}"

        return f"vast-{instance_id}"
    except Exception:
        return f"vast-{instance_id}"
