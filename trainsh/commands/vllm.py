"""Managed vLLM serving and batch helpers."""

from __future__ import annotations

import concurrent.futures
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cli_utils import SubcommandSpec, dispatch_subcommand
from ..services.tunnel import (
    TunnelSpec,
    find_free_local_port,
    is_local_port_open,
    start_local_tunnel,
    stop_process,
)
from ..services.vllm_batch import (
    completed_request_ids,
    load_batch_requests,
    parse_endpoint_name,
    run_batch_request,
)
from ..services.vllm_service import (
    VllmServiceRecord,
    apply_serve_tuning_defaults,
    build_vllm_serve_command,
    default_service_name,
    delete_service,
    list_services,
    load_service,
    normalize_gpu_selection,
    parse_duration,
    resolve_service_host,
    sanitize_service_name,
    save_service,
    service_is_ready,
    service_is_running,
    tmux_client_for_host,
)
from .help_catalog import render_command_help
from .help_cmd import reject_subcommand_help


SUBCOMMAND_SPECS = (
    SubcommandSpec("list", "List managed vLLM services."),
    SubcommandSpec("serve", "Start one vLLM OpenAI-compatible server in remote tmux."),
    SubcommandSpec("status", "Inspect one managed service."),
    SubcommandSpec("logs", "Read recent tmux pane output for one service."),
    SubcommandSpec("stop", "Stop one managed service and remove its record."),
    SubcommandSpec("batch", "Run local high-concurrency JSONL requests against a service or base URL."),
)

usage = render_command_help("vllm")


def _parse_assignment(raw: str, *, flag: str) -> tuple[str, str]:
    key, sep, value = str(raw or "").partition("=")
    if not sep or not key.strip():
        print(f"Invalid {flag} value. Expected KEY=VALUE.")
        raise SystemExit(1)
    return key.strip(), value


def _resolve_host(name: str):
    from .host import load_hosts

    hosts = load_hosts()
    host = hosts.get(name)
    if host is None:
        print(f"Host not found: {name}")
        raise SystemExit(1)
    return host


def _service_or_exit(name: str) -> VllmServiceRecord:
    record = load_service(name)
    if record is None:
        print(f"vLLM service not found: {name}")
        raise SystemExit(1)
    return record


def _default_session_name(service_name: str) -> str:
    return f"trainsh-vllm-{sanitize_service_name(service_name)}"


def _probe_and_update(record: VllmServiceRecord) -> tuple[bool, bool]:
    running = service_is_running(record)
    ready = running and service_is_ready(record)
    if ready:
        record.status = "ready"
        save_service(record)
    elif running:
        record.status = "starting"
        save_service(record)
    else:
        record.status = "stopped"
        save_service(record)
    return running, ready


def _capture_recent_lines(record: VllmServiceRecord, *, lines: int) -> str:
    host = resolve_service_host(record)
    client = tmux_client_for_host(host)
    result = client.capture_pane(record.session_name, start=f"-{max(20, int(lines) * 6)}")
    if result.returncode != 0:
        return result.stderr or ""
    text_lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    return "\n".join(text_lines[-max(1, int(lines)):])


