#!/usr/bin/env python
# train - GPU training workflow automation
# License: MIT

import sys
from typing import Optional, List, Dict

BANNER = r'''
   ████████╗██████╗  █████╗ ██╗███╗   ██╗███████╗██╗  ██╗
   ╚══██╔══╝██╔══██╗██╔══██╗██║████╗  ██║██╔════╝██║  ██║
      ██║   ██████╔╝███████║██║██╔██╗ ██║███████╗███████║
      ██║   ██╔══██╗██╔══██║██║██║╚██╗██║╚════██║██╔══██║
      ██║   ██║  ██║██║  ██║██║██║ ╚████║███████║██║  ██║
      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝

   ════════════════════════════════════════════════════════
     🖥️  TMUX   ══▶   ☁️  GPU   ══▶   💾  STORAGE
   ════════════════════════════════════════════════════════
'''


# ---------------------------------------------------------------------------
# COMMANDS_REGISTRY – single source of truth for all CLI commands.
# Each entry defines a top-level command, its description, and subcommands.
# generate_commands_markdown() renders them as markdown for README.
# usage / help_text are generated from this registry.
# ---------------------------------------------------------------------------

COMMANDS_REGISTRY: List[Dict] = [
    {
        "command": "run",
        "description": "Run a recipe (alias for \"recipe run\")",
        "help_summary": "Run a recipe",
        "frequency": "frequent",
        "subcommands": [
            {"name": "<name>", "description": "Run a recipe"},
            {"name": "<name> --host gpu=vast:123", "description": "Override host"},
            {"name": "<name> --var MODEL=llama-7b", "description": "Override variable"},
            {"name": "<name> --pick-host gpu", "description": "Pick Vast.ai host"},
        ],
    },
    {
        "command": "exec",
        "description": "Execute DSL commands directly",
        "help_summary": "Execute DSL commands directly",
        "frequency": "frequent",
        "subcommands": [
            {"name": "'<dsl>'", "description": "Execute DSL commands directly"},
            {"name": "'@session > cmd'", "description": "Run in tmux session; falls back to host if no session exists"},
            {"name": "'@src:path -> @dst:path'", "description": "Transfer files"},
        ],
    },
    {
        "command": "host",
        "description": "Host management (SSH, Colab, Vast.ai)",
        "help_summary": "Host management (SSH, Colab, Vast.ai)",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List configured hosts", "frequency": "frequent"},
            {"name": "show <name>", "description": "Show host details", "frequency": "frequent"},
            {"name": "ssh <name>", "description": "SSH into host", "frequency": "frequent"},
            {"name": "add", "description": "Add new host (SSH/Colab)", "frequency": "occasional"},
            {"name": "edit <name>", "description": "Edit existing host config", "frequency": "occasional"},
            {"name": "browse <name>", "description": "Browse files on host", "frequency": "occasional"},
            {"name": "test <name>", "description": "Test connection", "frequency": "occasional"},
            {"name": "rm <name>", "description": "Remove a host", "frequency": "rare"},
        ],
    },
    {
        "command": "transfer",
        "description": "File transfer between hosts/storage",
        "help_summary": "File transfer between hosts/storage",
        "frequency": "frequent",
        "subcommands": [
            {"name": "<src> <dst>", "description": "Transfer files"},
            {"name": "<src> <dst> --delete", "description": "Sync with deletions"},
            {"name": "<src> <dst> --exclude '*.ckpt'", "description": "Exclude patterns"},
            {"name": "<src> <dst> --dry-run", "description": "Preview transfer"},
        ],
    },
    {
        "command": "recipe",
        "description": "Recipe management (list, show, edit, etc.)",
        "help_summary": "Recipe management",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List recipes", "frequency": "frequent"},
            {"name": "show <name>", "description": "Show recipe details", "frequency": "frequent"},
            {"name": "status", "description": "View running sessions", "frequency": "frequent"},
            {"name": "status --last", "description": "Show latest running job details and attach commands", "frequency": "frequent"},
            {"name": "status --all", "description": "Include completed sessions", "frequency": "frequent"},
            {"name": "syntax", "description": "Show full DSL syntax reference", "frequency": "occasional"},
            {"name": "new <name>", "description": "Create new recipe", "frequency": "occasional"},
            {"name": "edit <name>", "description": "Edit recipe in editor", "frequency": "occasional"},
            {"name": "run <name>", "description": "Run a recipe (same as `train run`)", "frequency": "occasional"},
            {"name": "resume <name>", "description": "Resume a failed/interrupted recipe (rebuilds tmux bridge splits)", "frequency": "occasional"},
            {"name": "resume <name> --check", "description": "Check remote status only", "frequency": "occasional"},
            {"name": "logs", "description": "View execution logs", "frequency": "occasional"},
            {"name": "logs --last", "description": "Show last execution", "frequency": "occasional"},
            {"name": "logs <job-id>", "description": "Show logs for a specific job", "frequency": "occasional"},
            {"name": "jobs", "description": "View job history", "frequency": "occasional"},
            {"name": "rm <name>", "description": "Remove a recipe", "frequency": "rare"},
        ],
    },
    {
        "command": "storage",
        "description": "Storage backend management (R2, B2, S3, etc.)",
        "help_summary": "Storage backend management (R2, B2, S3)",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List storage backends", "frequency": "occasional"},
            {"name": "show <name>", "description": "Show storage details", "frequency": "occasional"},
            {"name": "add", "description": "Add storage backend", "frequency": "occasional"},
            {"name": "test <name>", "description": "Test connection", "frequency": "occasional"},
            {"name": "rm <name>", "description": "Remove storage", "frequency": "rare"},
        ],
    },
    {
        "command": "secrets",
        "description": "Manage API keys and credentials",
        "help_summary": "Manage API keys and credentials",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List stored secrets", "frequency": "occasional"},
            {"name": "set <key>", "description": "Set a secret", "frequency": "occasional"},
            {"name": "get <key>", "description": "Get a secret", "frequency": "occasional"},
            {"name": "delete <key>", "description": "Delete a secret", "frequency": "rare"},
        ],
    },
    {
        "command": "config",
        "description": "Configuration and settings",
        "help_summary": "Configuration and settings",
        "frequency": "mixed",
        "subcommands": [
            {"name": "show", "description": "Show configuration", "frequency": "occasional"},
            {"name": "get <key>", "description": "Get config value", "frequency": "occasional"},
            {"name": "set <key> <val>", "description": "Set config value", "frequency": "occasional"},
            {"name": "tmux-setup", "description": "Apply tmux configuration to ~/.tmux.conf", "frequency": "occasional"},
            {"name": "tmux-edit", "description": "Edit tmux options in $EDITOR", "frequency": "occasional"},
            {"name": "tmux-list", "description": "List current tmux options", "frequency": "occasional"},
            {"name": "reset", "description": "Reset configuration", "frequency": "rare"},
        ],
    },
    {
        "command": "colab",
        "description": "Google Colab integration",
        "help_summary": "Google Colab integration",
        "frequency": "occasional",
        "subcommands": [
            {"name": "list", "description": "List Colab connections"},
            {"name": "connect", "description": "Add Colab connection"},
            {"name": "run <cmd>", "description": "Run command on Colab"},
            {"name": "ssh", "description": "SSH into Colab"},
        ],
    },
    {
        "command": "vast",
        "description": "Vast.ai instance management",
        "help_summary": "Vast.ai instance management",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List your instances", "frequency": "occasional"},
            {"name": "show <id>", "description": "Show instance details", "frequency": "occasional"},
            {"name": "ssh <id>", "description": "SSH into instance", "frequency": "occasional"},
            {"name": "start <id>", "description": "Start instance", "frequency": "occasional"},
            {"name": "stop <id>", "description": "Stop instance", "frequency": "occasional"},
            {"name": "reboot <id>", "description": "Reboot instance", "frequency": "occasional"},
            {"name": "search", "description": "Search for GPU offers", "frequency": "occasional"},
            {"name": "keys", "description": "List SSH keys", "frequency": "occasional"},
            {"name": "attach-key [path]", "description": "Attach local SSH key", "frequency": "occasional"},
            {"name": "rm <id>", "description": "Remove instance", "frequency": "rare"},
        ],
    },
    {
        "command": "pricing",
        "description": "Currency exchange rates and cost calculator",
        "help_summary": "Currency exchange and cost calculator",
        "frequency": "rare",
        "subcommands": [
            {"name": "rates", "description": "Show exchange rates"},
            {"name": "rates --refresh", "description": "Refresh exchange rates"},
            {"name": "currency", "description": "Show display currency"},
            {"name": "currency --set CNY", "description": "Set display currency"},
            {"name": "colab", "description": "Show Colab pricing"},
            {"name": "vast", "description": "Show Vast.ai costs"},
            {"name": "convert 10 USD CNY", "description": "Convert currency"},
        ],
    },
    {
        "command": "update",
        "description": "Check for updates",
        "help_summary": "Check for updates",
        "frequency": "rare",
        "subcommands": [],
    },
    {
        "command": "help",
        "description": "Show help",
        "help_summary": "Show this help",
        "frequency": "rare",
        "subcommands": [],
    },
    {
        "command": "version",
        "description": "Show version",
        "help_summary": "Show version",
        "frequency": "rare",
        "subcommands": [],
    },
]


