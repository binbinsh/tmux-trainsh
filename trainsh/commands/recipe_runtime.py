"""Runtime-oriented CLI commands for Python recipes."""

from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from typing import List, Optional

from ..constants import RECIPE_FILE_EXTENSION
from ..core.job_state import generate_job_id
from ..core.tmux_naming import get_live_session_name
from .recipe import find_recipe
from .recipe_shared import (
    EXECUTOR_OPTIONS_FLAGS,
    EXECUTOR_OPTION_FLAGS,
    HELP_FLAGS,
    SET_OPTION_FLAGS,
    WORKER_OPTION_FLAGS,
    _parse_assignment,
    _parse_int_flag,
    _print_resume_usage,
    _print_exec_usage,
    _print_full_help,
    _print_run_usage,
)
from .recipe_views import (
    _format_recent_event,
    _short_text,
    _show_execution_details,
    _show_job_details,
    cmd_jobs,
    cmd_logs,
    cmd_status,
)
from .runtime_dispatch import run_recipe_via_dag


UNSUPPORTED_EXECUTORS = {
    "k8s",
    "kubernetes",
    "kubernetesexecutor",
    "kubernetesexecutors",
    "kubernetes_executor",
    "kubeexecutor",
}
RUNTIME_FLAGS_WITH_VALUE = {
    "--host",
    "--set",
    "--pick-host",
    "--executor",
    "--executor-workers",
    "--executor-option",
    "--executor-options",
    "--callback",
}
RUNTIME_FLAGS_WITH_INLINE_VALUE = (
    "--host=",
    "--set=",
    "--pick-host=",
    "--executor=",
    "--executor-workers=",
    "--executor-option=",
    "--executor-options=",
    "--callback=",
)


def _maybe_auto_enter_tmux(
    command_parts: List[str],
    args: List[str],
    *,
    recipe_name: str,
    job_id: str,
    session_index: int,
    next_session_index: int,
) -> bool:
    """Auto-start command inside tmux when launched from a normal terminal."""
    if os.environ.get("TMUX"):
        return False
    if os.environ.get("TRAINSH_TMUX_BOOTSTRAP"):
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False

    from ..config import load_config
    from ..core.local_tmux import LocalTmuxClient

    tmux_cfg = load_config().get("tmux", {})
    auto_enter = bool(tmux_cfg.get("auto_enter_tmux", True))
    if not auto_enter:
        return False

    tmux = LocalTmuxClient()
    if not tmux.available:
        return False

    session_name = get_live_session_name(recipe_name, job_id, session_index)
    inner_cmd = [sys.executable, "-m", "trainsh", *command_parts, *args]
    command_prefix = ""
    if os.environ.get("TERM", "").lower() in {"", "dumb", "unknown"}:
        command_prefix = "TERM=xterm-256color "
    command = (
        f"{command_prefix}TRAINSH_TMUX_BOOTSTRAP=1 "
        f"TRAINSH_JOB_ID={shlex.quote(job_id)} "
        f"TRAINSH_SESSION_INDEX_START={next_session_index} "
        f"{shlex.join(inner_cmd)}"
    )

    print(f"Not in tmux; auto-starting session: {session_name}")
    result = tmux.new_session(session_name, detached=False, command=command)
    if result.returncode != 0:
        print("Failed to auto-start tmux session. Continuing in current terminal.")
        return False
    return True


