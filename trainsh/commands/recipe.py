# kitten-trainsh recipe command
# Recipe execution

import sys
import os
from typing import Optional, List

usage = '''[subcommand] [args...]

Subcommands:
  list             - List available recipes
  run <name>       - Execute a recipe
  show <name>      - Show recipe details
  new <name>       - Create a new recipe from template
  edit <name>      - Open recipe in editor
  logs [exec-id]   - View execution logs
  status [id]      - View running recipe sessions

Recipes are stored in: ~/.config/kitten-trainsh/recipes/
'''


def get_recipes_dir() -> str:
    """Get the recipes directory path."""
    from ..constants import RECIPES_DIR
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    return str(RECIPES_DIR)


def list_recipes() -> List[str]:
    """List all recipe files."""
    recipes_dir = get_recipes_dir()
    recipes = []

    for filename in os.listdir(recipes_dir):
        if filename.endswith(".recipe"):
            recipes.append(filename)

    return sorted(recipes)


def cmd_list(args: List[str]) -> None:
    """List available recipes."""
    recipes = list_recipes()

    if not recipes:
        print("No recipes found.")
        print(f"Create recipes in: {get_recipes_dir()}")
        return

    print("Available recipes:")
    print("-" * 40)

    for recipe in recipes:
        name = recipe.rsplit(".", 1)[0]
        print(f"  {name}")

    print("-" * 40)
    print(f"Total: {len(recipes)} recipes")


def cmd_show(args: List[str]) -> None:
    """Show recipe details."""
    if not args:
        print("Usage: kitty +kitten trainsh recipe show <name>")
        sys.exit(1)

    name = args[0]

    # Find recipe file
    recipe_path = None
    if os.path.exists(name):
        recipe_path = name
    else:
        recipes_dir = get_recipes_dir()
        for ext in [".recipe", ""]:
            test_path = os.path.join(recipes_dir, name + ext)
            if os.path.exists(test_path):
                recipe_path = test_path
                break

    if not recipe_path:
        print(f"Recipe not found: {name}")
        sys.exit(1)

    from ..core.dsl_parser import parse_recipe

    try:
        recipe = parse_recipe(recipe_path)

        print(f"Recipe: {recipe.name}")
        print()

        if recipe.variables:
            print("Variables:")
            for k, v in recipe.variables.items():
                print(f"  {k} = {v}")
            print()

        if recipe.hosts:
            print("Hosts:")
            for k, v in recipe.hosts.items():
                if k != "local":
                    print(f"  @{k} = {v}")
            print()

        print(f"Steps ({len(recipe.steps)}):")
        for i, step in enumerate(recipe.steps, 1):
            print(f"  {i}. [{step.type.value}] {step.raw}")

    except Exception as e:
        print(f"Error loading recipe: {e}")
        sys.exit(1)


def cmd_run(args: List[str]) -> None:
    """Execute a recipe."""
    if not args:
        print("Usage: kitty +kitten trainsh recipe run <name> [options]")
        print()
        print("Options:")
        print("  --no-visual       Run in headless mode")
        print("  --host NAME=HOST  Override host (e.g., --host gpu=vast:12345)")
        print("  --var NAME=VALUE  Override variable")
        print("  --pick-host NAME  Interactively select host from vast.ai")
        sys.exit(1)

    name = args[0]
    rest_args = args[1:]

    # Parse options
    visual = True
    host_overrides = {}
    var_overrides = {}
    pick_hosts = []

    i = 0
    while i < len(rest_args):
        arg = rest_args[i]
        if arg == "--no-visual":
            visual = False
        elif arg == "--host" and i + 1 < len(rest_args):
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
        elif "=" in arg:
            # Shorthand: VAR=value
            key, _, value = arg.partition("=")
            var_overrides[key] = value
        i += 1

    # Interactive host selection
    for host_name in pick_hosts:
        selected = _pick_vast_host(host_name)
        if selected:
            host_overrides[host_name] = selected
        else:
            print(f"No host selected for {host_name}")
            sys.exit(1)

    # Find recipe file
    recipe_path = None
    if os.path.exists(name):
        recipe_path = name
    else:
        recipes_dir = get_recipes_dir()
        for ext in [".recipe", ""]:
            test_path = os.path.join(recipes_dir, name + ext)
            if os.path.exists(test_path):
                recipe_path = test_path
                break

    if not recipe_path:
        print(f"Recipe not found: {name}")
        sys.exit(1)

    from ..core.dsl_executor import run_recipe

    print(f"Running recipe: {os.path.basename(recipe_path)}")
    if visual:
        print("Mode: visual (kitty tabs)")
    else:
        print("Mode: headless")

    if host_overrides:
        print("Host overrides:")
        for k, v in host_overrides.items():
            print(f"  @{k} = {v}")

    if var_overrides:
        print("Variable overrides:")
        for k, v in var_overrides.items():
            print(f"  {k} = {v}")

    print("-" * 40)

    success = run_recipe(
        recipe_path,
        visual=visual,
        host_overrides=host_overrides,
        var_overrides=var_overrides,
    )

    print("-" * 40)
    if success:
        print("Recipe completed successfully!")
    else:
        print("Recipe execution failed.")
        sys.exit(1)


