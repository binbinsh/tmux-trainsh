"""Shared CLI helpers for runtime-oriented recipe commands."""

from __future__ import annotations


HELP_FLAGS = {"-h", "--help", "help"}
SET_OPTION_FLAGS = {"--set"}
WORKER_OPTION_FLAGS = {"--executor-workers"}
EXECUTOR_OPTION_FLAGS = {"--executor-option"}
EXECUTOR_OPTIONS_FLAGS = {"--executor-options"}


def _print_run_usage(exit_code: int) -> None:
    print("Usage:")
    print("  train recipe run <recipe> [options]")
    print()
    print("What It Does:")
    print("  Load one Python recipe, build its dependency graph, and execute it now.")
    print()
    print("Primary Options:")
    print("  --host NAME=SPEC           Override one recipe host (e.g. gpu=vast:12345)")
    print("  --set NAME=VALUE           Override one recipe variable")
    print("  --pick-host NAME           Interactively choose a running Vast host for one recipe host")
    print("  --executor NAME            sequential|thread_pool|process_pool|local|airflow|celery|dask|debug")
    print("  --executor-workers N       Preferred worker count override")
    print("  --executor-option KEY=VAL  Repeatable executor option override")
    print("  --executor-options SPEC    JSON object or comma-separated key=value list")
    print("  --callback NAME            Callback sink: console|sqlite (repeatable or comma-separated)")
    print()
    print("Examples:")
    print("  train recipe run nanochat")
    print("  train recipe run nanochat --host gpu=vast:12345")
    print("  train recipe run nanochat --executor thread_pool --executor-workers 4 --callback console")
    print()
    print("Notes:")
    print("  kubernetes executor aliases are intentionally unsupported in this runtime.")
    raise SystemExit(exit_code)


def _print_resume_usage(exit_code: int) -> None:
    print("Usage:")
    print("  train recipe resume <recipe> [options]")
    print()
    print("Primary Options:")
    print("  --set NAME=VALUE           Override one recipe variable while resuming")
    print()
    print("Notes:")
    print("  Host overrides are not supported when resuming.")
    print("  Start a fresh run with `train recipe run` if host placement needs to change.")
    raise SystemExit(exit_code)


def _print_logs_usage(exit_code: int) -> None:
    print("Usage:")
    print("  train recipe logs")
    print("  train recipe logs --last")
    print("  train recipe logs <job-id>")
    print()
    print("Use `train recipe logs` for detailed step-level output.")
    raise SystemExit(exit_code)


def _print_status_usage(exit_code: int) -> None:
    print("Usage:")
    print("  train recipe status")
    print("  train recipe status --last")
    print("  train recipe status --all")
    print("  train recipe status <job-id>")
    print()
    print("Use `train recipe status` for live/manual runs and tmux session state.")
    print("Use `train recipe schedule status` for scheduler-triggered run history.")
    raise SystemExit(exit_code)


def _print_jobs_usage(exit_code: int) -> None:
    print("Usage:")
    print("  train recipe jobs [--all]")
    print()
    print("Use `train recipe jobs` for a compact recent-jobs table.")
    raise SystemExit(exit_code)


def _parse_assignment(raw: str, *, flag_name: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    key = key.strip()
    value = value.strip()
    if not sep or not key:
        print(f"Invalid {flag_name} value: {raw!r}")
        print(f"Expected {flag_name} NAME=VALUE")
        raise SystemExit(1)
    return key, value


def _parse_int_flag(raw: str, *, flag_name: str) -> int:
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid {flag_name} value, must be integer.")
        raise SystemExit(1)
