"""Canonical `train recipe` command namespace."""

from __future__ import annotations

from typing import List, Optional

from .help_catalog import render_command_help, render_top_level_help


HELP_FLAGS = {"-h", "--help", "help"}

usage = render_command_help("recipe")


def main(args: List[str]) -> Optional[str]:
    """Main entry point for the canonical recipe namespace."""
    if not args:
        print(usage)
        return None
    if args[0] in HELP_FLAGS:
        print(render_top_level_help())
        return None

    subcommand = args[0]
    subargs = args[1:]

    if subcommand in {"list", "show", "new", "edit", "remove"}:
        from .recipe import main as recipes_main

        return recipes_main([subcommand, *subargs])

    if subcommand in {"run", "exec"}:
        from .recipe_runtime import cmd_exec, cmd_run

        if subcommand == "exec":
            cmd_exec(subargs)
            return None
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