def _parse_serve_args(args: List[str]) -> dict[str, Any]:
    if not args:
        print(
            "Usage: train vllm serve <host> <model> "
            "[--name <name>] [--port <port>] [--gpus <ids>] [--tp <n>] [--bind-host <host>] "
            "[--workdir <dir>] [--session <name>] [--env KEY=VALUE] "
            "[--arg <value>] [--ready-timeout <duration>] [--no-wait] [--replace]\n"
            "   or: train vllm serve <host> --model <model> "
            "[--name <name>] [--port <port>] [--bind-host <host>] "
            "[--workdir <dir>] [--session <name>] [--env KEY=VALUE] "
            "[--arg <value>] [--ready-timeout <duration>] [--no-wait] [--replace]"
        )
        raise SystemExit(1)

    host_name = str(args[0]).strip()
    if not host_name:
        print("Usage: train vllm serve <host> --model <model>")
        raise SystemExit(1)

    model = ""
    name = ""
    port = 8000
    bind_host = "127.0.0.1"
    workdir = ""
    session_name = ""
    env: Dict[str, str] = {}
    extra_args: list[str] = []
    gpus: Optional[str] = None
    tp_explicit = False
    ready_timeout = "10m"
    wait = True
    replace = False

    i = 1
    if i < len(args) and not str(args[i]).startswith("-"):
        model = str(args[i]).strip()
        i += 1
    while i < len(args):
        arg = args[i]
        if arg == "--model":
            i += 1
            if i >= len(args):
                print("Missing value for --model.")
                raise SystemExit(1)
            model = args[i].strip()
        elif arg.startswith("--model="):
            model = arg.split("=", 1)[1].strip()
        elif arg == "--name":
            i += 1
            if i >= len(args):
                print("Missing value for --name.")
                raise SystemExit(1)
            name = args[i].strip()
        elif arg.startswith("--name="):
            name = arg.split("=", 1)[1].strip()
        elif arg == "--port":
            i += 1
            if i >= len(args):
                print("Missing value for --port.")
                raise SystemExit(1)
            port = int(args[i])
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg == "--bind-host":
            i += 1
            if i >= len(args):
                print("Missing value for --bind-host.")
                raise SystemExit(1)
            bind_host = args[i].strip()
        elif arg.startswith("--bind-host="):
            bind_host = arg.split("=", 1)[1].strip()
        elif arg == "--workdir":
            i += 1
            if i >= len(args):
                print("Missing value for --workdir.")
                raise SystemExit(1)
            workdir = args[i].strip()
        elif arg.startswith("--workdir="):
            workdir = arg.split("=", 1)[1].strip()
        elif arg == "--session":
            i += 1
            if i >= len(args):
                print("Missing value for --session.")
                raise SystemExit(1)
            session_name = args[i].strip()
        elif arg.startswith("--session="):
            session_name = arg.split("=", 1)[1].strip()
        elif arg == "--env":
            i += 1
            if i >= len(args):
                print("Missing value for --env.")
                raise SystemExit(1)
            key, value = _parse_assignment(args[i], flag="--env")
            env[key] = value
        elif arg.startswith("--env="):
            key, value = _parse_assignment(arg.split("=", 1)[1], flag="--env")
            env[key] = value
        elif arg == "--gpus":
            i += 1
            if i >= len(args):
                print("Missing value for --gpus.")
                raise SystemExit(1)
            gpus = args[i].strip()
        elif arg.startswith("--gpus="):
            gpus = arg.split("=", 1)[1].strip()
        elif arg == "--arg":
            i += 1
            if i >= len(args):
                print("Missing value for --arg.")
                raise SystemExit(1)
            extra_args.append(args[i])
        elif arg.startswith("--arg="):
            extra_args.append(arg.split("=", 1)[1])
        elif arg == "--tp" or arg == "--tensor-parallel-size":
            tp_explicit = True
            i += 1
            if i >= len(args):
                print(f"Missing value for {arg}.")
                raise SystemExit(1)
            extra_args.append(f"--tensor-parallel-size={int(args[i])}")
        elif arg.startswith("--tp="):
            tp_explicit = True
            extra_args.append(f"--tensor-parallel-size={int(arg.split('=', 1)[1])}")
        elif arg.startswith("--tensor-parallel-size="):
            tp_explicit = True
            extra_args.append(f"--tensor-parallel-size={int(arg.split('=', 1)[1])}")
        elif arg == "--ready-timeout":
            i += 1
            if i >= len(args):
                print("Missing value for --ready-timeout.")
                raise SystemExit(1)
            ready_timeout = args[i]
        elif arg.startswith("--ready-timeout="):
            ready_timeout = arg.split("=", 1)[1]
        elif arg == "--no-wait":
            wait = False
        elif arg == "--replace":
            replace = True
        else:
            print(f"Unknown option: {arg}")
            raise SystemExit(1)
        i += 1

    if not model:
        print("Usage: train vllm serve <host> <model>")
        print("   or: train vllm serve <host> --model <model>")
        raise SystemExit(1)

    if gpus is not None:
        try:
            gpu_text, gpu_count = normalize_gpu_selection(gpus)
        except ValueError as exc:
            print(f"Invalid --gpus: {exc}")
            raise SystemExit(1)
        env["CUDA_VISIBLE_DEVICES"] = gpu_text
        if gpu_count > 1 and not tp_explicit and not any(
            str(item).startswith("--tensor-parallel-size")
            for item in extra_args
        ):
            extra_args.append(f"--tensor-parallel-size={gpu_count}")

    extra_args = apply_serve_tuning_defaults(extra_args)

    return {
        "host_name": host_name,
        "model": model,
        "name": sanitize_service_name(name or default_service_name(model)),
        "port": int(port),
        "bind_host": bind_host or "127.0.0.1",
        "workdir": workdir,
        "session_name": session_name.strip() or _default_session_name(name or default_service_name(model)),
        "env": env,
        "extra_args": extra_args,
        "ready_timeout": ready_timeout,
        "wait": wait,
        "replace": replace,
    }