def _generate_usage() -> str:
    """Generate the short usage string from COMMANDS_REGISTRY."""
    lines = ["[command] [args...]", "", "Commands:"]
    for entry in COMMANDS_REGISTRY:
        cmd = entry["command"]
        # Skip meta commands (help/version) in short usage
        if cmd in ("help", "version"):
            continue
        lines.append(f"  {cmd:<10s}- {entry['description']}")
    lines.append("")
    return "\n".join(lines)


def _generate_help_text() -> str:
    """Generate the full help text from COMMANDS_REGISTRY."""
    lines = [
        "",
        "tmux-trainsh: GPU training workflow automation in the terminal.",
        "",
        "Manage remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage backends",
        "(Cloudflare R2, Backblaze B2, S3, Google Drive), and automate training workflows.",
        "",
        "QUICK START",
        "  train secrets set VAST_API_KEY      # Set up API keys",
        "  train host add                      # Add SSH/Colab host",
        "  train storage add                   # Add storage backend",
        "  train run <recipe>                  # Run a recipe",
        "",
        "COMMANDS",
    ]
    for entry in COMMANDS_REGISTRY:
        cmd = entry["command"]
        # Build a short subcommand hint from the subcommand list
        sub_names = []
        seen = set()
        for sc in entry.get("subcommands", []):
            name = sc["name"].split()[0]
            if name.startswith("<") or name.startswith("'") or name.startswith("@"):
                continue
            if name.startswith("-"):
                continue
            if name not in seen:
                sub_names.append(name)
                seen.add(name)
        if sub_names:
            hint = "|".join(sub_names[:3])
            if len(sub_names) > 3:
                hint += "|..."
            left = f"  {cmd} {hint}"
        elif cmd in ("help", "version"):
            left = f"  {cmd}"
        else:
            left = f"  {cmd} <args>"
        lines.append(f"{left:<32s}{entry['help_summary']}")
    lines.extend([
        "",
        "RECIPE DSL (quick reference)",
        "  var NAME = value                    Define a variable",
        "  host gpu = placeholder              Define a host (filled by vast.pick)",
        "  storage output = r2:bucket          Define storage backend",
        "",
        "  vast.pick @gpu num_gpus=1           Pick Vast.ai instance",
        "  vast.wait timeout=5m                Wait for instance ready",
        "  tmux.open @gpu as work              Create tmux session",
        "",
        "  @work > command                     Run command in session",
        "  @work > command &                   Run in background",
        "  wait @work idle timeout=2h          Wait for completion",
        '  notify "Done"                        Send styled notification',
        "",
        "  @gpu:/path -> @output:/path         Transfer files",
        "  vast.stop                           Stop instance",
        "",
        "  Full DSL reference: train recipe syntax",
        "",
        "CONFIG FILES",
        "  ~/.config/tmux-trainsh/",
        "  ├── config.yaml         Main settings",
        "  ├── hosts.yaml          SSH hosts",
        "  ├── storages.yaml       Storage backends",
        "  └── recipes/            Recipe files (.recipe)",
        "",
        'Use "train <command> --help" for command-specific help.',
        "Full documentation: https://github.com/binbinsh/tmux-trainsh",
        "",
    ])
    return "\n".join(lines)


