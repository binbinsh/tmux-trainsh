"""Status and log views for runtime-oriented recipe commands."""

from __future__ import annotations

from typing import List

from ..core.tmux_naming import get_window_session_name
from .recipe_shared import (
    HELP_FLAGS,
    _print_full_help,
)


def cmd_logs(args: List[str]) -> None:
    """View execution logs."""
    if args and args[0] in HELP_FLAGS:
        _print_full_help(0)

    from ..core.execution_log import ExecutionLogReader

    with ExecutionLogReader() as reader:
        if not args or args[0] in ("--list", "-l"):
            executions = reader.list_executions(limit=20)

            if not executions:
                print("No execution logs found.")
                return

            print("Recent executions:")
            print("-" * 98)
            print(f"{'Job ID':<12} {'Recipe':<20} {'Started':<24} {'Status':<10} {'H/S':<7} {'Duration'}")
            print("-" * 98)

            for ex in executions:
                job_id = ex.get("job_id", "")[:10]
                recipe = ex.get("recipe", "")[:18]
                started = ex.get("started", "")[:22]
                success = ex.get("success")
                duration_ms = ex.get("duration_ms", 0)
                host_count = int(ex.get("host_count", 0) or 0)
                storage_count = int(ex.get("storage_count", 0) or 0)

                if success is None:
                    status = "running"
                elif success:
                    status = "success"
                else:
                    status = "failed"

                duration_str = f"{duration_ms}ms" if duration_ms else "-"
                bindings = f"{host_count}/{storage_count}"
                print(f"{job_id:<12} {recipe:<20} {started:<24} {status:<10} {bindings:<7} {duration_str}")

            print("-" * 98)
            print(f"Total: {len(executions)} executions")
            print("\nUse 'train recipe logs <job-id>' to view details.")
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

    storages = summary.get("storages", {})
    if storages:
        print(f"\nStorages ({len(storages)}):")
        for key, value in storages.items():
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

    recent_events = summary.get("recent_events", [])
    if recent_events:
        print(f"\nRecent Events ({len(recent_events)}):")
        for event in recent_events:
            print(f"  {_format_recent_event(event)}")


def cmd_status(args: List[str]) -> None:
    """View running recipe sessions."""
    if args and args[0] in HELP_FLAGS:
        _print_full_help(0)

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
            print("Run a recipe with 'train recipe run <name>'")
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
            print("Use 'train recipe status' to list jobs.")
            raise SystemExit(1)

        _show_job_details(job)
        return

    all_jobs = "--all" in args or "-a" in args
    jobs = state_manager.list_all() if all_jobs else state_manager.list_running()

    if not jobs:
        print("No running recipe jobs.")
        print("Run a recipe with 'train recipe run <name>'")
        return

    print("Recipe Jobs:")
    print("-" * 90)
    print(f"{'ID':<10} {'Recipe':<20} {'Status':<12} {'Step':<10} {'H/S':<7} {'Updated':<25}")
    print("-" * 90)

    for job in jobs:
        job_id = job.job_id[:8]
        recipe = job.recipe_name[:18]
        status = job.status[:10]
        step = f"{job.current_step + 1}/{job.total_steps}"
        bindings = f"{len(job.hosts)}/{len(getattr(job, 'storages', {}))}"
        updated = job.updated_at[:23]
        print(f"{job_id:<10} {recipe:<20} {status:<12} {step:<10} {bindings:<7} {updated:<25}")

    print("-" * 90)
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
    from ..core.execution_log import ExecutionLogReader
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

    storages = getattr(job, "storages", {})
    if storages:
        print("\nStorages:")
        for name, spec in storages.items():
            print(f"  @{name} = {spec}")

    if job.vast_instance_id:
        print(f"\nVast.ai Instance: {job.vast_instance_id}")
        if job.vast_start_time:
            print(f"  Started: {job.vast_start_time}")
    if getattr(job, "runpod_pod_id", None):
        print(f"\nRunPod Pod: {job.runpod_pod_id}")
        if getattr(job, "runpod_start_time", ""):
            print(f"  Started: {job.runpod_start_time}")

    with ExecutionLogReader() as reader:
        recent_events = reader.list_recent_events(job.job_id, limit=6)
        if recent_events:
            print("\nRecent Events:")
            for event in recent_events:
                print(f"  {_format_recent_event(event)}")

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


def _short_text(value: object, *, max_len: int = 60) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_recent_event(event: dict) -> str:
    ts = str(event.get("ts", "")).strip()
    time_text = ts[11:19] if len(ts) >= 19 else ts or "?"
    event_name = str(event.get("event", "")).strip()
    step_num = event.get("step_num")

    if event_name == "execution_start":
        return f"{time_text} execution start"
    if event_name == "execution_end":
        result = "success" if event.get("success") else "failed"
        return f"{time_text} execution end ({result})"
    if event_name == "step_start":
        return f"{time_text} step {step_num} start"
    if event_name == "step_end":
        state = str(event.get("state") or ("success" if event.get("success") else "failed"))
        return f"{time_text} step {step_num} {state}"
    if event_name == "detail":
        return f"{time_text} {event.get('category', 'detail')}: {_short_text(event.get('message', ''))}"
    if event_name == "variable_set":
        return f"{time_text} var {event.get('name', '?')} = {_short_text(event.get('value', ''))}"
    if event_name == "ssh_command":
        return f"{time_text} ssh {_short_text(event.get('host', ''))} rc={event.get('returncode', '?')}"
    if event_name == "tmux_operation":
        return f"{time_text} tmux {event.get('operation', '?')} {_short_text(event.get('target', ''))}"
    if event_name == "file_transfer":
        return f"{time_text} transfer {_short_text(event.get('source', ''))} -> {_short_text(event.get('dest', ''))}"
    if event_name == "vast_api":
        return f"{time_text} vast {event.get('operation', '?')}"
    return f"{time_text} {event_name}"


def cmd_jobs(args: List[str]) -> None:
    """List all job states."""
    if args and args[0] in HELP_FLAGS:
        _print_full_help(0)

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