def cmd_list(args: List[str]) -> None:
    """List managed vLLM services."""
    _ = args
    services = list_services()
    if not services:
        print("No vLLM services found.")
        print("Use 'train vllm serve <host> --model <model>' to start one.")
        return

    print("Managed vLLM services:")
    print("-" * 96)
    print(f"  {'NAME':<18} {'HOST':<18} {'PORT':<6} {'STATUS':<10} MODEL")
    print("-" * 96)
    for record in services:
        running, ready = _probe_and_update(record)
        status = "ready" if ready else ("running" if running else "stopped")
        print(f"  {record.name:<18} {record.host_name:<18} {record.port:<6} {status:<10} {record.model}")
    print("-" * 96)
    print(f"Total: {len(services)} services")


def cmd_serve(args: List[str]) -> None:
    """Start one managed vLLM service."""
    opts = _parse_serve_args(args)
    host = _resolve_host(opts["host_name"])
    host_snapshot = host.to_dict()
    existing = load_service(opts["name"])
    if existing is not None and not opts["replace"]:
        running, ready = _probe_and_update(existing)
        if running:
            status = "ready" if ready else "starting"
            print(f"Service already running: {existing.name} ({status})")
            print(f"  Host: {existing.host_name}")
            print(f"  Session: {existing.session_name}")
            print(f"  Port: {existing.port}")
            return
        delete_service(existing.name)
    elif existing is not None and opts["replace"]:
        cmd_stop([existing.name])

    record = VllmServiceRecord(
        name=opts["name"],
        host_name=opts["host_name"],
        host=host_snapshot,
        model=opts["model"],
        port=opts["port"],
        bind_host=opts["bind_host"],
        workdir=opts["workdir"],
        session_name=opts["session_name"],
        command=build_vllm_serve_command(
            model=opts["model"],
            port=opts["port"],
            bind_host=opts["bind_host"],
            workdir=opts["workdir"],
            env=opts["env"],
            extra_args=opts["extra_args"],
        ),
        status="starting",
    )

    client = tmux_client_for_host(resolve_service_host(record))
    if client.has_session(record.session_name):
        print(f"Remote tmux session already exists: {record.session_name}")
        print("Use --replace to kill and recreate it.")
        raise SystemExit(1)

    result = client.new_session(record.session_name, detached=True)
    if result.returncode != 0:
        print(result.stderr or "Failed to create remote tmux session.")
        raise SystemExit(1)

    send_result = client.send_keys(record.session_name, record.command, enter=True, literal=True)
    if send_result.returncode != 0:
        client.kill_session(record.session_name)
        print(send_result.stderr or "Failed to start vLLM command in tmux.")
        raise SystemExit(1)

    save_service(record)
    print(f"Started vLLM service: {record.name}")
    print(f"  Host: {record.host_name}")
    print(f"  Session: {record.session_name}")
    print(f"  Port: {record.port}")
    print(f"  Model: {record.model}")

    if not opts["wait"]:
        print(f"Run 'train vllm status {record.name}' to inspect readiness.")
        return

    timeout = parse_duration(opts["ready_timeout"], default=600)
    deadline = time.time() + max(1, timeout)
    while time.time() < deadline:
        running = service_is_running(record)
        if not running:
            record.status = "failed"
            save_service(record)
            print("vLLM service exited before becoming ready.")
            logs = _capture_recent_lines(record, lines=40)
            if logs:
                print(logs)
            raise SystemExit(1)
        if service_is_ready(record):
            record.status = "ready"
            save_service(record)
            print("Service is ready.")
            print(
                f"Tunnel with: train host tunnel {record.host_name} "
                f"--local-port {record.port} --remote-port {record.port}"
            )
            return
        time.sleep(2)

    record.status = "starting"
    save_service(record)
    print(f"Timed out waiting for readiness after {timeout}s.")
    print(f"Run 'train vllm logs {record.name}' for recent output.")
    raise SystemExit(1)