def _pick_vast_host(host_name: str) -> Optional[str]:
    """Interactively pick a vast.ai instance."""
    from ..services.vast_api import get_vast_client
    from ..utils.vast_formatter import format_instance_header, format_instance_row, get_currency_settings

    try:
        client = get_vast_client()
        instances = client.list_instances()

        if not instances:
            print("No vast.ai instances available.")
            return None

        running = [item for item in instances if item.is_running]
        if not running:
            print("No running instances.")
            return None

        currency = get_currency_settings()
        header, sep = format_instance_header(currency, show_index=True)

        print(f"\nSelect host for @{host_name}:")
        print(sep)
        print(header)
        print(sep)

        for idx, inst in enumerate(running, 1):
            row = format_instance_row(inst, currency, show_index=True, index=idx)
            print(row)

        print(sep)

        try:
            choice = input(f"Enter number (1-{len(running)}) or instance ID: ").strip()

            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(running):
                    selected = running[num - 1]
                    return f"vast:{selected.id}"
                for inst in instances:
                    if inst.id == num:
                        return f"vast:{inst.id}"

            print("Invalid selection.")
            return None

        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return None

    except Exception as exc:
        print(f"Error listing vast.ai instances: {exc}")
        return None


def _coerce_executor_kw_value(raw: str) -> int | float | bool | str:
    value = raw.strip()
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        try:
            return int(value)
        except ValueError:
            pass
    if value.replace(".", "", 1).isdigit():
        try:
            return float(value)
        except ValueError:
            pass
    return value


def _parse_executor_kwargs(raw: str) -> dict:
    text = raw.strip()
    if not text:
        raise ValueError("empty value")
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("must decode to object")
        return dict(parsed)
    parsed = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"invalid token {item!r}")
        parsed[key.strip()] = _coerce_executor_kw_value(value.strip())
    if not parsed:
        raise ValueError("no key=value pairs")
    return parsed


def _parse_runtime_options(rest_args: List[str]) -> tuple[dict, dict, list[str], list[str], Optional[str], dict]:
    host_overrides = {}
    var_overrides = {}
    pick_hosts = []
    callbacks = []
    executor: Optional[str] = None
    executor_kwargs = {}

    i = 0
    while i < len(rest_args):
        arg = rest_args[i]
        if arg.startswith("--host="):
            key, value = _parse_assignment(arg.split("=", 1)[1], flag_name="--host")
            host_overrides[key] = value
        elif arg == "--host":
            if i + 1 >= len(rest_args):
                print("Missing value for --host. Expected NAME=SPEC.")
                raise SystemExit(1)
            i += 1
            key, value = _parse_assignment(rest_args[i], flag_name="--host")
            host_overrides[key] = value
        elif arg.startswith("--set="):
            key, value = _parse_assignment(arg.split("=", 1)[1], flag_name="--set")
            var_overrides[key] = value
        elif arg == "--set":
            if i + 1 >= len(rest_args):
                print("Missing value for --set. Expected NAME=VALUE.")
                raise SystemExit(1)
            i += 1
            key, value = _parse_assignment(rest_args[i], flag_name="--set")
            var_overrides[key] = value
        elif arg.startswith("--pick-host="):
            pick_host = arg.split("=", 1)[1].strip()
            if not pick_host:
                print("Missing value for --pick-host.")
                raise SystemExit(1)
            pick_hosts.append(pick_host)
        elif arg == "--pick-host":
            if i + 1 >= len(rest_args):
                print("Missing value for --pick-host.")
                raise SystemExit(1)
            i += 1
            pick_hosts.append(rest_args[i])
        elif arg.startswith("--executor="):
            executor = arg.split("=", 1)[1].strip()
            normalized_executor = "".join(ch for ch in str(executor).lower() if ch.isalnum())
            if normalized_executor in UNSUPPORTED_EXECUTORS:
                print("Error: kubernetes executor is not supported in this runtime.")
                raise SystemExit(1)
        elif arg == "--executor":
            if i + 1 >= len(rest_args):
                print("Missing value for --executor.")
                raise SystemExit(1)
            i += 1
            executor = rest_args[i]
            normalized_executor = "".join(ch for ch in str(executor).lower() if ch.isalnum())
            if normalized_executor in UNSUPPORTED_EXECUTORS:
                print("Error: kubernetes executor is not supported in this runtime.")
                raise SystemExit(1)
        elif arg.startswith("--executor-workers="):
            executor_kwargs["max_workers"] = _parse_int_flag(arg.split("=", 1)[1], flag_name="--executor-workers")
        elif arg == "--executor-workers":
            if i + 1 >= len(rest_args):
                print("Missing value for --executor-workers.")
                raise SystemExit(1)
            i += 1
            executor_kwargs["max_workers"] = _parse_int_flag(rest_args[i], flag_name="--executor-workers")
        elif arg.startswith("--executor-option="):
            key, value = _parse_assignment(arg.split("=", 1)[1], flag_name="--executor-option")
            executor_kwargs[key] = _coerce_executor_kw_value(value)
        elif arg == "--executor-option":
            if i + 1 >= len(rest_args):
                print("Missing value for --executor-option. Expected KEY=VALUE.")
                raise SystemExit(1)
            i += 1
            key, value = _parse_assignment(rest_args[i], flag_name="--executor-option")
            executor_kwargs[key] = _coerce_executor_kw_value(value)
        elif arg.startswith("--executor-options="):
            try:
                executor_kwargs.update(_parse_executor_kwargs(arg.split("=", 1)[1]))
            except (json.JSONDecodeError, ValueError) as exc:
                print(f"Invalid --executor-options: {exc}")
                raise SystemExit(1)
        elif arg == "--executor-options":
            if i + 1 >= len(rest_args):
                print("Missing value for --executor-options.")
                raise SystemExit(1)
            i += 1
            try:
                executor_kwargs.update(_parse_executor_kwargs(rest_args[i]))
            except (json.JSONDecodeError, ValueError) as exc:
                print(f"Invalid --executor-options: {exc}")
                raise SystemExit(1)
        elif arg.startswith("--callback="):
            parts = [part.strip() for part in arg.split("=", 1)[1].split(",") if part.strip()]
            if not parts:
                print("Missing value for --callback.")
                raise SystemExit(1)
            callbacks.extend(parts)
        elif arg == "--callback":
            if i + 1 >= len(rest_args):
                print("Missing value for --callback.")
                raise SystemExit(1)
            i += 1
            parts = [part.strip() for part in rest_args[i].split(",") if part.strip()]
            callbacks.extend(parts)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            raise SystemExit(1)
        else:
            print(f"Unexpected argument: {arg}")
            raise SystemExit(1)
        i += 1

    return host_overrides, var_overrides, pick_hosts, callbacks, executor, executor_kwargs


