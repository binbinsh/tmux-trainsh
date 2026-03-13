"""Centralized command catalog and long-form CLI help text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class HelpEntry:
    group: str
    command: str
    summary: str
    usage: str
    examples: tuple[str, ...] = ()


TOP_LEVEL_ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry("Workflow", "recipe", "Manage recipe files, runs, logs, status, jobs, and schedules.", "train recipe <subcommand>"),
    HelpEntry("Infrastructure", "host", "Manage named SSH or Colab host definitions.", "train host <subcommand>"),
    HelpEntry("Infrastructure", "storage", "Manage named storage backends.", "train storage <subcommand>"),
    HelpEntry("Infrastructure", "transfer", "Copy files between local paths, hosts, and storage.", "train transfer <source> <destination>"),
    HelpEntry("Infrastructure", "secrets", "Manage credentials used by hosts, storage, and cloud APIs.", "train secrets <subcommand>"),
    HelpEntry("Infrastructure", "config", "Inspect and update config.yaml and tmux settings.", "train config <subcommand>"),
    HelpEntry("Cloud", "vast", "Inspect and manage Vast.ai instances.", "train vast <subcommand>"),
    HelpEntry("Cloud", "colab", "Manage direct Google Colab SSH connections.", "train colab <subcommand>"),
    HelpEntry("Cloud", "pricing", "Inspect exchange rates and estimate costs.", "train pricing <subcommand>"),
    HelpEntry("Utility", "update", "Check for or install new tmux-trainsh releases.", "train update [--check]"),
    HelpEntry("Utility", "help", "Browse help topics and the command index.", "train help [topic]"),
    HelpEntry("Utility", "version", "Print the installed tmux-trainsh version.", "train version"),
)


COMMON_MISTAKES: tuple[tuple[str, str], ...] = (
    ("train recipes ...", "use `train recipe ...`"),
    ("train schedule ...", "use `train recipe schedule ...`"),
    ("train host connect", "use `train host ssh`"),
    ("train storage test", "use `train storage check`"),
)


COMMAND_HELP_TEXTS: dict[str, str] = {
    "recipe": """Recipe Command

Usage
  train recipe list
  train recipe show <name>
  train recipe new <name> [--template minimal]
  train recipe edit <name>
  train recipe remove <name>
  train recipe run <name> [options]
  train recipe resume <name> [options]
  train recipe status [job-id|--last|--all]
  train recipe logs [job-id|--last|--list]
  train recipe jobs [--all]
  train recipe schedule <run|list|status> [args...]

Purpose
  `train recipe` is the single workflow entry point.
  File management, immediate execution, resume, status, logs, jobs, and scheduling
  all live under this namespace.

File Commands
  list                List user recipes and bundled examples
  show <name>         Load a recipe and print variables, hosts, and steps
  new <name>          Create a recipe from a bundled template
  edit <name>         Open a recipe in $EDITOR
  remove <name>       Delete a recipe file

Runtime Commands
  run <name>          Execute a recipe immediately
  resume <name>       Resume the latest failed or interrupted run
  status              Inspect running jobs and tmux attach commands
  logs                Inspect persisted execution summaries
  jobs                Show recent job history
  schedule            Run, list, or inspect scheduled recipes

Examples
  train recipe show nanochat
  train recipe run nanochat --host gpu=vast:12345
  train recipe run nanochat --executor thread_pool --executor-workers 4
  train recipe status --last
  train recipe schedule list
""",
    "run": """Run A Recipe

Usage
  train recipe run <name> [options]

Options
  --host NAME=SPEC            Override a recipe host binding
  --set NAME=VALUE            Override a recipe variable
  --pick-host NAME            Pick a running Vast instance for one recipe host
  --executor NAME             sequential|thread_pool|process_pool|local|airflow|celery|dask|debug
  --executor-workers N        Worker limit for parallel executors
  --executor-option KEY=VALUE Repeatable executor option override
  --executor-options SPEC     JSON object or comma-separated key=value list
  --callback NAME             console|sqlite; repeat or pass comma-separated values

Notes
  `train run <name>` is a top-level alias for `train recipe run <name>`.
  kubernetes executor aliases are intentionally unsupported in this runtime.
""",
    "resume": """Resume A Recipe

Usage
  train recipe resume <name> [options]

Options
  --set NAME=VALUE            Override a recipe variable while resuming

Notes
  Resume reuses the latest resumable state for the recipe path.
  Host overrides are intentionally blocked; start a fresh run instead.
""",
    "status": """Status, Logs, Jobs, And Scheduler History

Usage
  train recipe status [job-id|--last|--all]
  train recipe logs [job-id|--last|--list]
  train recipe jobs [--all]
  train recipe schedule status [--rows N] [--runtime-db PATH]

How To Choose
  status               Live/manual jobs, tmux sessions, current progress
  logs                 Detailed persisted execution summaries
  jobs                 Compact recent-jobs table
  recipe schedule status
                       Scheduler-triggered run history
""",
    "schedule": """Schedule Recipes

Usage
  train recipe schedule run [FILTER...] [options]
  train recipe schedule list [FILTER...] [options]
  train recipe schedule status [options]

Run Options
  --recipe NAME                  Limit to one or more recipe ids or names
  --recipes-dir PATH             Override recipe discovery directory
  --runtime-db PATH              Override scheduler metadata database
  --once                         Run one scheduler pass (default)
  --forever                      Keep polling on an interval
  --wait                         Wait for started runs to finish
  --force                        Ignore schedule and start matched recipes now
  --include-invalid              Include recipes that failed schedule discovery
  --loop-interval N              Poll interval in seconds for --forever
  --max-active-runs N            Global scheduler concurrency limit
  --max-active-runs-per-recipe N Per-recipe concurrency limit
  --iterations N                 Stop after N scheduler loops in --forever mode
  --rows N                       History rows for `status`
