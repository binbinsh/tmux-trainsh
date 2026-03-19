"""Single-source canonical CLI reference for tmux-trainsh."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..constants import RECIPE_FILE_EXTENSION


@dataclass(frozen=True)
class HelpEntry:
    group: str
    command: str
    summary: str
    usage: str


@dataclass(frozen=True)
class DocBlock:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class CommandDoc:
    key: str
    label: str
    group: str
    command: str
    summary: str
    usage_lines: tuple[str, ...]
    blocks: tuple[DocBlock, ...] = ()
    options: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    see_also: tuple[str, ...] = ()


def _package_version() -> str:
    try:
        from .. import __version__

        return __version__
    except Exception:
        return "unknown"


def _bundled_examples() -> tuple[str, ...]:
    examples_dir = Path(__file__).resolve().parents[1] / "examples"
    names = sorted(path.stem for path in examples_dir.glob(f"*{RECIPE_FILE_EXTENSION}") if path.is_file())
    return tuple(names)


def _template_names() -> tuple[str, ...]:
    try:
        from .recipe_templates import list_template_names

        return tuple(list_template_names())
    except Exception:
        return ("minimal",)


def _joined(values: Iterable[str], *, sep: str = " | ", default: str = "-") -> str:
    items = [str(value).strip() for value in values if str(value).strip()]
    return sep.join(items) if items else default


TOP_LEVEL_ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry("Workflow", "recipe", "Single namespace for recipe files, execution, status, logs, jobs, and schedules.", "train recipe <subcommand>"),
    HelpEntry("Workflow", "run", "Top-level file-oriented alias for immediate recipe execution.", "train run <recipe> [options]"),
    HelpEntry("Workflow", "exec", "Immediate execution from recipe name, path, inline code, or stdin.", "train exec <recipe-or-path> [options]"),
    HelpEntry("Infrastructure", "host", "Manage named SSH or Colab host definitions.", "train host <subcommand>"),
    HelpEntry("Infrastructure", "storage", "Manage named storage backends.", "train storage <subcommand>"),
    HelpEntry("Infrastructure", "transfer", "Copy files between local paths, hosts, and storage.", "train transfer <source> <destination>"),
    HelpEntry("Infrastructure", "secrets", "Manage API keys and other credentials.", "train secrets <subcommand>"),
    HelpEntry("Infrastructure", "config", "Inspect and update config.yaml and tmux settings.", "train config <subcommand>"),
    HelpEntry("Cloud", "vast", "Inspect and manage Vast.ai instances.", "train vast <subcommand>"),
    HelpEntry("Cloud", "colab", "Manage one-off Google Colab SSH tunnels.", "train colab <subcommand>"),
    HelpEntry("Cloud", "pricing", "Inspect exchange rates and cost estimates.", "train pricing <subcommand>"),
    HelpEntry("Utility", "update", "Check for or install newer tmux-trainsh releases.", "train update [--check]"),
    HelpEntry("Utility", "help", "Canonical full CLI reference.", "train help"),
    HelpEntry("Utility", "version", "Print the installed tmux-trainsh version.", "train version"),
)


COMMON_MISTAKES: tuple[tuple[str, str], ...] = (
    ("train recipes ...", "use `train recipe ...`"),
    ("train schedule ...", "use `train recipe schedule ...`"),
    ("train host connect", "use `train host ssh`"),
    ("train storage test", "use `train storage check`"),
    ("train help <topic>", "use `train help`; the canonical help is no longer split across topic pages"),
)


COMMAND_DOCS: tuple[CommandDoc, ...] = (
    CommandDoc(
        key="recipe",
        label="Recipe Command",
        group="Workflow",
        command="train recipe",
        summary="Single entry point for recipe files, run/exec aliases, resume, status, logs, jobs, and schedules.",
        usage_lines=(
            "train recipe list",
            "train recipe show <name>",
            "train recipe new <name> [--template minimal]",
            "train recipe edit <name>",
            "train recipe remove <name>",
            "train recipe run <name> [options]",
            "train recipe exec <name-or-path> [options]",
            "train recipe resume <name> [options]",
            "train recipe status [job-id|--last|--all]",
            "train recipe logs [job-id|--last|--list]",
            "train recipe jobs [--all]",
            "train recipe schedule <run|list|status> [args...]",
        ),
        blocks=(
            DocBlock(
                "File Commands",
                (
                    "list                List user recipes and bundled examples.",
                    "show <name>         Load one recipe and print variables, hosts, and steps.",
                    "new <name>          Create a recipe file from a bundled template.",
                    "edit <name>         Open a recipe file in $EDITOR.",
                    "remove <name>       Delete a recipe file after confirmation.",
                ),
            ),
            DocBlock(
                "Runtime Commands",
                (
                    "run <name>          Execute a recipe immediately from a stored file.",
                    "exec <source>       Execute from a recipe file, path, inline code, or stdin.",
                    "resume <name>       Resume the latest failed or interrupted run.",
                    "status              Inspect running jobs and tmux attach commands.",
                    "logs                Inspect persisted execution summaries.",
                    "jobs                Show recent job history.",
                    "schedule            Run, list, or inspect scheduled recipes.",
                ),
            ),
        ),
        notes=(
            f"Recipe files live in project-local paths such as ./recipes/*{RECIPE_FILE_EXTENSION}.",
            "Bundled templates: " + _joined(_template_names()) + ".",
            "Current bundled examples: " + _joined(_bundled_examples()) + ".",
            "Fast paths: `train run <recipe>` for files and `train exec ...` for files or inline recipe code.",
        ),
        examples=(
            "train recipe list",
            "train recipe show nanochat",
            "train recipe run nanochat",
            "train exec nanochat",
            "train recipe status --last",
        ),
        see_also=("train help", "train run", "train exec"),
    ),
    CommandDoc(
        key="run",
        label="Run A Recipe",
        group="Workflow",
        command="train run / train recipe run",
        summary="Load one Python recipe from disk, build its dependency graph, and execute it immediately.",
        usage_lines=(
            "train recipe run <name> [options]",
            "train run <name> [options]",
        ),
        options=(
            "--host NAME=SPEC            Override one recipe host binding.",
            "--set NAME=VALUE            Override one recipe variable.",
            "--pick-host NAME            Interactively choose a running Vast host for one recipe host.",
            "--executor NAME             sequential|thread_pool|process_pool|local|airflow|celery|dask|debug",
            "--executor-workers N        Worker limit override for parallel executors.",
            "--executor-option KEY=VALUE Repeatable executor option override.",
            "--executor-options SPEC     JSON object or comma-separated key=value list.",
            "--callback NAME             console|jsonl; repeatable or comma-separated.",
        ),
        notes=(
            "`train run` is the file-oriented fast alias for `train recipe run`.",
            "Kubernetes executor aliases are intentionally unsupported in this runtime.",
        ),
        examples=(
            "train recipe run nanochat",
            "train run nanochat",
            "train recipe run nanochat --host gpu=vast:12345",
            "train recipe run nanochat --executor thread_pool --executor-workers 4 --callback console",
        ),
        see_also=("train exec", "train recipe resume", "train help"),
    ),
    CommandDoc(
        key="exec",
        label="Exec A Recipe",
        group="Workflow",
        command="train exec / train recipe exec",
        summary=f"Execute a recipe name, a {RECIPE_FILE_EXTENSION} path, inline Python recipe code, or recipe code read from stdin.",
        usage_lines=(
            "train recipe exec <name-or-path> [options]",
            "train exec <name-or-path> [options]",
            "train recipe exec -c 'from trainsh import Recipe ...' [options]",
            "train exec --code 'from trainsh import Recipe ...' [options]",
            "train exec <<'EOF'",
            "from trainsh import Recipe",
            "recipe = Recipe('demo')",
            "recipe.empty(id='start')",
            "EOF",
        ),
        options=(
            "-c, --code PYTHON           Execute inline Python recipe code.",
            "--host NAME=SPEC            Override one recipe host binding.",
            "--set NAME=VALUE            Override one recipe variable.",
            "--pick-host NAME            Interactively choose a running Vast host.",
            "--executor NAME             sequential|thread_pool|process_pool|local|airflow|celery|dask|debug",
            "--executor-workers N        Worker limit override for parallel executors.",
            "--executor-option KEY=VALUE Repeatable executor option override.",
            "--executor-options SPEC     JSON object or comma-separated key=value list.",
            "--callback NAME             console|jsonl; repeatable or comma-separated.",
        ),
        notes=(
            f"`train exec` accepts recipe names, {RECIPE_FILE_EXTENSION} paths, inline code, or stdin.",
            "`train run` stays file-oriented; `train exec` is the direct execution entry for files or inline code.",
        ),
        examples=(
            "train exec nanochat",
            f"train recipe exec ./recipes/demo{RECIPE_FILE_EXTENSION}",
            "train exec --code 'from trainsh import Recipe; recipe = Recipe(\"demo\"); recipe.empty(id=\"start\")'",
            "train exec <<'EOF'",
            "from trainsh import Recipe",
            "recipe = Recipe('demo')",
            "recipe.empty(id='start')",
            "EOF",
        ),
        see_also=("train run", "train recipe", "train help"),
    ),
    CommandDoc(
        key="resume",
        label="Resume A Recipe",
        group="Workflow",
        command="train recipe resume",
        summary="Resume the latest failed or interrupted run for one stored recipe path.",
        usage_lines=("train recipe resume <name> [options]",),
        options=("--set NAME=VALUE            Override one recipe variable while resuming.",),
        notes=(
            "Resume reuses the latest resumable state for the recipe path.",
            "Host overrides are intentionally blocked when resuming; start a fresh run instead.",
        ),
        examples=(
            "train recipe resume nanochat",
            "train recipe resume nanochat --set MODEL=small",
        ),
        see_also=("train run", "train recipe status"),
    ),
    CommandDoc(
        key="status",
        label="Status, Logs, Jobs, And Scheduler History",
        group="Workflow",
        command="train recipe status / logs / jobs / schedule status",
        summary="Choose the right runtime inspection view depending on whether a run is live, persisted, or scheduler-driven.",
        usage_lines=(
            "train recipe status [job-id|--last|--all]",
            "train recipe logs [job-id|--last|--list]",
            "train recipe jobs [--all]",
            "train recipe schedule status [--rows N] [--runtime-state PATH]",
        ),
        blocks=(
            DocBlock(
                "How To Choose",
                (
                    "status               Live/manual jobs, tmux sessions, current progress.",
                    "logs                 Detailed persisted execution summaries.",
                    "jobs                 Compact recent-jobs table.",
                    "schedule status      Scheduler-triggered run history.",
                ),
            ),
        ),
        notes=(
            "If you started the run manually, begin with `train recipe status`.",
            "If you are checking cron-like scheduled activity, begin with `train recipe schedule status`.",
        ),
        examples=(
            "train recipe status",
            "train recipe status --last",
            "train recipe logs --last",
            "train recipe jobs --all",
            "train recipe schedule status --rows 20",
        ),
        see_also=("train recipe run", "train recipe schedule"),
    ),
    CommandDoc(
        key="logs",
        label="Recipe Logs",
        group="Workflow",
        command="train recipe logs",
        summary="Inspect persisted execution summaries and step-level output for completed or running jobs.",
        usage_lines=(
            "train recipe logs",
            "train recipe logs --last",
            "train recipe logs <job-id>",
        ),
        notes=("Use `train recipe logs` for detailed step-level output.",),
        examples=(
            "train recipe logs",
            "train recipe logs --last",
            "train recipe logs job12345",
        ),
        see_also=("train recipe status", "train recipe jobs"),
    ),
    CommandDoc(
        key="jobs",
        label="Recipe Jobs",
        group="Workflow",
        command="train recipe jobs",
        summary="Show a compact recent-jobs table across manual and resumed recipe runs.",
        usage_lines=("train recipe jobs [--all]",),
        notes=("Use `train recipe jobs` for a compact recent-jobs table.",),
        examples=("train recipe jobs", "train recipe jobs --all"),
        see_also=("train recipe status", "train recipe logs"),
    ),
    CommandDoc(
        key="schedule",
        label="Schedule Recipes",
        group="Workflow",
        command="train recipe schedule",
        summary="Discover scheduled recipes, run the scheduler once or forever, and inspect scheduler history.",
        usage_lines=(
            "train recipe schedule run [FILTER...] [options]",
            "train recipe schedule list [FILTER...] [options]",
            "train recipe schedule status [options]",
        ),
        options=(
            "--recipe NAME                  Limit to one or more recipe ids or names.",
            "--recipes-dir PATH             Override recipe discovery directory.",
            "--runtime-state PATH           Override scheduler JSONL runtime state directory.",
            "--once                         Run one scheduler pass (default).",
            "--forever                      Keep polling on an interval.",
            "--wait                         Wait for started runs to finish.",
            "--force                        Ignore schedule and start matched recipes now.",
            "--include-invalid              Include recipes that failed schedule discovery.",
            "--loop-interval N              Poll interval in seconds for --forever mode.",
            "--max-active-runs N            Global scheduler concurrency limit.",
            "--max-active-runs-per-recipe N Per-recipe concurrency limit.",
            "--iterations N                 Stop after N scheduler loops in --forever mode.",
            "--rows N                       History rows for `status`.",
        ),
        notes=(
            "`train recipe status` shows live/manual jobs; `train recipe schedule status` shows scheduler history.",
            "Use `--force` to start matched scheduled recipes even if they are not currently due.",
        ),
        examples=(
            "train recipe schedule list",
            "train recipe schedule run --recipe nightly",
            "train recipe schedule run --forever --loop-interval 60",
            "train recipe schedule status --rows 50",
        ),
        see_also=("train recipe status", "train recipe"),
    ),
    CommandDoc(
        key="host",
        label="Manage Named Hosts",
        group="Infrastructure",
        command="train host",
        summary="Manage named SSH or Colab-backed host definitions used by recipes and transfers.",
        usage_lines=(
            "train host list",
            "train host add",
            "train host show <name>",
            "train host edit <name>",
            "train host ssh <name>",
            "train host run <name> -- <command>",
            "train host files <name> [path]",
            "train host check <name>",
            "train host remove <name>",
        ),
        blocks=(
            DocBlock(
                "Subcommands",
                (
                    "list                List named reusable host definitions.",
                    "add                 Add a new SSH or Colab-backed host interactively.",
                    "edit                Modify an existing named host.",
                    "show                Inspect one host definition.",
                    "ssh                 Open an SSH session using stored connection settings.",
                    "run                 Run one remote shell command with stored connection settings.",
                    "files               Browse remote files over SFTP.",
                    "check               Check whether a host is reachable.",
                    "remove              Delete a stored host definition or destroy a Vast.ai instance.",
                ),
            ),
        ),
        notes=(
            "Hosts are stored in ~/.config/tmux-trainsh/hosts.yaml.",
            "When VAST_API_KEY is configured, Vast.ai instances are auto-discovered here, including stopped or exited ones.",
            "Use `train vast` for provider-side instance lifecycle operations.",
            "Use `train colab` for quick one-off Colab tunnel helpers; prefer `train host add` for reusable configs.",
        ),
        examples=(
            "train host list",
            "train host add",
            "train host show gpu-box",
            "train host ssh gpu-box",
            "train host run gpu-box -- nvidia-smi",
            "train host check gpu-box",
        ),
        see_also=("train vast", "train colab", "train transfer"),
    ),
    CommandDoc(
        key="storage",
        label="Manage Named Storage Backends",
        group="Infrastructure",
        command="train storage",
        summary="Manage storage backends used by transfers and recipes.",
        usage_lines=(
            "train storage list",
            "train storage add",
            "train storage show <name>",
            "train storage check <name>",
            "train storage remove <name>",
        ),
        blocks=(
            DocBlock(
                "Subcommands",
                (
                    "list                List configured storage backends.",
                    "add                 Add a storage backend interactively.",
                    "show                Inspect one backend configuration.",
                    "check               Check connectivity for one backend.",
                    "remove              Delete a stored backend.",
                ),
            ),
        ),
        notes=(
            "Supported types: local, ssh, gdrive, r2, b2, s3, gcs, smb.",
            "Backends are stored in ~/.config/tmux-trainsh/storages.yaml.",
            "Credential prompts can store secrets directly in train's secrets backend.",
        ),
        examples=(
            "train storage list",
            "train storage add",
            "train storage show artifacts",
            "train storage check artifacts",
        ),
        see_also=("train transfer", "train secrets"),
    ),
    CommandDoc(
        key="transfer",
        label="Transfer Data",
        group="Infrastructure",
        command="train transfer",
        summary="Copy files between local paths, named hosts, storage backends, and cloud endpoints.",
        usage_lines=("train transfer <source> <destination> [options]",),
        blocks=(
            DocBlock(
                "Endpoint Forms",
                (
                    "/local/path                     Local filesystem path.",
                    "@host:/path                     Configured host alias.",
                    "host:<name>:/path               Explicit host endpoint.",
                    "storage:<name>:/path            Named storage endpoint.",
                    "r2:<bucket>/[prefix]            Cloudflare R2 (no pre-configuration needed).",
                    "b2:<bucket>/[prefix]            Backblaze B2.",
                    "gcs:<bucket>/[prefix]           Google Cloud Storage.",
                ),
            ),
        ),
        options=(
            "--delete, -d            Delete files at destination that do not exist in the source.",
            "--exclude, -e PAT       Exclude a glob pattern; repeat to add more patterns.",
            "--dry-run               Show what would change without transferring files.",
            "--transfers N           Parallel rclone transfers (default: 32 for cloud).",
            "--checkers N            Parallel rclone checkers (default: 64 for cloud).",
            "--upload-concurrency N  S3 multipart upload threads per file (default: 16 for cloud).",
            "--chunk-size SIZE       Multipart chunk size (default: 64M for cloud).",
            "--include PAT           rclone include pattern (repeatable).",
        ),
        notes=(
            "Cloud endpoint shortcuts (r2:/b2:/gcs:) resolve credentials from secrets automatically.",
            "No `train storage add` step is needed for r2:/b2:/gcs: endpoint prefixes.",
            "Use named storage endpoints for Amazon S3, for example `storage:s3-artifacts:/path`.",
            "Host <-> cloud storage transfers relay through a local temp directory.",
            "Dry runs work for direct rsync/rclone paths; relayed transfers fail fast instead.",
        ),
        examples=(
            "train transfer ./artifacts @gpu:/workspace/out",
            "train transfer @gpu:/workspace/checkpoints ./checkpoints",
            "train transfer ./data storage:artifacts:/datasets/run-01",
            "train transfer ./data r2:my-bucket/prefix",
            "train transfer ./shards storage:s3-artifacts:/datasets --transfers 64 --chunk-size 128M",
        ),
        see_also=("train host", "train storage", "train secrets"),
    ),
    CommandDoc(
        key="secrets",
        label="Manage Secrets",
        group="Infrastructure",
        command="train secrets",
        summary="Manage API keys and credentials used by hosts, storage, and cloud integrations.",
        usage_lines=(
            "train secrets list",
            "train secrets set <key>",
            "train secrets get <key>",
            "train secrets remove <key>",
            "train secrets backend [name]",
        ),
        blocks=(
            DocBlock(
                "Common Keys",
                (
                    "VAST_API_KEY",
                    "HF_TOKEN",
                    "OPENAI_API_KEY",
                    "ANTHROPIC_API_KEY",
                    "GITHUB_TOKEN",
                    "GOOGLE_DRIVE_CREDENTIALS",
                    "R2_CREDENTIALS",
                    "B2_CREDENTIALS",
                ),
            ),
        ),
        notes=(
            "Secret values are prompted securely for `train secrets set`.",
            "Cloud bundle secrets are supported for providers such as R2 and B2.",
        ),
        examples=(
            "train secrets list",
            "train secrets set VAST_API_KEY",
            "train secrets get OPENAI_API_KEY",
            "train secrets backend",
        ),
        see_also=("train host", "train storage", "train vast"),
    ),
    CommandDoc(
        key="config",
        label="Manage Configuration",
        group="Infrastructure",
        command="train config",
        summary="Inspect and update tmux-trainsh configuration.",
        usage_lines=(
            "train config show",
            "train config get <key>",
            "train config set <key> <value>",
            "train config reset",
            "train config tmux <show|edit|apply>",
        ),
        blocks=(
            DocBlock(
                "Subcommands",
                (
                    "show                Show the merged configuration.",
                    "get                 Read one config key by dotted path.",
                    "set                 Write one config key by dotted path.",
                    "reset               Reset config.yaml back to defaults.",
                    "tmux                Inspect or edit tmux-specific settings.",
                ),
            ),
        ),
        notes=("Main config file: ~/.config/tmux-trainsh/config.yaml.",),
        examples=(
            "train config show",
            "train config get ui.currency",
            "train config set ui.currency CNY",
            "train config tmux show",
            "train config tmux edit",
            "train config tmux apply",
        ),
        see_also=("train config tmux", "train pricing"),
    ),
    CommandDoc(
        key="config-tmux",
        label="train config tmux",
        group="Infrastructure",
        command="train config tmux",
        summary="Inspect and apply tmux-specific settings stored in config.yaml.",
        usage_lines=("train config tmux <show|edit|apply>",),
        blocks=(
            DocBlock(
                "Subcommands",
                (
                    "show                List tmux options from config.",
                    "edit                Edit tmux options in $EDITOR.",
                    "apply               Write ~/.tmux.conf from config.",
                ),
            ),
        ),
        notes=("`apply` writes ~/.tmux.conf; `edit` only changes config.yaml.",),
        examples=(
            "train config tmux show",
            "train config tmux edit",
            "train config tmux apply",
        ),
        see_also=("train config",),
    ),
    CommandDoc(
        key="vast",
        label="Manage Vast.ai Instances",
        group="Cloud",
        command="train vast",
        summary="Manage Vast.ai instances and offers.",
        usage_lines=(
            "train vast list",
            "train vast show <id>",
            "train vast ssh <id>",
            "train vast run <id> -- <command>",
            "train vast start <id>",
            "train vast stop <id>",
            "train vast reboot <id>",
            "train vast remove <id>",
            "train vast search",
            "train vast keys",
            "train vast attach-key [path]",
        ),
        blocks=(
            DocBlock(
                "Subcommands",
                (
                    "list                List your current Vast.ai instances.",
                    "show                Inspect one instance in detail.",
                    "ssh                 Open SSH to a running instance.",
                    "run                 Run one remote shell command on an instance.",
                    "start               Start an instance.",
                    "stop                Stop an instance.",
                    "reboot              Reboot an instance.",
                    "remove              Destroy an instance.",
                    "search              Search available GPU offers.",
                    "keys                List registered SSH public keys.",
                    "attach-key          Upload a local SSH public key.",
                ),
            ),
        ),
        notes=("Requires VAST_API_KEY. Configure it with `train secrets set VAST_API_KEY`.",),
        examples=(
            "train vast list",
            "train vast search",
            "train vast ssh 12345",
            "train vast run 12345 -- nvidia-smi",
            "train vast remove 12345",
        ),
        see_also=("train host", "train pricing vast"),
    ),
    CommandDoc(
        key="colab",
        label="Manage Colab Connections",
        group="Cloud",
        command="train colab",
        summary="Quick helper for one-off Google Colab SSH tunnels.",
        usage_lines=(
            "train colab list",
            "train colab connect",
            "train colab ssh [name]",
            "train colab run <command>",
        ),
        blocks=(
            DocBlock(
                "Subcommands",
                (
                    "list                List saved Colab tunnel definitions.",
                    "connect             Add a Colab tunnel definition.",
                    "ssh                 Open SSH to one saved Colab runtime.",
                    "run                 Run one remote shell command over SSH.",
                ),
            ),
        ),
        notes=(
            "For reusable named connections inside recipes, prefer `train host add` and choose a Colab host type.",
            "You need a running Colab notebook with SSH enabled plus a cloudflared or ngrok tunnel.",
        ),
        examples=(
            "train colab connect",
            "train colab list",
            "train colab ssh my-colab",
            "train colab run nvidia-smi",
        ),
        see_also=("train host",),
    ),
    CommandDoc(
        key="pricing",
        label="Inspect Pricing",
        group="Cloud",
        command="train pricing",
        summary="Show exchange rates, display currency settings, and Colab or Vast.ai cost estimates.",
        usage_lines=(
            "train pricing rates [--refresh]",
            "train pricing currency [--set CODE]",
            "train pricing colab [--subscription SPEC]",
            "train pricing vast",
            "train pricing convert <amount> <from> <to>",
        ),
        notes=(
            "Cross-currency views auto-refresh cached exchange rates when needed.",
            "Exchange rates are refreshed at most once every 3 days unless you force --refresh.",
        ),
        examples=(
            "train pricing rates --refresh",
            "train pricing currency --set CNY",
            "train pricing colab",
            "train pricing vast",
            "train pricing convert 10 USD CNY",
        ),
        see_also=("train config", "train vast"),
    ),
    CommandDoc(
        key="update",
        label="Update tmux-trainsh",
        group="Utility",
        command="train update",
        summary="Check for updates and optionally install them.",
        usage_lines=(
            "train update",
            "train update --check",
        ),
        options=("--check            Only check for updates; do not install.",),
        notes=("The updater detects whether tmux-trainsh came from uv, pip, or another supported method.",),
        examples=("train update", "train update --check"),
        see_also=("train version",),
    ),
    CommandDoc(
        key="version",
        label="Version",
        group="Utility",
        command="train version / train --version",
        summary="Print the installed tmux-trainsh version string.",
        usage_lines=(
            "train version",
            "train --version",
        ),
        examples=("train version", "train --version"),
    ),
)


def _command_doc(command: str) -> CommandDoc:
    key = "config-tmux" if command == "config.tmux" else command
    for doc in COMMAND_DOCS:
        if doc.key == key:
            return doc
    raise KeyError(command)


def _render_rows(entries: Iterable[HelpEntry]) -> list[str]:
    rows = list(entries)
    width = max(len(item.command) for item in rows) if rows else 0
    return [f"  {item.command:<{width}}  {item.summary}" for item in rows]


def _render_grouped_index() -> list[str]:
    lines: list[str] = []
    groups: list[str] = []
    seen = set()
    for entry in TOP_LEVEL_ENTRIES:
        if entry.group in seen:
            continue
        seen.add(entry.group)
        groups.append(entry.group)

    for group in groups:
        lines.append(f"  {group}")
        lines.extend(_render_rows(item for item in TOP_LEVEL_ENTRIES if item.group == group))
        lines.append("")
    return lines


def _render_command_section(doc: CommandDoc) -> list[str]:
    lines = [doc.label, f"  {doc.summary}", "", "Usage:"]
    lines.extend(f"  {line}" for line in doc.usage_lines)

    for block in doc.blocks:
        lines.extend(["", f"{block.title}:"])
        lines.extend(f"  {line}" for line in block.lines)

    if doc.options:
        lines.extend(["", "Options:"])
        lines.extend(f"  {line}" for line in doc.options)

    if doc.notes:
        lines.extend(["", "Notes:"])
        lines.extend(f"  {line}" for line in doc.notes)

    if doc.examples:
        lines.extend(["", "Examples:"])
        lines.extend(f"  {line}" for line in doc.examples)

    if doc.see_also:
        lines.extend(["", "See Also:"])
        lines.extend(f"  {line}" for line in doc.see_also)

    return lines


def render_command_help(command: str) -> str:
    doc = _command_doc(command)
    return "\n".join(_render_command_section(doc)).rstrip()


def render_top_level_help() -> str:
    examples = _joined(_bundled_examples())
    version = _package_version()
    lines = [
        "tmux-trainsh CLI Reference",
        "",
        "tmux-trainsh: GPU training workflow automation in the terminal.",
        "",
        "Manage remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage backends",
        "(Cloudflare R2, Backblaze B2, S3, Google Drive), and automate training workflows.",
        "",
        "Version",
        f"  {version}",
        "",
        "Canonical Entry",
        "  `train help` and `train --help` are aliases.",
        "  They both print this same complete, llms.txt-style CLI reference.",
        "  Explicit subcommand `--help` requests route back to this same document.",
        "",
        "Usage",
        "  train help",
        "  train --help",
        "  train <command> [args...]",
        "",
        "Recommended Topics",
        "  recipe    Recipe lifecycle, authoring, execution, and scheduling.",
        "  run       Immediate execution from stored recipe files.",
        "  exec      Direct execution from name, path, inline code, or stdin.",
        "  resume    Resume the latest failed or interrupted run.",
        "  status    Choose between status, logs, jobs, and scheduler history.",
        "  schedule  Scheduled recipe execution and scheduler inspection.",
        "",
        "Start Here",
        "  train recipe show nanochat",
        "  train exec nanochat",
        "  train recipe run nanochat",
        "  train recipe status --last",
        "  train host run gpu-box -- nvidia-smi",
        "  train vast run 12345 -- nvidia-smi",
        "",
        "Config Files",
        "  ~/.config/tmux-trainsh/",
        "  ├── config.yaml",
        "  ├── hosts.yaml",
        "  ├── storages.yaml",
        "  └── colab.yaml",
        "",
        "Project Recipe Files",
        f"  ./recipes/*{RECIPE_FILE_EXTENSION}",
        f"  or explicit paths like ./demo{RECIPE_FILE_EXTENSION}",
        "",
        "Runtime State Files",
        "  ~/.local/state/tmux-trainsh/runtime/",
        "  JSONL event, run, checkpoint, and xcom state files",
        "",
        "Bundled Examples",
        f"  {examples}",
        "",
        "Command Groups",
    ]
    lines.extend(_render_grouped_index())
    lines.extend(
        [
            "Help Behavior",
            "  Only `train help` and `train --help` are canonical top-level help entry points.",
            "  `train help <topic>` is removed.",
            "  Explicit subcommand `--help` requests route back to this same document.",
            "",
            "Python Recipe Syntax",
            f"  Recipe files live under project-local paths such as ./recipes/*{RECIPE_FILE_EXTENSION}.",
            "",
            "Public import contract",
            "  from trainsh import Recipe, Host, VastHost, HostPath, Storage, StoragePath, load_python_recipe, local",
            "",
            "Main authoring model",
            "  Recipe",
            "  Host / VastHost / HostPath",
            "  Storage / StoragePath",
            "  host.tmux(...)",
            "  local.tmux(...)",
            "",
            "Minimal example",
            "```python",
            "from trainsh import Host, Recipe",
            "",
            "recipe = Recipe('nanochat', callbacks=['console', 'jsonl'])",
            "gpu = Host('placeholder', name='gpu')",
            "",
            "pick = recipe.vast.pick(",
            "    host='gpu',",
            "    gpu_name='H200',",
            "    num_gpus=8,",
            "    min_gpu_ram=80,",
            "    auto_select=True,",
            "    create_if_missing=True,",
            ")",
            "recipe.vast.start()",
            "recipe.vast.wait_ready(timeout='30m')",
            "",
            "with gpu.tmux('main', cwd='/workspace/nanochat') as tmux:",
            "    tmux.install_uv()",
            "    tmux.run('bash runs/trainsh_nanochat.sh', background=True)",
            "    tmux.file('/workspace/nanochat-data/trainsh_success.txt', timeout='10h')",
            "```",
            "",
            "Recipe-first workflow",
            "  Prefer Python recipe authoring over ad-hoc ssh, bash, or manual polling when the task is repeatable.",
            "  For one-off remote commands, prefer `train host run <name> -- <command>` or `train vast run <id> -- <command>`.",
            "  Prefer `train run <recipe>` or `train exec <recipe>` for immediate execution.",
            "  Prefer `with local.tmux(...) as tmux:` or `with gpu.tmux(...) as tmux:` for straightforward tmux-backed flows.",
            "  Let tmux blocks chain by file order by default.",
            "  Use explicit `depends_on` only for branch fallback, fan-in/join, or cross-block edges.",
            "  `depends_on=` may be a single handle or a list of handles.",
            "  Reuse a tmux context later by name with `gpu.tmux('work')` instead of carrying one Python variable across the whole file.",
            "  Use `recipe.vast.pick(...)`, `recipe.vast.start(...)`, and `recipe.vast.wait_ready(...)` over manually assembling SSH endpoints.",
            "",
            "Scheduling metadata",
            "  recipe = Recipe('nightly', schedule='@every 15m', owner='ml', tags=['nightly', 'train'])",
            "",
            "Runtime Guarantees",
            f"  `{RECIPE_FILE_EXTENSION}` recipes run as: load -> dependency graph from `depends_on` -> executor run.",
            "  Airflow-like retry / timeout / callback / trigger-rule semantics remain supported.",
            "  Supported executor aliases: sequential, thread_pool, process_pool, local, airflow, celery, dask, debug.",
            "  Kubernetes executor remains unsupported.",
            "",
            "Run Status vs Scheduler History",
            "  `train recipe status`",
            "    Live/manual jobs, tmux sessions, current progress, attach commands.",
            "  `train recipe logs`",
            "    Full execution details for one job, including step results.",
            "  `train recipe jobs`",
            "    Compact recent job table.",
            "  `train recipe schedule list`",
            "    What recipes are scheduled?",
            "  `train recipe schedule status`",
            "    What did the scheduler start recently?",
            "",
        ]
    )

    for doc in COMMAND_DOCS:
        lines.extend(_render_command_section(doc))
        lines.append("")

    lines.extend(["Common Mistakes"])
    lines.extend(f"  {wrong:<24} {fix}" for wrong, fix in COMMON_MISTAKES)
    lines.extend(
        [
            "",
            "Regression Commands",
            "```bash",
            "python3 tests/test_commands.py",
            "python3 -m unittest tests.test_runtime_persist tests.test_pyrecipe_runtime tests.test_runtime_semantics tests.test_provider_dispatch tests.test_ti_dependencies",
            "uv run --with coverage python scripts/check_runtime_coverage.py",
            "```",
        ]
    )
    return "\n".join(lines).rstrip()

def render_readme_overview() -> str:
    version = _package_version()
    examples = ", ".join(_bundled_examples())
    return (
        "# tmux-trainsh\n\n"
        "<!-- AUTO-GENERATED FROM trainsh.commands.help_catalog; DO NOT EDIT DIRECTLY. -->\n\n"
        "`tmux-trainsh` is a terminal-first workflow runner for GPU and remote automation work.\n\n"
        f"Current version: `{version}`\n\n"
        "README is the quick overview and landing page. The canonical command reference stays in the CLI:\n\n"
        "```bash\n"
        "train help\n"
        "train --help\n"
        "```\n\n"
        "Those two commands are the canonical help entry points.\n\n"
        "## Install\n\n"
        "Install from PyPI with uv:\n\n"
        "```bash\n"
        "uv tool install -U tmux-trainsh\n"
        "train help\n"
        "```\n\n"
        "Install the latest GitHub version with uv:\n\n"
        "```bash\n"
        "uv tool install -U git+https://github.com/binbinsh/tmux-trainsh\n"
        "```\n\n"
        "Or use the install script:\n\n"
        "```bash\n"
        "curl -LsSf https://raw.githubusercontent.com/binbinsh/tmux-trainsh/main/install.sh | bash\n"
        "```\n\n"
        "## Main Command Groups\n\n"
        "- `train recipe` for recipe files, execution, status, logs, jobs, and schedules\n"
        "- `train host` for named SSH or Colab hosts\n"
        "- `train storage` for named storage backends\n"
        "- `train transfer` for local, host, and storage copies\n"
        "- `train secrets` for credentials\n"
        "- `train config` for config and tmux settings\n"
        "- `train vast` for Vast.ai instances\n"
        "- `train colab` for one-off Colab tunnels\n"
        "- `train pricing` for exchange rates and cost estimates\n\n"
        "## Quick Start\n\n"
        "```bash\n"
        "train secrets set VAST_API_KEY\n"
        "train host add\n"
        "train storage add\n\n"
        "train recipe show nanochat\n"
        "train exec nanochat\n"
        "train recipe status --last\n"
        "```\n\n"
        "## Bundled Examples\n\n"
        f"Current bundled examples: `{examples}`\n\n"
        "## Recipe Authoring\n\n"
        "Public imports:\n\n"
        "```python\n"
        "from trainsh import Recipe, Host, VastHost, HostPath, Storage, StoragePath, load_python_recipe, local\n"
        "```\n\n"
        "Main authoring model:\n\n"
        "- `Recipe`\n"
        "- `Host` / `VastHost` / `HostPath`\n"
        "- `Storage` / `StoragePath`\n"
        "- `host.tmux(...)`\n"
        "- `local.tmux(...)`\n\n"
        "## Runtime Guarantees\n\n"
        f"- `{RECIPE_FILE_EXTENSION}` recipes run as: load -> dependency graph from `depends_on` -> executor run\n"
        "- Airflow-like retry / timeout / callback / trigger-rule semantics remain supported\n"
        "- Supported executor aliases include `sequential`, `thread_pool`, `process_pool`, `local`, `airflow`, `celery`, `dask`, and `debug`\n"
        "- Kubernetes executor remains unsupported\n\n"
        "## Maintenance\n\n"
        "To refresh this file after editing the canonical help catalog:\n\n"
        "```bash\n"
        "python3 scripts/sync_cli_docs.py\n"
        "```\n\n"
        "Regression commands:\n\n"
        "```bash\n"
        "python3 tests/test_commands.py\n"
        "python3 -m unittest tests.test_runtime_persist tests.test_pyrecipe_runtime tests.test_runtime_semantics tests.test_provider_dispatch tests.test_ti_dependencies\n"
        "uv run --with coverage python scripts/check_runtime_coverage.py\n"
        "```\n"
    )


COMMAND_HELP_TEXTS = {doc.key: render_command_help(doc.key) for doc in COMMAND_DOCS}


__all__ = [
    "COMMAND_DOCS",
    "COMMAND_HELP_TEXTS",
    "COMMON_MISTAKES",
    "CommandDoc",
    "DocBlock",
    "HelpEntry",
    "TOP_LEVEL_ENTRIES",
    "render_command_help",
    "render_readme_overview",
    "render_top_level_help",
]