def _execute_recipe_path(
    recipe_path: str,
    *,
    runtime_args: List[str],
    original_args: List[str],
    command_parts: List[str],
    allow_auto_enter_tmux: bool = True,
    announce_text: Optional[str] = None,
) -> None:
    (
        host_overrides,
        var_overrides,
        pick_hosts,
        callbacks,
        executor,
        executor_kwargs,
    ) = _parse_runtime_options(runtime_args)

    for host_name in pick_hosts:
        selected = _pick_vast_host(host_name)
        if selected:
            host_overrides[host_name] = selected
            continue
        print(f"No host selected for {host_name}")
        raise SystemExit(1)

    run_job_id = os.environ.get("TRAINSH_JOB_ID") or generate_job_id()
    session_start = int(os.environ.get("TRAINSH_SESSION_INDEX_START", "0") or "0")
    recipe_display_name = os.path.splitext(os.path.basename(recipe_path))[0]

    if allow_auto_enter_tmux and _maybe_auto_enter_tmux(
        command_parts,
        original_args,
        recipe_name=recipe_display_name,
        job_id=run_job_id,
        session_index=session_start,
        next_session_index=session_start + 1,
    ):
        return

    print(announce_text or f"Running recipe: {os.path.basename(recipe_path)}")
    print("Commands run in remote tmux sessions (survive SSH disconnect)")

    if host_overrides:
        print("Host overrides:")
        for key, value in host_overrides.items():
            print(f"  @{key} = {value}")

    if var_overrides:
        print("Variable overrides:")
        for key, value in var_overrides.items():
            print(f"  {key} = {value}")

    print("-" * 40)

    result = run_recipe_via_dag(
        recipe_path,
        host_overrides=host_overrides,
        var_overrides=var_overrides,
        job_id=run_job_id,
        initial_session_index=session_start,
        executor_name=executor,
        executor_kwargs=executor_kwargs,
        callbacks=callbacks,
    )
    success = result.success

    print("-" * 40)
    if success:
        print("Recipe completed successfully!")
        return
    print("Recipe execution failed.")
    raise SystemExit(1)


