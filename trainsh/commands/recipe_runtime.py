"""Runtime-oriented CLI commands for Python recipes."""

from __future__ import annotations

import json
import os
import shlex
import sys
from typing import List, Optional

from ..core.job_state import generate_job_id
from ..core.tmux_naming import get_live_session_name, get_window_session_name
from .recipe import find_recipe
from .runtime_dispatch import run_recipe_via_dag


HELP_FLAGS = {"-h", "--help", "help"}


def _print_run_usage(exit_code: int) -> None:
    print("Usage: train run <name> [options]")
    print()
    print("Options:")
    print("  --host NAME=HOST  Override host (e.g., --host gpu=vast:12345)")
    print("  --var NAME=VALUE  Override variable")
    print("  --pick-host NAME  Interactively select host from vast.ai")
    print("  --executor NAME   Executor: sequential|thread_pool|process_pool|local_executor|airflow|celery|dask (aliases supported)")
    print("                    kubernetes/executor is intentionally not supported in this runtime")
    print("  --max-workers N   Worker count (default: 4)")
    print("  --workers N       Alias for --max-workers")
    print("  --concurrency N   Alias for --max-workers")
    print("  --parallelism N   Alias for --max-workers")
    print("  --executor-arg KEY=VALUE")
    print("  --executor-kwargs JSON_OR_KV")
    print("  --callback NAME   Callback sink: console|sqlite (repeatable or comma-separated)")
    raise SystemExit(exit_code)


def _print_resume_usage(exit_code: int) -> None:
    print("Usage: train resume <name> [options]")
    print()
    print("Options:")
    print("  --var NAME=VALUE  Override variable while resuming")
    print()
    print("Host overrides are not supported when resuming.")
    raise SystemExit(exit_code)


def _print_logs_usage(exit_code: int) -> None:
    print("Usage: train logs [--list|--last|JOB_ID]")
    raise SystemExit(exit_code)


def _print_status_usage(exit_code: int) -> None:
    print("Usage: train status [--list|--last|--all|JOB_ID]")
    raise SystemExit(exit_code)


def _print_jobs_usage(exit_code: int) -> None:
    print("Usage: train jobs [--all]")
    raise SystemExit(exit_code)