def _pick_vast_host(host_name: str) -> Optional[str]:
    """Interactively pick a vast.ai instance."""
    from ..services.vast_api import get_vast_client

    try:
        client = get_vast_client()
        instances = client.list_instances()

        if not instances:
            print("No vast.ai instances available.")
            return None

        print(f"\nSelect host for @{host_name}:")
        print("-" * 60)
        print(f"{'#':<4} {'ID':<10} {'Status':<10} {'GPU':<20} {'$/hr':<8}")
        print("-" * 60)

        running = [i for i in instances if i.is_running]
        for idx, inst in enumerate(running, 1):
            gpu = inst.gpu_name or "N/A"
            price = f"${inst.dph_total:.3f}" if inst.dph_total else "N/A"
            print(f"{idx:<4} {inst.id:<10} {'running':<10} {gpu:<20} {price:<8}")

        if not running:
            print("No running instances.")
            return None

        print("-" * 60)

        try:
            choice = input(f"Enter number (1-{len(running)}) or instance ID: ").strip()

            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(running):
                    selected = running[num - 1]
                    return f"vast:{selected.id}"
                # Try as instance ID
                for inst in instances:
                    if inst.id == num:
                        return f"vast:{inst.id}"

            print("Invalid selection.")
            return None

        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return None

    except Exception as e:
        print(f"Error listing vast.ai instances: {e}")
        return None


def cmd_new(args: List[str]) -> None:
    """Create a new recipe from template."""
    if not args:
        print("Usage: kitty +kitten trainsh recipe new <name>")
        sys.exit(1)

    name = args[0]
    if not name.endswith(".recipe"):
        name += ".recipe"

    recipe_path = os.path.join(get_recipes_dir(), name)

    if os.path.exists(recipe_path):
        print(f"Recipe already exists: {name}")
        sys.exit(1)

    template = '''# {name}
# Created with kitty +kitten trainsh

---
HOST = your-server
MODEL = llama-7b
---

# Define hosts
@gpu = ${{HOST}}

# Open terminal
> kitty.open @gpu as main

# Run commands
main: echo "Hello from ${{MODEL}}"
main: uv --version

# File transfer example
# ~/local/path -> @gpu:/remote/path

# Wait for pattern
# ? main: "completed" timeout=1h

# Notify when done
> notify "Recipe complete!"
'''

    recipe_name = name.rsplit(".", 1)[0]

    with open(recipe_path, "w") as f:
        f.write(template.format(name=recipe_name))

    print(f"Created recipe: {recipe_path}")
    print("Edit it to add your steps.")


def cmd_edit(args: List[str]) -> None:
    """Open recipe in editor."""
    if not args:
        print("Usage: kitty +kitten trainsh recipe edit <name>")
        sys.exit(1)

    name = args[0]

    # Find recipe file
    recipe_path = None
    if os.path.exists(name):
        recipe_path = name
    else:
        recipes_dir = get_recipes_dir()
        for ext in [".recipe", ""]:
            test_path = os.path.join(recipes_dir, name + ext)
            if os.path.exists(test_path):
                recipe_path = test_path
                break

    if not recipe_path:
        print(f"Recipe not found: {name}")
        print("Use 'kitty +kitten trainsh recipe new' to create one.")
        sys.exit(1)

    editor = os.environ.get("EDITOR", "vim")
    os.system(f'{editor} "{recipe_path}"')


def cmd_logs(args: List[str]) -> None:
    """View execution logs."""
    from ..core.execution_log import ExecutionLogReader

    reader = ExecutionLogReader()

    if not args or args[0] in ("--list", "-l"):
        # List recent executions
        executions = reader.list_executions(limit=20)

        if not executions:
            print("No execution logs found.")
            return

        print("Recent executions:")
        print("-" * 80)
        print(f"{'ID':<12} {'Recipe':<20} {'Started':<24} {'Status':<10} {'Duration'}")
        print("-" * 80)

        for ex in executions:
            exec_id = ex.get("exec_id", "")[:10]
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
            print(f"{exec_id:<12} {recipe:<20} {started:<24} {status:<10} {duration_str}")

        print("-" * 80)
        print(f"Total: {len(executions)} executions")
        print("\nUse 'kitty +kitten trainsh recipe logs <exec-id>' to view details.")

    elif args[0] == "--last":
        # Show last execution
        executions = reader.list_executions(limit=1)
        if not executions:
            print("No execution logs found.")
            return
        _show_execution_details(reader, executions[0]["exec_id"])

    else:
        # Show specific execution
        exec_id = args[0]
        _show_execution_details(reader, exec_id)