def _parse_exec_source(args: List[str]) -> tuple[str, str, List[str]]:
    if args and args[0] in HELP_FLAGS:
        _print_full_help(0)

    source_kind: Optional[str] = None
    source_value: Optional[str] = None
    runtime_args: List[str] = []

    i = 0
    while i < len(args):
        arg = args[i]

        if arg in {"-c", "--code"}:
            if source_kind is not None:
                print("Multiple recipe sources provided to train exec.")
                raise SystemExit(1)
            if i + 1 >= len(args):
                print("Missing value for --code.")
                raise SystemExit(1)
            source_kind = "code"
            source_value = args[i + 1]
            i += 2
            continue

        if arg.startswith("--code=") or arg.startswith("-c="):
            if source_kind is not None:
                print("Multiple recipe sources provided to train exec.")
                raise SystemExit(1)
            source_kind = "code"
            source_value = arg.split("=", 1)[1]
            i += 1
            continue

        if arg == "-":
            if source_kind is not None:
                print("Multiple recipe sources provided to train exec.")
                raise SystemExit(1)
            source_kind = "stdin"
            i += 1
            continue

        if arg in RUNTIME_FLAGS_WITH_VALUE:
            runtime_args.append(arg)
            if i + 1 < len(args):
                runtime_args.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue

        if arg.startswith(RUNTIME_FLAGS_WITH_INLINE_VALUE):
            runtime_args.append(arg)
            i += 1
            continue

        if arg.startswith("-"):
            runtime_args.append(arg)
            i += 1
            continue

        if source_kind is None:
            source_kind = "recipe"
            source_value = arg
        else:
            runtime_args.append(arg)
        i += 1

    if source_kind is None:
        if sys.stdin.isatty():
            _print_exec_usage(1)
        source_kind = "stdin"

    if source_kind == "stdin":
        source_value = sys.stdin.read()
        if not str(source_value or "").strip():
            print("No recipe code received on stdin.")
            raise SystemExit(1)
    elif source_kind == "code":
        if not str(source_value or "").strip():
            print("Inline recipe code cannot be empty.")
            raise SystemExit(1)
    elif not str(source_value or "").strip():
        _print_exec_usage(1)

    return source_kind, str(source_value), runtime_args


def _write_inline_recipe_file(code: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=RECIPE_FILE_EXTENSION,
        prefix=".trainsh-exec-",
        delete=False,
        dir=os.getcwd(),
    ) as handle:
        text = code if code.endswith("\n") else f"{code}\n"
        handle.write(text)
        return handle.name


def cmd_run(args: List[str]) -> None:
    """Execute a recipe."""
    if not args:
        _print_run_usage(1)
    if args[0] in HELP_FLAGS:
        _print_full_help(0)

    name = args[0]
    rest_args = args[1:]

    recipe_path = find_recipe(name)
    if not recipe_path:
        print(f"Recipe not found: {name}")
        raise SystemExit(1)
    _execute_recipe_path(
        recipe_path,
        runtime_args=rest_args,
        original_args=args,
        command_parts=["recipe", "run"],
    )