def cmd_status(args: List[str]) -> None:
    """Show detailed service status."""
    if not args:
        cmd_list([])
        return
    record = _service_or_exit(args[0])
    running, ready = _probe_and_update(record)
    host_snapshot = record.host or {}
    print(f"Service: {record.name}")
    print(f"  Host: {record.host_name}")
    if host_snapshot.get("hostname"):
        print(f"  Hostname: {host_snapshot.get('hostname')}")
    print(f"  Model: {record.model}")
    print(f"  Port: {record.port}")
    print(f"  Bind Host: {record.bind_host}")
    print(f"  Session: {record.session_name}")
    print(f"  Status: {'ready' if ready else ('running' if running else 'stopped')}")
    if record.workdir:
        print(f"  Workdir: {record.workdir}")
    print(f"  Updated: {record.updated_at}")
    if record.direct_base_url:
        print(f"  Direct URL: {record.direct_base_url}")
    print(
        f"  Tunnel Hint: train host tunnel {record.host_name} "
        f"--local-port {record.port} --remote-port {record.port}"
    )


def cmd_logs(args: List[str]) -> None:
    """Print recent service logs from the tmux pane."""
    if not args:
        print("Usage: train vllm logs <name> [--lines N]")
        raise SystemExit(1)
    name = args[0]
    lines = 80
    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--lines":
            i += 1
            if i >= len(args):
                print("Missing value for --lines.")
                raise SystemExit(1)
            lines = int(args[i])
        elif arg.startswith("--lines="):
            lines = int(arg.split("=", 1)[1])
        else:
            print(f"Unknown option: {arg}")
            raise SystemExit(1)
        i += 1
    record = _service_or_exit(name)
    text = _capture_recent_lines(record, lines=max(1, lines))
    if text:
        print(text)
        return
    print(f"No tmux output available for service: {name}")


def cmd_stop(args: List[str]) -> None:
    """Stop one managed service."""
    if not args:
        print("Usage: train vllm stop <name>")
        raise SystemExit(1)
    record = _service_or_exit(args[0])
    try:
        host = resolve_service_host(record)
        client = tmux_client_for_host(host)
        if record.session_name and client.has_session(record.session_name):
            result = client.kill_session(record.session_name)
            if result.returncode != 0:
                print(result.stderr or "Failed to stop remote tmux session.")
                raise SystemExit(1)
    except Exception as exc:
        print(f"Failed to stop session: {exc}")
        raise SystemExit(1)
    delete_service(record.name)
    print(f"Stopped vLLM service: {record.name}")