def _show_execution_details(reader, exec_id: str) -> None:
    """Show details of a specific execution."""
    from ..core.execution_log import ExecutionLogReader

    summary = reader.get_execution_summary(exec_id)
    if not summary:
        print(f"Execution not found: {exec_id}")
        sys.exit(1)

    print(f"Execution: {summary['exec_id']}")
    print(f"Recipe: {summary['recipe']}")
    print(f"Started: {summary['started']}")
    print(f"Ended: {summary['ended'] or 'N/A'}")

    success = summary.get('success')
    if success is None:
        status = "running"
    elif success:
        status = "success"
    else:
        status = "failed"
    print(f"Status: {status}")

    duration_ms = summary.get('duration_ms', 0)
    if duration_ms:
        print(f"Duration: {duration_ms}ms ({duration_ms / 1000:.2f}s)")

    steps = summary.get("steps", [])
    if steps:
        print(f"\nSteps ({len(steps)}):")
        print("-" * 60)
        for i, step in enumerate(steps, 1):
            step_status = "OK" if step.get("ok") else "FAIL"
            step_duration = step.get("duration_ms", 0)
            error = step.get("error", "")

            line = f"  {i}. [{step_status}] {step.get('step_id', 'unknown')}"
            if step_duration:
                line += f" ({step_duration}ms)"
            print(line)

            if error:
                print(f"      Error: {error}")
        print("-" * 60)


def cmd_status(args: List[str]) -> None:
    """View running recipe sessions."""
    from ..core.session_registry import SessionRegistry

    registry = SessionRegistry()

    if args and args[0] not in ("--list", "-l", "--all", "-a"):
        # Show specific session
        session_id = args[0]
        session = registry.get(session_id)

        if not session:
            # Try to find by partial match
            for s in registry.list_all():
                if s.session_id.startswith(session_id):
                    session = s
                    break

        if not session:
            print(f"Session not found: {session_id}")
            print("Use 'kitty +kitten trainsh recipe status' to list sessions.")
            sys.exit(1)

        _show_session_details(session)
    else:
        # List all sessions
        all_sessions = "--all" in args or "-a" in args
        sessions = registry.list_all() if all_sessions else registry.list_running()

        if not sessions:
            print("No running recipe sessions.")
            print("Run a recipe with 'kitty +kitten trainsh recipe run <name>'")
            return

        print("Recipe Sessions:")
        print("-" * 80)
        print(f"{'ID':<14} {'Recipe':<20} {'Host':<15} {'Status':<10} {'Started':<20}")
        print("-" * 80)

        for session in sessions:
            session_id = session.session_id[:12]
            recipe = session.recipe_name[:18]
            host = (session.host_id or "local")[:13]
            status = session.status[:8]
            started = session.started_at[:18] if session.started_at else "N/A"

            print(f"{session_id:<14} {recipe:<20} {host:<15} {status:<10} {started:<20}")

        print("-" * 80)
        print(f"Total: {len(sessions)} sessions")

        if not all_sessions:
            print("\nUse '--all' to show completed/failed sessions.")


def _show_session_details(session) -> None:
    """Show details of a specific session."""
    from ..services.tmux import TmuxManager

    print(f"Session: {session.session_id}")
    print(f"Recipe: {session.recipe_name}")
    print(f"Host: {session.host_id or 'local'}")
    print(f"Status: {session.status}")
    print(f"Started: {session.started_at}")
    print(f"Tmux Session: {session.tmux_session}")
    print(f"Kitty Window: {session.kitty_window_id or 'N/A'}")
    print("-" * 60)

    # Try to get live output from tmux
    if session.status == "running":
        tmux = TmuxManager()
        if tmux.session_exists(session.tmux_session):
            print("\nLive Output (last 20 lines):")
            output = tmux.capture_pane(session.tmux_session, lines=20)
            for line in output.split("\n"):
                print(f"  {line}")
        else:
            print("\n(Tmux session no longer exists)")
    else:
        print(f"\n(Session {session.status})")


def main(args: List[str]) -> Optional[str]:
    """Main entry point for recipe command."""
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "run": cmd_run,
        "new": cmd_new,
        "edit": cmd_edit,
        "logs": cmd_logs,
        "status": cmd_status,
    }

    if subcommand not in commands:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    commands[subcommand](subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Recipe execution"
    cd["short_desc"] = "Execute automation recipes"