""",
    "host": """Manage Named Hosts

Usage
  train host list
  train host add
  train host show <name>
  train host edit <name>
  train host ssh <name>
  train host files <name> [path]
  train host check <name>
  train host remove <name>
""",
    "storage": """Manage Named Storage Backends

Usage
  train storage list
  train storage add
  train storage show <name>
  train storage check <name>
  train storage remove <name>
""",
    "transfer": """Transfer Data

Usage
  train transfer <source> <destination> [options]

Endpoint Forms
  /local/path                     Local filesystem path
  @host:/path                     Configured host alias
  host:<name>:/path               Explicit host endpoint
  storage:<name>:/path            Explicit storage endpoint

Notes
  Storage endpoints can point to local, SSH, or cloud-backed named storage.
  Host <-> cloud storage transfers relay through a local temp directory.
  --dry-run works for direct rsync/rclone paths; relayed transfers fail fast instead.
""",
    "secrets": """Manage Secrets

Usage
  train secrets list
  train secrets set <key>
  train secrets get <key>
  train secrets remove <key>
  train secrets backend [name]
""",
    "config": """Manage Configuration

Usage
  train config show
  train config get <key>
  train config set <key> <value>
  train config reset
  train config tmux show
  train config tmux edit
  train config tmux apply
""",
    "vast": """Manage Vast.ai Instances

Usage
  train vast list
  train vast show <id>
  train vast ssh <id>
  train vast start <id>
  train vast stop <id>
  train vast reboot <id>
  train vast remove <id>
  train vast search
  train vast keys
  train vast attach-key [path]
""",
    "colab": """Manage Colab Connections

Usage
  train colab list
  train colab connect
  train colab ssh [name]
  train colab run <command>
""",
    "pricing": """Inspect Pricing

Usage
  train pricing rates [--refresh]
  train pricing currency [--set CODE]
  train pricing colab [--subscription SPEC]
  train pricing vast
  train pricing convert <amount> <from> <to>

Notes
  Cross-currency views auto-refresh cached exchange rates when needed.
  Exchange rates are refreshed at most once every 3 days unless you force --refresh.
""",
    "update": """Update tmux-trainsh

Usage
  train update
  train update --check
""",
}


def _render_group(entries: Iterable[HelpEntry]) -> list[str]:
    rows = list(entries)
    width = max(len(item.command) for item in rows) if rows else 0
    return [f"  {item.command:<{width}}  {item.summary}" for item in rows]


def _render_groups() -> list[str]:
    lines: list[str] = []
    groups = []
    seen = set()
    for entry in TOP_LEVEL_ENTRIES:
        if entry.group in seen:
            continue
        seen.add(entry.group)
        groups.append(entry.group)

    for group in groups:
        lines.append(f"  {group}")
        lines.extend(_render_group(item for item in TOP_LEVEL_ENTRIES if item.group == group))
        lines.append("")
    return lines


def render_top_level_help() -> str:
    lines = [
        "tmux-trainsh CLI",
        "",
        "Usage",
        "  train <command> [args...]",
        "  train help [topic]",
        "",
        "Start Here",
        "  train help recipe",
        "  train recipe show nanochat",
        "  train recipe run nanochat",
        "  train recipe status --last",
        "",
        "Choose The Right Entry",
        "  Manage recipe files                train recipe list/show/new/edit/remove",
        "  Run or resume work                 train recipe run / train recipe resume",
        "  Inspect run state                  train recipe status / logs / jobs",
        "  Inspect scheduled recipes          train recipe schedule list / status",
        "  Configure reusable machines        train host ...",
        "  Move files                         train transfer ...",
        "",
        "Command Groups",
    ]
    lines.extend(_render_groups())
    lines.extend(
        [
            "Help Navigation",
            "  train --help                      Top-level command map",
            "  train help                        Topic index",
            "  train help <topic>                Focused guide for one command family",
            "  train <command> --help            Command-local help",
            "",
            "Common Mistakes",
        ]
    )
    lines.extend(f"  {wrong:<20} {fix}" for wrong, fix in COMMON_MISTAKES)
    return "\n".join(lines).rstrip()


def render_help_index() -> str:
    lines = [
        "tmux-trainsh Help",
        "",
        "Recommended Topics",
        "  recipe    Recipe lifecycle, authoring, execution, and scheduling",
        "  run       Execution options and executor model",
        "  status    status vs logs vs jobs vs scheduler history",
        "  schedule  Scheduled recipe execution",
        "  host      Named machine management",
        "  storage   Named storage backend management",
        "  transfer  Endpoint syntax and data movement",
        "",
        "Command Index",
    ]
    lines.extend(_render_groups())
    lines.extend(
        [
            "Where To Look",
            "  Workflows                         train recipe ...",
            "  Machines and clouds               train host / vast / colab",
            "  Storage and transfers             train storage / transfer",
            "  Credentials                       train secrets",
            "  Configuration                     train config",
            "",
            "Examples",
            "  train help recipe",
            "  train help status",
            "  train help transfer",
            "  train recipe show nanochat",
            "",
            "Common Mistakes",
        ]
    )
    lines.extend(f"  {wrong:<20} {fix}" for wrong, fix in COMMON_MISTAKES)
    return "\n".join(lines).rstrip()


def render_command_help(command: str) -> str:
    return COMMAND_HELP_TEXTS[command]


__all__ = [
    "COMMAND_HELP_TEXTS",
    "COMMON_MISTAKES",
    "HelpEntry",
    "TOP_LEVEL_ENTRIES",
    "render_command_help",
    "render_help_index",
    "render_top_level_help",
]