def _parse_batch_args(args: List[str]) -> Dict[str, Any]:
    if not args:
        print(
            "Usage: train vllm batch <service-or-base-url> [<service-or-base-url> ...] "
            "--input <jsonl> --output <jsonl> "
            "[--endpoint chat] [--concurrency N-per-target] [--retries N] [--timeout S] "
            "[--resume] [--overwrite] [--direct] [--local-port N] [--api-key KEY]"
        )
        raise SystemExit(1)

    targets: list[str] = []
    input_file = ""
    output_file = ""
    endpoint = "chat"
    concurrency = 64
    retries = 2
    timeout = 120
    resume = False
    overwrite = False
    direct = False
    local_port: Optional[int] = None
    api_key = ""
    bind_host = "127.0.0.1"
    remote_host = "127.0.0.1"

    i = 0
    while i < len(args) and not str(args[i]).startswith("-"):
        target = str(args[i]).strip()
        if target:
            targets.append(target)
        i += 1

    while i < len(args):
        arg = args[i]
        if arg == "--input":
            i += 1
            if i >= len(args):
                print("Missing value for --input.")
                raise SystemExit(1)
            input_file = args[i]
        elif arg.startswith("--input="):
            input_file = arg.split("=", 1)[1]
        elif arg == "--output":
            i += 1
            if i >= len(args):
                print("Missing value for --output.")
                raise SystemExit(1)
            output_file = args[i]
        elif arg.startswith("--output="):
            output_file = arg.split("=", 1)[1]
        elif arg == "--endpoint":
            i += 1
            if i >= len(args):
                print("Missing value for --endpoint.")
                raise SystemExit(1)
            endpoint = args[i]
        elif arg.startswith("--endpoint="):
            endpoint = arg.split("=", 1)[1]
        elif arg == "--concurrency":
            i += 1
            if i >= len(args):
                print("Missing value for --concurrency.")
                raise SystemExit(1)
            concurrency = int(args[i])
        elif arg.startswith("--concurrency="):
            concurrency = int(arg.split("=", 1)[1])
        elif arg == "--retries":
            i += 1
            if i >= len(args):
                print("Missing value for --retries.")
                raise SystemExit(1)
            retries = int(args[i])
        elif arg.startswith("--retries="):
            retries = int(arg.split("=", 1)[1])
        elif arg == "--timeout":
            i += 1
            if i >= len(args):
                print("Missing value for --timeout.")
                raise SystemExit(1)
            timeout = int(args[i])
        elif arg.startswith("--timeout="):
            timeout = int(arg.split("=", 1)[1])
        elif arg == "--local-port":
            i += 1
            if i >= len(args):
                print("Missing value for --local-port.")
                raise SystemExit(1)
            local_port = int(args[i])
        elif arg.startswith("--local-port="):
            local_port = int(arg.split("=", 1)[1])
        elif arg == "--tunnel-bind-host":
            i += 1
            if i >= len(args):
                print("Missing value for --tunnel-bind-host.")
                raise SystemExit(1)
            bind_host = args[i].strip()
        elif arg.startswith("--tunnel-bind-host="):
            bind_host = arg.split("=", 1)[1].strip()
        elif arg == "--remote-host":
            i += 1
            if i >= len(args):
                print("Missing value for --remote-host.")
                raise SystemExit(1)
            remote_host = args[i].strip()
        elif arg.startswith("--remote-host="):
            remote_host = arg.split("=", 1)[1].strip()
        elif arg == "--api-key":
            i += 1
            if i >= len(args):
                print("Missing value for --api-key.")
                raise SystemExit(1)
            api_key = args[i]
        elif arg.startswith("--api-key="):
            api_key = arg.split("=", 1)[1]
        elif arg == "--resume":
            resume = True
        elif arg == "--overwrite":
            overwrite = True
        elif arg == "--direct":
            direct = True
        else:
            print(f"Unknown option: {arg}")
            raise SystemExit(1)
        i += 1

    if not input_file or not output_file:
        print(
            "Usage: train vllm batch <service-or-base-url> [<service-or-base-url> ...] "
            "--input <jsonl> --output <jsonl>"
        )
        raise SystemExit(1)
    if overwrite and resume:
        print("--overwrite and --resume cannot be used together.")
        raise SystemExit(1)
    if not targets:
        print("train vllm batch requires at least one service or base URL target.")
        raise SystemExit(1)
    if len(targets) > 1 and local_port is not None:
        print("--local-port can only be used with a single batch target.")
        raise SystemExit(1)

    return {
        "targets": targets,
        "input_file": input_file,
        "output_file": output_file,
        "endpoint": endpoint,
        "concurrency": max(1, int(concurrency)),
        "retries": max(0, int(retries)),
        "timeout": max(1, int(timeout)),
        "resume": resume,
        "overwrite": overwrite,
        "direct": direct,
        "local_port": local_port,
        "api_key": api_key,
        "bind_host": bind_host or "127.0.0.1",
        "remote_host": remote_host or "127.0.0.1",
    }


