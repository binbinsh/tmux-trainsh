# tmux-trainsh recipe command
# Recipe execution

import sys
import os
from typing import Optional, List

from ..cli_utils import prompt_input

usage = '''[subcommand] [args...]

Subcommands:
  list             - List available recipes
  run <name>       - Execute a recipe
  resume <name>    - Resume a failed/interrupted recipe
  show <name>      - Show recipe details
  new <name>       - Create a new recipe from template
  edit <name>      - Open recipe in editor
  rm <name>        - Remove a recipe
  logs [exec-id]   - View execution logs
  status [id]      - View running recipe sessions
  jobs             - List all job states

Recipes are stored in: ~/.config/tmux-trainsh/recipes/
'''


def get_recipes_dir() -> str:
    """Get the recipes directory path."""
    from ..constants import RECIPES_DIR
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    return str(RECIPES_DIR)


def get_examples_dir() -> Optional[str]:
    """Get the bundled examples directory path."""
    import importlib.resources
    try:
        # Python 3.9+
        files = importlib.resources.files("trainsh")
        examples_path = files / "examples"
        if examples_path.is_dir():
            return str(examples_path)
    except (AttributeError, TypeError):
        pass

    # Fallback: check relative to this file
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    examples_path = os.path.join(package_dir, "examples")
    if os.path.isdir(examples_path):
        return examples_path

    return None


def list_recipes() -> List[str]:
    """List all recipe files."""
    recipes_dir = get_recipes_dir()
    recipes = []

    for filename in os.listdir(recipes_dir):
        if filename.endswith(".recipe"):
            recipes.append(filename)

    return sorted(recipes)


def list_examples() -> List[str]:
    """List bundled example recipe files."""
    examples_dir = get_examples_dir()
    if not examples_dir:
        return []

    examples = []
    try:
        for filename in os.listdir(examples_dir):
            if filename.endswith(".recipe"):
                examples.append(filename)
    except OSError:
        return []

    return sorted(examples)