def cmd_exec(args: List[str]) -> None:
    """Execute a recipe file, path, inline code, or stdin recipe."""
    source_kind, source_value, runtime_args = _parse_exec_source(args)

    if source_kind == "recipe":
        recipe_path = find_recipe(source_value)
        if not recipe_path:
            print(f"Recipe not found: {source_value}")
            raise SystemExit(1)
        _execute_recipe_path(
            recipe_path,
            runtime_args=runtime_args,
            original_args=args,
            command_parts=["recipe", "exec"],
        )
        return

    temp_path = _write_inline_recipe_file(source_value)
    try:
        announce_map = {
            "code": "Executing inline recipe code.",
            "stdin": "Executing recipe code from stdin.",
        }
        _execute_recipe_path(
            temp_path,
            runtime_args=runtime_args,
            original_args=args,
            command_parts=["recipe", "exec"],
            allow_auto_enter_tmux=False,
            announce_text=announce_map.get(source_kind, f"Running recipe: {os.path.basename(temp_path)}"),
        )
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def cmd_resume(args: List[str]) -> None:
    """Resume a failed/interrupted Python recipe."""
    if not args:
        _print_resume_usage(1)
    if args[0] in HELP_FLAGS:
        _print_full_help(0)

    name = args[0]
    rest_args = args[1:]
    var_overrides = {}

    i = 0
    while i < len(rest_args):
        arg = rest_args[i]
        if arg == "--host" or arg.startswith("--host="):
            print("Host overrides are not supported when resuming.")
            print("Start a fresh run with 'train recipe run <name> --host NAME=HOST' instead.")
            raise SystemExit(1)
        if arg.startswith("--set="):
            key, value = _parse_assignment(arg.split("=", 1)[1], flag_name="--set")
            var_overrides[key] = value
        elif arg == "--set":
            if i + 1 >= len(rest_args):
                print("Missing value for --set. Expected NAME=VALUE.")
                raise SystemExit(1)
            i += 1
            key, value = _parse_assignment(rest_args[i], flag_name="--set")
            var_overrides[key] = value
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            _print_resume_usage(1)
        else:
            print(f"Unexpected argument: {arg}")
            _print_resume_usage(1)
        i += 1

    recipe_path = find_recipe(name)
    if not recipe_path:
        print(f"Recipe not found: {name}")
        raise SystemExit(1)

    from ..core.job_state import JobStateManager

    state_manager = JobStateManager()
    saved_state = state_manager.find_resumable(os.path.abspath(recipe_path))
    if not saved_state:
        print(f"No resumable state found for: {name}")
        print("Use 'train recipe run' to start a fresh execution.")
        raise SystemExit(1)

    resume_job_id = os.environ.get("TRAINSH_JOB_ID") or saved_state.job_id
    resume_start = int(os.environ.get("TRAINSH_SESSION_INDEX_START", str(saved_state.next_window_index)) or "0")
    recipe_display_name = os.path.splitext(os.path.basename(recipe_path))[0]

    if _maybe_auto_enter_tmux(
        ["recipe", "resume"],
        args,
        recipe_name=recipe_display_name,
        job_id=resume_job_id,
        session_index=resume_start,
        next_session_index=resume_start + 1,
    ):
        return

    print(f"Resuming recipe: {os.path.basename(recipe_path)}")
    print(f"Job ID: {saved_state.job_id}")
    print(f"Status: {saved_state.status}")
    print(f"Progress: Step {saved_state.current_step + 1}/{saved_state.total_steps}")
    print(f"Last updated: {saved_state.updated_at}")

    if var_overrides:
        print("Variable overrides:")
        for key, value in var_overrides.items():
            print(f"  {key} = {value}")

    print("-" * 40)

    result = run_recipe_via_dag(
        recipe_path,
        var_overrides=var_overrides,
        resume=True,
        job_id=resume_job_id,
        initial_session_index=resume_start,
    )
    success = result.success

    print("-" * 40)
    if success:
        print("Recipe completed successfully!")
        return
    print("Recipe execution failed.")
    print(f"Run 'train recipe resume {name}' to retry from the failed step.")
    raise SystemExit(1)