def _run_batch_group(
    requests,
    *,
    base_url: str,
    concurrency: int,
    timeout: int,
    retries: int,
    api_key: str,
):
    """Run one isolated worker pool against a single endpoint."""
    results: list[dict[str, Any]] = []
    if not requests:
        return results
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
        futures = [
            pool.submit(
                run_batch_request,
                request,
                base_url=base_url,
                timeout=timeout,
                retries=retries,
                api_key=api_key,
            )
            for request in requests
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return results


def _resolve_batch_base_urls(opts: Dict[str, Any]) -> tuple[list[str], list[Any]]:
    base_urls: list[str] = []
    tunnel_processes: list[Any] = []
    reserved_ports: set[int] = set()
    for index, target in enumerate(opts["targets"]):
        if target.startswith("http://") or target.startswith("https://"):
            base_urls.append(target.rstrip("/"))
            continue

        service = _service_or_exit(target)
        if opts["direct"]:
            base_url = service.direct_base_url
            if not base_url:
                print(f"Cannot derive direct URL for service: {service.name}")
                raise SystemExit(1)
            base_urls.append(base_url)
            continue

        host = resolve_service_host(service)
        local_port = opts["local_port"] if index == 0 else None
        if local_port is None:
            candidate_port = service.port
            if candidate_port in reserved_ports or is_local_port_open(opts["bind_host"], candidate_port):
                candidate_port = find_free_local_port(opts["bind_host"])
            local_port = candidate_port
        spec = TunnelSpec(
            local_port=local_port,
            remote_port=service.port,
            bind_host=opts["bind_host"],
            remote_host=opts["remote_host"],
        )
        try:
            tunnel_process = start_local_tunnel(host, spec, wait_timeout=10.0)
        except RuntimeError as exc:
            print(f"Failed to open SSH tunnel for {service.name}: {exc}")
            for proc in tunnel_processes:
                stop_process(proc)
            raise SystemExit(1)
        tunnel_processes.append(tunnel_process)
        reserved_ports.add(int(local_port))
        base_url = f"http://{opts['bind_host']}:{spec.local_port}/v1"
        base_urls.append(base_url)
        print(
            f"Tunnel ready for {service.name}: "
            f"{opts['bind_host']}:{spec.local_port} -> {opts['remote_host']}:{service.port}"
        )
    return base_urls, tunnel_processes


def cmd_batch(args: List[str]) -> None:
    """Run a local high-concurrency batch client against a managed service."""
    opts = _parse_batch_args(args)
    input_path = Path(opts["input_file"]).expanduser().resolve()
    output_path = Path(opts["output_file"]).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    completed: set[str] = set()
    if output_path.exists():
        if opts["overwrite"]:
            output_path.unlink()
        elif opts["resume"]:
            completed = completed_request_ids(output_path)
        else:
            print(f"Output file already exists: {output_path}")
            print("Use --resume to continue or --overwrite to replace it.")
            raise SystemExit(1)

    base_urls, tunnel_processes = _resolve_batch_base_urls(opts)

    default_path = parse_endpoint_name(opts["endpoint"])
    if not str(default_path).startswith("/"):
        default_path = "/" + str(default_path)

    try:
        pending = load_batch_requests(input_path, default_path=default_path, completed=completed)
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
    if not pending:
        print("No pending requests.")
        for proc in tunnel_processes:
            stop_process(proc)
        return

    lock = threading.Lock()
    success_count = 0
    failure_count = 0

    try:
        with output_path.open("a", encoding="utf-8") as handle:
            if len(base_urls) == 1:
                group_results = _run_batch_group(
                    pending,
                    base_url=base_urls[0],
                    concurrency=opts["concurrency"],
                    timeout=opts["timeout"],
                    retries=opts["retries"],
                    api_key=opts["api_key"],
                )
                grouped_results = [group_results]
            else:
                request_groups = [[] for _ in base_urls]
                for index, request in enumerate(pending):
                    request_groups[index % len(base_urls)].append(request)
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(base_urls)) as endpoint_pool:
                    endpoint_futures = [
                        endpoint_pool.submit(
                            _run_batch_group,
                            request_groups[index],
                            base_url=base_urls[index],
                            concurrency=opts["concurrency"],
                            timeout=opts["timeout"],
                            retries=opts["retries"],
                            api_key=opts["api_key"],
                        )
                        for index in range(len(base_urls))
                        if request_groups[index]
                    ]
                    grouped_results = [future.result() for future in concurrent.futures.as_completed(endpoint_futures)]

            for results in grouped_results:
                for result in results:
                    with lock:
                        if result.get("ok"):
                            success_count += 1
                        else:
                            failure_count += 1
                        handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                        handle.flush()
    finally:
        for proc in tunnel_processes:
            stop_process(proc)

    print(f"Batch complete: {success_count} succeeded, {failure_count} failed.")
    print(f"Output: {output_path}")
    if failure_count:
        raise SystemExit(1)


def main(args: List[str]) -> Optional[str]:
    """Main entry point for vllm command."""
    if not args:
        print(usage)
        return None
    if args[0] in ("-h", "--help", "help"):
        reject_subcommand_help()

    subcommand = args[0]
    subargs = args[1:]
    commands = {
        "list": cmd_list,
        "serve": cmd_serve,
        "status": cmd_status,
        "logs": cmd_logs,
        "stop": cmd_stop,
        "batch": cmd_batch,
    }

    try:
        handler = dispatch_subcommand(subcommand, commands=commands)
    except KeyError:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        raise SystemExit(1)

    handler(subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