def _open_editor(path: str) -> None:
    """Open file in user's editor."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    os.system(f'{editor} "{path}"')


def find_recipe(name: str) -> Optional[str]:
    """Find a recipe file by name. Searches user recipes first, then examples."""
    # Check if it's an absolute/relative path that exists
    if os.path.exists(name):
        return name

    # Check user recipes directory
    recipes_dir = get_recipes_dir()
    for ext in [".recipe", ""]:
        test_path = os.path.join(recipes_dir, name + ext)
        if os.path.exists(test_path):
            return test_path

    # Check if name starts with "examples/" prefix
    if name.startswith("examples/"):
        example_name = name[9:]  # Remove "examples/" prefix
        examples_dir = get_examples_dir()
        if examples_dir:
            for ext in [".recipe", ""]:
                test_path = os.path.join(examples_dir, example_name + ext)
                if os.path.exists(test_path):
                    return test_path

    # Also check examples directory without prefix (fallback)
    examples_dir = get_examples_dir()
    if examples_dir:
        for ext in [".recipe", ""]:
            test_path = os.path.join(examples_dir, name + ext)
            if os.path.exists(test_path):
                return test_path

    return None


def cmd_list(args: List[str]) -> None:
    """List available recipes."""
    recipes = list_recipes()
    examples = list_examples()

    if not recipes and not examples:
        print("No recipes found.")
        print(f"Create recipes in: {get_recipes_dir()}")
        return

    if recipes:
        print("User recipes:")
        print("-" * 40)

        for recipe in recipes:
            name = recipe.rsplit(".", 1)[0]
            print(f"  {name}")

        print("-" * 40)
        print(f"Total: {len(recipes)} recipes")
        print()

    if examples:
        print("Bundled examples:")
        print("-" * 40)

        for example in examples:
            name = example.rsplit(".", 1)[0]
            print(f"  {name}")

        print("-" * 40)
        print(f"Total: {len(examples)} examples")


def cmd_show(args: List[str]) -> None:
    """Show recipe details."""
    if not args:
        print("Usage: train recipe show <name>")
        sys.exit(1)

    name = args[0]
    recipe_path = find_recipe(name)

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
        print("Usage: train run <name> [options]")
        print("       train recipe run <name> [options]")
        print()
        print("Options:")
        print("  --host NAME=HOST  Override host (e.g., --host gpu=vast:12345)")
        print("  --var NAME=VALUE  Override variable")
        print("  --pick-host NAME  Interactively select host from vast.ai")
        sys.exit(1)

    name = args[0]
    rest_args = args[1:]

    # Parse options
    host_overrides = {}
    var_overrides = {}
    pick_hosts = []

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

    # Find recipe file (searches user recipes and bundled examples)
    recipe_path = find_recipe(name)

    if not recipe_path:
        print(f"Recipe not found: {name}")
        sys.exit(1)

    from ..core.dsl_executor import run_recipe

    print(f"Running recipe: {os.path.basename(recipe_path)}")
    print("Commands run in remote tmux sessions (survive SSH disconnect)")

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
    from ..utils.vast_formatter import format_instance_header, format_instance_row, get_currency_settings

    try:
        client = get_vast_client()
        instances = client.list_instances()

        if not instances:
            print("No vast.ai instances available.")
            return None

        running = [i for i in instances if i.is_running]
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
        print("Usage: train recipe new <name>")
        sys.exit(1)

    name = args[0]
    if not name.endswith(".recipe"):
        name += ".recipe"

    recipe_path = os.path.join(get_recipes_dir(), name)

    if os.path.exists(recipe_path):
        print(f"Recipe already exists: {name}")
        sys.exit(1)

    template = '''# {name}
# Created with tmux-trainsh

# Variables (reference with $NAME or ${{NAME}})
var HOST = your-server
var MODEL = llama-7b

# Hosts (reference with @NAME)
host gpu = $HOST

# Open tmux session
tmux.open @gpu as main

# Run commands (session name, not host)
@main > echo "Hello from $MODEL"
@main > uv --version

# File transfer example
# ./local/path -> @gpu:/remote/path

# Wait for pattern
# wait @main "completed" timeout=1h

# Notify when done
notify "Recipe complete!"

# Close session when done
# tmux.close @main
'''

    recipe_name = name.rsplit(".", 1)[0]

    with open(recipe_path, "w") as f:
        f.write(template.format(name=recipe_name))

    print(f"Created recipe: {recipe_path}")
    print("Opening in editor...")
    _open_editor(recipe_path)


def cmd_edit(args: List[str]) -> None:
    """Open recipe in editor."""
    if not args:
        print("Usage: train recipe edit <name>")
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
        print("Use 'train recipe new' to create one.")
        sys.exit(1)

    _open_editor(recipe_path)


def cmd_rm(args: List[str]) -> None:
    """Remove a recipe."""
    if not args:
        print("Usage: train recipe rm <name>")
        sys.exit(1)

    name = args[0]

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

    try:
        confirm = prompt_input(f"Remove recipe '{recipe_path}'? (y/N): ")
        if confirm is None or confirm.lower() != "y":
            print("Cancelled.")
            return
        os.remove(recipe_path)
        print(f"Recipe removed: {recipe_path}")
    except OSError as e:
        print(f"Failed to remove recipe: {e}")
        sys.exit(1)


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
        print("\nUse 'train recipe logs <job-id>' to view details.")

    elif args[0] == "--last":
        # Show last execution
        executions = reader.list_executions(limit=1)
        if not executions:
            print("No execution logs found.")
            return
        _show_execution_details(reader, executions[0]["job_id"])

    else:
        # Show specific execution
        job_id = args[0]
        _show_execution_details(reader, job_id)


def _show_execution_details(reader, job_id: str) -> None:
    """Show details of a specific execution."""
    from ..core.execution_log import ExecutionLogReader

    summary = reader.get_execution_summary(job_id)
    if not summary:
        print(f"Execution not found: {job_id}")
        sys.exit(1)

    print(f"Job ID: {summary['job_id']}")
    print(f"Recipe: {summary['recipe']}")
    print(f"Recipe Path: {summary.get('recipe_path', 'N/A')}")
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

    # Show variables
    variables = summary.get("variables", {})
    if variables:
        print(f"\nVariables ({len(variables)}):")
        for k, v in list(variables.items())[:10]:
            print(f"  {k} = {v[:50] if len(str(v)) > 50 else v}")
        if len(variables) > 10:
            print(f"  ... and {len(variables) - 10} more")

    # Show hosts
    hosts = summary.get("hosts", {})
    if hosts:
        print(f"\nHosts ({len(hosts)}):")
        for k, v in hosts.items():
            print(f"  @{k} = {v}")

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

    # Show log file location
    from ..core.execution_log import get_jobs_dir
    jobs_dir = get_jobs_dir()
    # Find log file with timestamp prefix
    log_files = list(jobs_dir.glob(f"*_{job_id}.jsonl.gz")) + list(jobs_dir.glob(f"*_{job_id}.jsonl"))
    if not log_files:
        # Try old format without timestamp
        log_files = list(jobs_dir.glob(f"{job_id}.jsonl.gz")) + list(jobs_dir.glob(f"{job_id}.jsonl"))
    if log_files:
        print(f"\nLog file: {log_files[0]}")


def cmd_status(args: List[str]) -> None:
    """View running recipe sessions."""
    from ..core.job_state import JobStateManager
    from ..core.tmux_session import session_exists

    state_manager = JobStateManager()

    if args and args[0] not in ("--list", "-l", "--all", "-a"):
        # Show specific job
        job_id = args[0]
        job = state_manager.load(job_id)

        if not job:
            # Try to find by partial match
            for j in state_manager.list_all():
                if j.job_id.startswith(job_id):
                    job = j
                    break

        if not job:
            print(f"Job not found: {job_id}")
            print("Use 'train recipe status' to list jobs.")
            sys.exit(1)

        _show_job_details(job)
    else:
        # List all jobs
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


def _show_job_details(job) -> None:
    """Show details of a specific job."""
    from ..core.job_state import get_tmux_session_name
    from ..core.tmux_session import TmuxSession, session_exists

    print(f"Job ID: {job.job_id}")
    print(f"Recipe: {job.recipe_name}")
    print(f"Recipe Path: {job.recipe_path}")
    print(f"Status: {job.status}")
    print(f"Progress: Step {job.current_step + 1}/{job.total_steps}")
    print(f"Created: {job.created_at}")
    print(f"Updated: {job.updated_at}")

    tmux_session_name = get_tmux_session_name(job.job_id)
    print(f"Tmux Session: {tmux_session_name}")

    if job.hosts:
        print("\nHosts:")
        for name, spec in job.hosts.items():
            print(f"  @{name} = {spec}")

    if job.vast_instance_id:
        print(f"\nVast.ai Instance: {job.vast_instance_id}")
        if job.vast_start_time:
            print(f"  Started: {job.vast_start_time}")

    print("-" * 60)

    # Try to get live output from tmux
    if job.status == "running" and session_exists(tmux_session_name):
        try:
            tmux = TmuxSession(tmux_session_name, create=False)
            panes = tmux.list_panes()
            if panes:
                print("\nActive Panes:")
                for pane in panes:
                    print(f"  {pane.pane_id}: {pane.window_name} ({pane.current_command})")

                # Capture output from first pane
                print("\nLive Output (last 20 lines):")
                output = tmux.capture(panes[0].pane_id, start=-20)
                for line in output.split("\n"):
                    print(f"  {line}")
        except Exception as e:
            print(f"\n(Could not capture output: {e})")
    elif job.status == "running":
        print("\n(Tmux session no longer exists)")
    else:
        print(f"\n(Job {job.status})")


def cmd_resume(args: List[str]) -> None:
    """Resume a failed/interrupted recipe."""
    if not args:
        print("Usage: train recipe resume <name>")
        print()
        print("Options:")
        print("  --check           Only check remote status, don't resume")
        sys.exit(1)

    name = args[0]
    rest_args = args[1:]

    # Parse options
    check_only = False
    for arg in rest_args:
        if arg == "--check":
            check_only = True

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
    from ..core.dsl_parser import parse_recipe
    from ..core.job_state import JobStateManager, check_remote_condition

    # Check for resumable state
    state_manager = JobStateManager()
    saved_state = state_manager.find_resumable(os.path.abspath(recipe_path))

    if not saved_state:
        print(f"No resumable state found for: {name}")
        print("Use 'recipe run' to start a fresh execution.")
        sys.exit(1)

    print(f"Job ID: {saved_state.job_id}")
    print(f"Recipe: {os.path.basename(recipe_path)}")
    print(f"Status: {saved_state.status}")
    print(f"Progress: Step {saved_state.current_step + 1}/{saved_state.total_steps}")
    print(f"Last updated: {saved_state.updated_at}")

    if saved_state.hosts:
        print("Saved hosts:")
        for k, v in saved_state.hosts.items():
            print(f"  @{k} = {v}")

    # Check if current step is a wait step with file condition
    recipe = parse_recipe(recipe_path)
    current_step_idx = saved_state.current_step

    if current_step_idx < len(recipe.steps):
        current_step = recipe.steps[current_step_idx]

        # Check if it's a wait step with a file condition
        if current_step.condition and current_step.condition.startswith("file:"):
            target = current_step.target
            host_spec = saved_state.hosts.get(target)

            if host_spec:
                print(f"\nChecking remote condition...")

                # Interpolate the condition with saved variables
                condition = current_step.condition
                for var_name, var_value in saved_state.variables.items():
                    condition = condition.replace(f"${{{var_name}}}", var_value)

                met, msg = check_remote_condition(host_spec, condition)

                if met:
                    print(f"  {msg}")
                    print(f"  Training appears to be COMPLETE!")
                    print(f"  The wait condition at step {current_step_idx + 1} is already satisfied.")

                    if check_only:
                        print("\nRun without --check to resume and complete remaining steps.")
                        return

                    # Update state to skip the wait step
                    saved_state.current_step = current_step_idx + 1
                    state_manager.save(saved_state)
                    print(f"  Advancing to step {current_step_idx + 2}")
                else:
                    print(f"  {msg}")
                    print(f"  Training is still in progress (or failed).")

                    if check_only:
                        return

    if check_only:
        print("\nRun without --check to resume execution.")
        return

    print("-" * 40)

    success = run_recipe(
        recipe_path,
        resume=True,
    )

    print("-" * 40)
    if success:
        print("Recipe completed successfully!")
    else:
        print("Recipe execution failed.")
        print(f"Run 'recipe resume {name}' to retry from the failed step.")
        sys.exit(1)


def cmd_jobs(args: List[str]) -> None:
    """List all job states."""
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
        "resume": cmd_resume,
        "new": cmd_new,
        "edit": cmd_edit,
        "rm": cmd_rm,
        "logs": cmd_logs,
        "status": cmd_status,
        "jobs": cmd_jobs,
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
