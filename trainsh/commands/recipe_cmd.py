"""Canonical `train recipe` command namespace."""

from __future__ import annotations

from typing import List, Optional

from ..cli_utils import render_command_help


HELP_FLAGS = {"-h", "--help", "help"}

usage = render_command_help(
    command="train recipe",
    summary="Single entry point for recipe files, runs, logs, status, jobs, and schedules.",
    usage_lines=(
        "train recipe <list|show|new|edit|remove> ...",
        "train recipe <run|resume|status|logs|jobs|schedule> ...",
    ),
    notes=(
        "Recipe file management and runtime inspection intentionally live under one namespace.",
        "Use `train help recipe` for the full lifecycle guide.",
    ),
    examples=(
        "train recipe show nanochat",
        "train recipe run nanochat",
        "train recipe status --last",
    ),
)


def main(args: List[str]) -> Optional[str]:
    """Main entry point for the canonical recipe namespace."""
    if not args or args[0] in HELP_FLAGS:
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    if subcommand in {"list", "show", "new", "edit", "remove"}:
        from .recipe import main as recipes_main

        return recipes_main([subcommand, *subargs])

    if subcommand == "run":
        from .recipe_runtime import cmd_run

        cmd_run(subargs)
        return None

    if subcommand == "resume":
        from .recipe_runtime import cmd_resume

        cmd_resume(subargs)
        return None

    if subcommand == "status":
        from .recipe_runtime import cmd_status

        cmd_status(subargs)
        return None

    if subcommand == "logs":
        from .recipe_runtime import cmd_logs

        cmd_logs(subargs)
        return None

    if subcommand == "jobs":
        from .recipe_runtime import cmd_jobs

        cmd_jobs(subargs)
        return None

    if subcommand == "schedule":
        from .schedule_cmd import main as schedule_main

        schedule_main(subargs)
        return None

    print(f"Unknown subcommand: {subcommand}")
    print(usage)
    raise SystemExit(1)


__all__ = ["main"]