def generate_commands_markdown() -> str:
    """Render COMMANDS_REGISTRY as markdown tables for README."""
    header = "| Command | Description |\n|---------|-------------|"
    sections: List[str] = []

    for entry in COMMANDS_REGISTRY:
        cmd = entry["command"]
        subs = entry.get("subcommands", [])

        sections.append(f"### train {cmd}\n")
        sections.append(entry["description"])
        sections.append("")

        if not subs:
            sections.append(f"`train {cmd}`")
            sections.append("")
            continue

        sections.append(header)
        for sc in subs:
            sections.append(f"| `train {cmd} {sc['name']}` | {sc['description']} |")
        sections.append("")

    return "\n".join(sections)


usage = _generate_usage()

help_text = _generate_help_text()


def option_text() -> str:
    return '''\
--config
default=~/.config/tmux-trainsh/config.yaml
Path to configuration file.

--verbose -v
type=bool-set
Enable verbose output.
'''


def main(args: list[str]) -> Optional[str]:
    """Main entry point for train."""
    from .constants import CONFIG_DIR, RECIPES_DIR

    # Ensure config directories exist
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)

    # No subcommand - show usage
    if len(args) < 2:
        print(BANNER)
        print(usage)
        raise SystemExit(0)

    command = args[1]
    cmd_args = args[2:]

    # Route to subcommand
    if command == "run":
        # Alias: "train run <name>" -> "train recipe run <name>"
        from .commands.recipe import cmd_run
        return cmd_run(cmd_args)
    elif command == "exec":
        from .commands.exec_cmd import main as exec_main
        return exec_main(cmd_args)
    elif command == "vast":
        from .commands.vast import main as vast_main
        return vast_main(cmd_args)
    elif command == "transfer":
        from .commands.transfer import main as transfer_main
        return transfer_main(cmd_args)
    elif command == "recipe":
        from .commands.recipe import main as recipe_main
        return recipe_main(cmd_args)
    elif command == "host":
        from .commands.host import main as host_main
        return host_main(cmd_args)
    elif command == "storage":
        from .commands.storage import main as storage_main
        return storage_main(cmd_args)
    elif command == "secrets":
        from .commands.secrets_cmd import main as secrets_main
        return secrets_main(cmd_args)
    elif command == "colab":
        from .commands.colab import main as colab_main
        return colab_main(cmd_args)
    elif command == "pricing":
        from .commands.pricing import main as pricing_main
        return pricing_main(cmd_args)
    elif command == "update":
        from .commands.update import main as update_main
        return update_main(cmd_args)
    elif command == "config":
        from .commands.config_cmd import main as config_main
        return config_main(cmd_args)
    elif command == "help":
        print(BANNER)
        print(help_text)
        raise SystemExit(0)
    elif command == "version":
        from . import __display_version__
        print(f"tmux-trainsh {__display_version__}")
        raise SystemExit(0)
    else:
        print(f"Unknown command: {command}")
        print(usage)
        raise SystemExit(1)


def cli() -> None:
    """CLI entry point (called by uv/pip installed command)."""
    result = main(sys.argv)
    if result:
        print(result)


if __name__ == "__main__":
    cli()
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["options"] = option_text
    cd["help_text"] = help_text
    cd["short_desc"] = "GPU training workflow automation"
