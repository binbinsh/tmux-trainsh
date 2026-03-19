"""Shared CLI helpers for runtime-oriented recipe commands."""

from __future__ import annotations

from .help_catalog import render_command_help, render_top_level_help


HELP_FLAGS = {"-h", "--help", "help"}
SET_OPTION_FLAGS = {"--set"}
WORKER_OPTION_FLAGS = {"--executor-workers"}
EXECUTOR_OPTION_FLAGS = {"--executor-option"}
EXECUTOR_OPTIONS_FLAGS = {"--executor-options"}


def _print_run_usage(exit_code: int) -> None:
    print(render_command_help("run"))
    raise SystemExit(exit_code)


def _print_exec_usage(exit_code: int) -> None:
    print(render_command_help("exec"))
    raise SystemExit(exit_code)


def _print_resume_usage(exit_code: int) -> None:
    print(render_command_help("resume"))
    raise SystemExit(exit_code)


def _print_logs_usage(exit_code: int) -> None:
    print(render_command_help("logs"))
    raise SystemExit(exit_code)


def _print_status_usage(exit_code: int) -> None:
    print(render_command_help("status"))
    raise SystemExit(exit_code)


def _print_jobs_usage(exit_code: int) -> None:
    print(render_command_help("jobs"))
    raise SystemExit(exit_code)


def _print_full_help(exit_code: int) -> None:
    print(render_top_level_help())
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