def _maybe_auto_enter_tmux(
    subcommand: str,
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
    inner_cmd = [sys.executable, "-m", "trainsh", subcommand, *args]
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


def cmd_run(args: List[str]) -> None:
    """Execute a recipe."""
    if not args:
        _print_run_usage(1)
    if args[0] in HELP_FLAGS:
        _print_run_usage(0)

    name = args[0]
    rest_args = args[1:]

    host_overrides = {}
    var_overrides = {}
    pick_hosts = []
    callbacks = []
    executor = "sequential"
    executor_kwargs = {}
    unsupported_executors = {
        "k8s",
        "kubernetes",
        "kubernetesexecutor",
        "kubernetesexecutors",
        "kubernetes_executor",
        "kubeexecutor",
    }

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

    i = 0
    while i < len(rest_args):
        arg = rest_args[i]
        if arg == "--host" and i + 1 < len(rest_args):
            i += 1
            key, _, value = rest_args[i].partition("=")
            host_overrides[key] = value
        elif arg == "--var" and i + 1 < len(rest_args):
            i += 1
            key, _, value = rest_args[i].partition("=")
            var_overrides[key] = value
        elif arg == "--pick-host" and i + 1 < len(rest_args):
            i += 1
            pick_hosts.append(rest_args[i])
        elif arg == "--executor" and i + 1 < len(rest_args):
            i += 1
            executor = rest_args[i]
            normalized_executor = "".join(ch for ch in str(executor).lower() if ch.isalnum())
            if normalized_executor in unsupported_executors:
                print("Error: kubernetes executor is not supported in this runtime.")
                raise SystemExit(1)
        elif arg == "--max-workers" and i + 1 < len(rest_args):
            i += 1
            try:
                executor_kwargs["max_workers"] = int(rest_args[i])
            except ValueError:
                print("Invalid --max-workers value, must be integer.")
                raise SystemExit(1)
        elif arg == "--workers" and i + 1 < len(rest_args):
            i += 1
            try:
                executor_kwargs["workers"] = int(rest_args[i])
            except ValueError:
                print("Invalid --workers value, must be integer.")
                raise SystemExit(1)
        elif arg == "--concurrency" and i + 1 < len(rest_args):
            i += 1
            try:
                executor_kwargs["concurrency"] = int(rest_args[i])
            except ValueError:
                print("Invalid --concurrency value, must be integer.")
                raise SystemExit(1)
        elif arg == "--parallelism" and i + 1 < len(rest_args):
            i += 1
            try:
                executor_kwargs["parallelism"] = int(rest_args[i])
            except ValueError:
                print("Invalid --parallelism value, must be integer.")
                raise SystemExit(1)
        elif arg == "--executor-arg" and i + 1 < len(rest_args):
            i += 1
            key, sep, value = rest_args[i].partition("=")
            if not sep or not key:
                print("Usage: --executor-arg KEY=VALUE")
                raise SystemExit(1)
            executor_kwargs[key.strip()] = _coerce_executor_kw_value(value.strip())
        elif arg == "--executor-kwargs" and i + 1 < len(rest_args):
            i += 1
            try:
                executor_kwargs.update(_parse_executor_kwargs(rest_args[i]))
            except (json.JSONDecodeError, ValueError) as exc:
                print(f"Invalid --executor-kwargs: {exc}")
                raise SystemExit(1)
        elif arg == "--callback" and i + 1 < len(rest_args):
            i += 1
            parts = [part.strip() for part in rest_args[i].split(",") if part.strip()]
            callbacks.extend(parts)
        elif "=" in arg:
            key, _, value = arg.partition("=")
            var_overrides[key] = value
        i += 1

    for host_name in pick_hosts:
        selected = _pick_vast_host(host_name)
        if selected:
            host_overrides[host_name] = selected
            continue
        print(f"No host selected for {host_name}")
        raise SystemExit(1)

    recipe_path = find_recipe(name)
    if not recipe_path:
        print(f"Recipe not found: {name}")
        raise SystemExit(1)

    run_job_id = os.environ.get("TRAINSH_JOB_ID") or generate_job_id()
    session_start = int(os.environ.get("TRAINSH_SESSION_INDEX_START", "0") or "0")
    recipe_display_name = os.path.splitext(os.path.basename(recipe_path))[0]

    if _maybe_auto_enter_tmux(
        "run",
        args,
        recipe_name=recipe_display_name,
        job_id=run_job_id,
        session_index=session_start,
        next_session_index=session_start + 1,
    ):
        return

    print(f"Running recipe: {os.path.basename(recipe_path)}")
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


def cmd_logs(args: List[str]) -> None:
    """View execution logs."""
    if args and args[0] in HELP_FLAGS:
        _print_logs_usage(0)

    from ..core.execution_log import ExecutionLogReader

    reader = ExecutionLogReader()

    if not args or args[0] in ("--list", "-l"):
        executions = reader.list_executions(limit=20)

        if not executions:
            print("No execution logs found.")
            return

        print("Recent executions:")
        print("-" * 90)
        print(f"{'Job ID':<12} {'Recipe':<20} {'Started':<24} {'Status':<10} {'Duration'}")
        print("-" * 90)

        for ex in executions:
            job_id = ex.get("job_id", "")[:10]
            recipe = ex.get("recipe", "")[:18]
            started = ex.get("started", "")[:22]
            success = ex.get("success")
            duration_ms = ex.get("duration_ms", 0)

            if success is None:
                status = "running"
            elif success:
                status = "success"
            else:
                status = "failed"

            duration_str = f"{duration_ms}ms" if duration_ms else "-"
            print(f"{job_id:<12} {recipe:<20} {started:<24} {status:<10} {duration_str}")

        print("-" * 90)
        print(f"Total: {len(executions)} executions")
        print("\nUse 'train logs <job-id>' to view details.")
        return

    if args[0] == "--last":
        executions = reader.list_executions(limit=1)
        if not executions:
            print("No execution logs found.")
            return
        _show_execution_details(reader, executions[0]["job_id"])
        return

    _show_execution_details(reader, args[0])


def _show_execution_details(reader, job_id: str) -> None:
    """Show details of a specific execution."""
    summary = reader.get_execution_summary(job_id)
    if not summary:
        print(f"Execution not found: {job_id}")
        raise SystemExit(1)

    print(f"Job ID: {summary['job_id']}")
    print(f"Recipe: {summary['recipe']}")
    print(f"Recipe Path: {summary.get('recipe_path', 'N/A')}")
    print(f"Started: {summary['started']}")
    print(f"Ended: {summary['ended'] or 'N/A'}")

    success = summary.get("success")
    if success is None:
        status = "running"
    elif success:
        status = "success"
    else:
        status = "failed"
    print(f"Status: {status}")

    duration_ms = summary.get("duration_ms", 0)
    if duration_ms:
        print(f"Duration: {duration_ms}ms ({duration_ms / 1000:.2f}s)")

    variables = summary.get("variables", {})
    if variables:
        print(f"\nVariables ({len(variables)}):")
        for key, value in list(variables.items())[:10]:
            pretty = value[:50] if len(str(value)) > 50 else value
            print(f"  {key} = {pretty}")
        if len(variables) > 10:
            print(f"  ... and {len(variables) - 10} more")

    hosts = summary.get("hosts", {})
    if hosts:
        print(f"\nHosts ({len(hosts)}):")
        for key, value in hosts.items():
            print(f"  @{key} = {value}")

    steps = summary.get("steps", [])
    if steps:
        print(f"\nSteps ({len(steps)}):")
        print("-" * 70)
        for step in steps:
            step_status = "OK" if step.get("success") else "FAIL"
            step_duration = step.get("duration_ms", 0)
            step_num = step.get("step_num", "?")
            error = step.get("error", "")
            result = step.get("result", "")

            line = f"  {step_num}. [{step_status}]"
            if step_duration:
                line += f" ({step_duration}ms)"
            if result and len(result) < 50:
                line += f" -> {result}"
            print(line)

            if error:
                print(f"      Error: {error}")
        print("-" * 70)

    from ..core.execution_log import get_jobs_dir

    jobs_dir = get_jobs_dir()
    log_files = list(jobs_dir.glob(f"*_{job_id}.jsonl.gz")) + list(jobs_dir.glob(f"*_{job_id}.jsonl"))
    if not log_files:
        log_files = list(jobs_dir.glob(f"{job_id}.jsonl.gz")) + list(jobs_dir.glob(f"{job_id}.jsonl"))
    if log_files:
        print(f"\nLog file: {log_files[0]}")


def cmd_status(args: List[str]) -> None:
    """View running recipe sessions."""
    if args and args[0] in HELP_FLAGS:
        _print_status_usage(0)

    from ..core.job_state import JobStateManager

    state_manager = JobStateManager()
    print("Recipe sessions:")

    if args and args[0] in ("--last", "-1"):
        running_jobs = state_manager.list_running()
        if running_jobs:
            _show_job_details(running_jobs[0])
            return

        jobs = state_manager.list_all(limit=1)
        if not jobs:
            print("No recipe jobs found.")
            print("Run a recipe with 'train run <name>'")
            return
        print("No running jobs found. Showing latest job instead.")
        print()
        _show_job_details(jobs[0])
        return

    if args and args[0] not in ("--list", "-l", "--all", "-a"):
        job_id = args[0]
        job = state_manager.load(job_id)

        if not job:
            for candidate in state_manager.list_all():
                if candidate.job_id.startswith(job_id):
                    job = candidate
                    break

        if not job:
            print(f"Job not found: {job_id}")
            print("Use 'train status' to list jobs.")
            raise SystemExit(1)

        _show_job_details(job)
        return

    all_jobs = "--all" in args or "-a" in args
    jobs = state_manager.list_all() if all_jobs else state_manager.list_running()

    if not jobs:
        print("No running recipe jobs.")
        print("Run a recipe with 'train run <name>'")
        return

    print("Recipe Jobs:")
    print("-" * 80)
    print(f"{'ID':<10} {'Recipe':<20} {'Status':<12} {'Step':<10} {'Updated':<25}")
    print("-" * 80)

    for job in jobs:
        job_id = job.job_id[:8]
        recipe = job.recipe_name[:18]
        status = job.status[:10]
        step = f"{job.current_step + 1}/{job.total_steps}"
        updated = job.updated_at[:23]
        print(f"{job_id:<10} {recipe:<20} {status:<12} {step:<10} {updated:<25}")

    print("-" * 80)
    print(f"Total: {len(jobs)} jobs")

    if not all_jobs:
        print("\nUse '--all' to show completed/failed jobs.")
        print("Use '--last' to show the latest running job.")


def _window_session_name(job, window_name: str, fallback_index: int) -> str:
    """Resolve tmux session name for a recipe window."""
    mapped = getattr(job, "window_sessions", {}).get(window_name)
    if mapped:
        return mapped
    return get_window_session_name(job.recipe_name, job.job_id, fallback_index)


def _show_attach_commands(job) -> None:
    """Show attach commands for bridge/local/remote window sessions."""
    from ..core.executor_utils import _build_ssh_args
    from ..core.local_tmux import LocalTmuxClient
    from ..core.remote_tmux import RemoteTmuxClient

    printed = False
    if getattr(job, "bridge_session", ""):
        print("\nAttach Commands:")
        print(f"  bridge: tmux attach -t {job.bridge_session}")
        printed = True

    if not job.hosts:
        return

    local_tmux = LocalTmuxClient()
    if not printed:
        print("\nAttach Commands:")

    for fallback_index, (window_name, host_spec) in enumerate(job.hosts.items()):
        session_name = _window_session_name(job, window_name, fallback_index)
        try:
            if host_spec == "local":
                attach_cmd = local_tmux.build_attach_command(session_name, nested=False)
            else:
                attach_cmd = RemoteTmuxClient(host_spec, _build_ssh_args).build_attach_command(
                    session_name,
                    status_mode="keep",
                )
            print(f"  @{window_name}: {attach_cmd}")
        except Exception:
            print(f"  @{window_name}: tmux attach -t {session_name}")


def _show_job_details(job) -> None:
    """Show details of a specific job."""
    from ..core.tmux_session import TmuxSession, session_exists

    print(f"Job ID: {job.job_id}")
    print(f"Recipe: {job.recipe_name}")
    print(f"Recipe Path: {job.recipe_path}")
    print(f"Status: {job.status}")
    print(f"Progress: Step {job.current_step + 1}/{job.total_steps}")
    print(f"Created: {job.created_at}")
    print(f"Updated: {job.updated_at}")

    tmux_session_name = (
        getattr(job, "tmux_session", "")
        or getattr(job, "bridge_session", "")
        or next(iter(getattr(job, "window_sessions", {}).values()), "")
    )
    print(f"Tmux Session: {tmux_session_name or '(none)'}")
    if getattr(job, "bridge_session", "") and job.bridge_session != tmux_session_name:
        print(f"Bridge Session: {job.bridge_session}")

    if job.hosts:
        print("\nHosts:")
        for name, spec in job.hosts.items():
            print(f"  @{name} = {spec}")
        _show_attach_commands(job)

    if job.vast_instance_id:
        print(f"\nVast.ai Instance: {job.vast_instance_id}")
        if job.vast_start_time:
            print(f"  Started: {job.vast_start_time}")

    print("-" * 60)

    if job.status == "running" and tmux_session_name and session_exists(tmux_session_name):
        try:
            tmux = TmuxSession(tmux_session_name, create=False)
            panes = tmux.list_panes()
            if panes:
                print("\nActive Panes:")
                for pane in panes:
                    print(f"  {pane.pane_id}: {pane.window_name} ({pane.current_command})")

                print("\nLive Output (last 20 lines):")
                output = tmux.capture(panes[0].pane_id, start=-20)
                for line in output.split("\n"):
                    print(f"  {line}")
        except Exception as exc:
            print(f"\n(Could not capture output: {exc})")
        return

    if job.status == "running":
        print("\n(Tmux session no longer exists)")
        return
    print(f"\n(Job {job.status})")


def cmd_resume(args: List[str]) -> None:
    """Resume a failed/interrupted Python recipe."""
    if not args:
        _print_resume_usage(1)
    if args[0] in HELP_FLAGS:
        _print_resume_usage(0)

    name = args[0]
    rest_args = args[1:]
    var_overrides = {}

    i = 0
    while i < len(rest_args):
        arg = rest_args[i]
        if arg == "--host":
            print("Host overrides are not supported when resuming.")
            print("Start a fresh run with 'train run <name> --host NAME=HOST' instead.")
            raise SystemExit(1)
        if arg == "--var":
            if i + 1 >= len(rest_args):
                print("Missing value for --var. Expected NAME=VALUE.")
                raise SystemExit(1)
            i += 1
            key, _, value = rest_args[i].partition("=")
            var_overrides[key] = value
        elif "=" in arg:
            key, _, value = arg.partition("=")
            var_overrides[key] = value
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
        print("Use 'train run' to start a fresh execution.")
        raise SystemExit(1)

    resume_job_id = os.environ.get("TRAINSH_JOB_ID") or saved_state.job_id
    resume_start = int(os.environ.get("TRAINSH_SESSION_INDEX_START", str(saved_state.next_window_index)) or "0")
    recipe_display_name = os.path.splitext(os.path.basename(recipe_path))[0]

    if _maybe_auto_enter_tmux(
        "resume",
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
    print(f"Run 'train resume {name}' to retry from the failed step.")
    raise SystemExit(1)


def cmd_jobs(args: List[str]) -> None:
    """List all job states."""
    if args and args[0] in HELP_FLAGS:
        _print_jobs_usage(0)

    from ..core.job_state import JobStateManager

    state_manager = JobStateManager()
    show_all = "--all" in args or "-a" in args
    limit = 100 if show_all else 20
    jobs = state_manager.list_all(limit=limit)

    if not jobs:
        print("No job states found.")
        return

    print("Recipe Jobs:")
    print("-" * 90)
    print(f"{'ID':<10} {'Recipe':<25} {'Status':<12} {'Step':<10} {'Updated':<25}")
    print("-" * 90)

    for job in jobs:
        job_id = job.job_id[:8]
        recipe = job.recipe_name[:23]
        status = job.status[:10]
        step = f"{job.current_step + 1}/{job.total_steps}"
        updated = job.updated_at[:23]
        print(f"{job_id:<10} {recipe:<25} {status:<12} {step:<10} {updated:<25}")

    print("-" * 90)
    print(f"Total: {len(jobs)} jobs")

    if not show_all and len(jobs) >= 20:
        print("\nUse '--all' to show all jobs.")
