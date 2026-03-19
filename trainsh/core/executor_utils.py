# tmux-trainsh executor utility functions
# Shared parsing, SSH args, and Vast host resolution helpers.

import shlex
import subprocess
from typing import Dict, List, Optional, Tuple

from .recipe_models import RecipeModel, StepType
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


def _configured_host_for_spec(spec: str) -> Optional[Host]:
    """Resolve one configured host alias into a Host model when possible."""
    text = str(spec or "").strip()
    if not text or text == "local":
        return None

    try:
        tokens = shlex.split(text)
    except ValueError:
        return None
    if len(tokens) != 1:
        return None

    try:
        from ..commands.host import load_hosts

        host = load_hosts(include_auto_vast=False).get(text)
    except Exception:
        return None
    if host is None:
        return None
    return Host.from_dict(host.to_dict())


def _insert_tty_flag(args: List[str]) -> List[str]:
    """Insert `-t` immediately after the ssh binary when missing."""
    try:
        ssh_index = args.index("ssh")
    except ValueError:
        return args
    if "-t" in args[ssh_index + 1 :]:
        return args
    return [*args[: ssh_index + 1], "-t", *args[ssh_index + 1 :]]


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
    configured_host = _configured_host_for_spec(spec)
    if configured_host is not None:
        from ..services.ssh import SSHClient

        env_prefix = "TERM=xterm-256color LC_ALL=en_US.UTF-8"
        resolved_command = command
        if set_term:
            if command:
                resolved_command = f"{env_prefix} {command}"
            else:
                resolved_command = f"{env_prefix} exec bash -l"

        client = SSHClient.from_host(configured_host)
        args = client._build_ssh_args(resolved_command, interactive=tty)
        return _insert_tty_flag(args) if tty else args

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
    configured_host = _configured_host_for_spec(spec)
    if configured_host is not None:
        return configured_host

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


def _infer_window_hosts_from_recipe(recipe: RecipeModel, upto_step: int) -> Dict[str, str]:
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
    from ..services.vast_connection import ssh_target_to_spec, vast_ssh_targets

    try:
        client = get_vast_client()
        instance = client.get_instance(int(instance_id))
        targets = vast_ssh_targets(instance)
        for target in targets:
            if _test_ssh_connection(target["hostname"], int(target["port"])):
                return ssh_target_to_spec(target)
        if targets:
            return ssh_target_to_spec(targets[0])

        return f"vast-{instance_id}"
    except Exception:
        return f"vast-{instance_id}"
