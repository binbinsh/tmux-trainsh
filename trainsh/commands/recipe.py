# tmux-trainsh recipes command
# Python recipe file management

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from ..cli_utils import SubcommandSpec, prompt_input
from ..constants import RECIPE_FILE_EXTENSION, RECIPE_FILE_EXTENSIONS
from .help_catalog import render_command_help, render_top_level_help
from .recipe_templates import get_recipe_template, list_template_names

SUBCOMMAND_SPECS = (
    SubcommandSpec("list", "List user recipes and bundled examples."),
    SubcommandSpec("show", "Inspect one recipe's metadata and rendered steps."),
    SubcommandSpec("new", "Create a recipe file from a bundled template."),
    SubcommandSpec("edit", "Open a recipe file in $EDITOR."),
    SubcommandSpec("remove", "Delete a recipe file after confirmation."),
)

usage = render_command_help("recipe")

RUNTIME_REDIRECTS = {
    "run": "train recipe run",
    "exec": "train recipe exec",
    "resume": "train recipe resume",
    "status": "train recipe status",
    "logs": "train recipe logs",
    "jobs": "train recipe jobs",
    "schedule": "train recipe schedule",
}


def _is_recipe_filename(filename: str) -> bool:
    return any(str(filename).endswith(ext) for ext in RECIPE_FILE_EXTENSIONS)


def _candidate_recipe_paths(root: str, name: str) -> list[str]:
    if _is_recipe_filename(name):
        return [os.path.join(root, name)]
    return [os.path.join(root, f"{name}{RECIPE_FILE_EXTENSION}")]


def get_recipes_dir() -> str:
    """Get the project-local recipes directory path."""
    root = _project_root()
    recipes_dir = root / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    return str(recipes_dir)


def _project_root() -> Path:
    cwd = Path.cwd().resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=1,
            check=False,
        )
    except Exception:
        return cwd
    if result.returncode != 0:
        return cwd
    root = Path(result.stdout.strip() or str(cwd)).expanduser().resolve()
    return root if root.exists() else cwd


def get_examples_dir() -> Optional[str]:
    """Get the bundled examples directory path."""
    import importlib.resources

    try:
        files = importlib.resources.files("trainsh")
        examples_path = files / "examples"
        if examples_path.is_dir():
            return str(examples_path)
    except (AttributeError, TypeError):
        pass

    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    examples_path = os.path.join(package_dir, "examples")
    if os.path.isdir(examples_path):
        return examples_path
    return None


def list_recipes() -> List[str]:
    """List user recipe files."""
    recipes_dir = get_recipes_dir()
    recipes = []
    for filename in os.listdir(recipes_dir):
        if _is_recipe_filename(filename):
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
            if _is_recipe_filename(filename):
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
    if os.path.exists(name) and _is_recipe_filename(name):
        return name

    recipes_dir = get_recipes_dir()
    for test_path in _candidate_recipe_paths(recipes_dir, name):
        if os.path.exists(test_path) and _is_recipe_filename(test_path):
            return test_path

    project_root = str(_project_root())
    for test_path in _candidate_recipe_paths(project_root, name):
        if os.path.exists(test_path) and _is_recipe_filename(test_path):
            return test_path

    if name.startswith("examples/"):
        example_name = name[9:]
        examples_dir = get_examples_dir()
        if examples_dir:
            for test_path in _candidate_recipe_paths(examples_dir, example_name):
                if os.path.exists(test_path) and _is_recipe_filename(test_path):
                    return test_path

    examples_dir = get_examples_dir()
    if examples_dir:
        for test_path in _candidate_recipe_paths(examples_dir, name):
            if os.path.exists(test_path) and _is_recipe_filename(test_path):
                return test_path

    return None


def _path_within(path: str, root: Optional[str]) -> bool:
    if not root:
        return False
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def find_user_recipe(name: str) -> Optional[str]:
    """Find a removable/editable recipe under the user recipes directory only."""
    recipes_dir = get_recipes_dir()
    if os.path.exists(name) and _is_recipe_filename(name):
        candidate = os.path.abspath(name)
        if _is_bundled_example(candidate):
            return None
        if _path_within(candidate, recipes_dir):
            return candidate
        project_root = str(_project_root())
        return candidate if _path_within(candidate, project_root) else None

    for test_path in _candidate_recipe_paths(recipes_dir, name):
        if os.path.exists(test_path) and _is_recipe_filename(test_path):
            return test_path

    project_root = str(_project_root())
    for test_path in _candidate_recipe_paths(project_root, name):
        if os.path.exists(test_path) and _is_recipe_filename(test_path):
            return test_path
    return None


def _is_bundled_example(path: Optional[str]) -> bool:
    examples_dir = get_examples_dir()
    if not path or not examples_dir:
        return False
    return _path_within(path, examples_dir)


def cmd_list(args: List[str]) -> None:
    """List available recipes."""
    del args
    recipes = list_recipes()
    examples = list_examples()

    print("Recipes:")
    if not recipes and not examples:
        print("No recipes found.")
        print(f"Create recipes in: {get_recipes_dir()}")
        return

    if recipes:
        print("User recipes:")
        print("-" * 40)
        for recipe_name in recipes:
            print(f"  {recipe_name.rsplit('.', 1)[0]}")
        print("-" * 40)
        print(f"Total: {len(recipes)} recipes")
        print()

    if examples:
        print("Bundled examples:")
        print("-" * 40)
        for example_name in examples:
            print(f"  {example_name.rsplit('.', 1)[0]}")
        print("-" * 40)
        print(f"Total: {len(examples)} examples")


def cmd_show(args: List[str]) -> None:
    """Show recipe details."""
    if not args:
        print("Usage: train recipe show <name>")
        raise SystemExit(1)

    recipe_path = find_recipe(args[0])
    if not recipe_path:
        print(f"Recipe not found: {args[0]}")
        raise SystemExit(1)

    from ..pyrecipe import load_python_recipe

    try:
        loaded_recipe = load_python_recipe(recipe_path)
        show_steps = [step.raw for step in loaded_recipe.steps]

        print(f"Recipe: {loaded_recipe.name}")
        print()

        if loaded_recipe.variables:
            print("Variables:")
            for key, value in loaded_recipe.variables.items():
                print(f"  {key} = {value}")
            print()

        if loaded_recipe.hosts:
            print("Hosts:")
            for key, value in loaded_recipe.hosts.items():
                if key != "local":
                    print(f"  @{key} = {value}")
            print()

        print(f"Steps ({len(show_steps)}):")
        for index, step in enumerate(show_steps, 1):
            print(f"  {index}. {step}")
    except Exception as exc:
        print(f"Error loading recipe: {exc}")
        raise SystemExit(1)


def cmd_new(args: List[str]) -> None:
    """Create a new recipe from template."""
    if not args:
        print("Usage: train recipe new <name> [--template minimal]")
        raise SystemExit(1)

    name = args[0]
    template_name = "minimal"
    rest_args = args[1:]

    i = 0
    while i < len(rest_args):
        arg = rest_args[i]
        if arg.startswith("--template="):
            template_name = arg.split("=", 1)[1].strip() or template_name
        elif arg == "--template":
            if i + 1 >= len(rest_args):
                print("Missing value for --template")
                raise SystemExit(1)
            i += 1
            template_name = rest_args[i].strip() or template_name
        else:
            print(f"Unknown flag: {arg}")
            print("Usage: train recipe new <name> [--template minimal]")
            raise SystemExit(1)
        i += 1

    if name.endswith(".py"):
        name = f"{os.path.splitext(name)[0]}{RECIPE_FILE_EXTENSION}"
    if not _is_recipe_filename(name):
        name += RECIPE_FILE_EXTENSION

    existing_recipe = find_user_recipe(os.path.splitext(name)[0])
    if existing_recipe is not None:
        print(f"Recipe already exists: {os.path.basename(existing_recipe)}")
        raise SystemExit(1)

    recipe_path = os.path.join(get_recipes_dir(), name)
    if os.path.exists(recipe_path):
        print(f"Recipe already exists: {name}")
        raise SystemExit(1)

    recipe_name = os.path.splitext(name)[0]
    try:
        template = get_recipe_template(template_name, recipe_name)
    except ValueError as exc:
        print(str(exc))
        print(f"Available templates: {', '.join(list_template_names())}")
        raise SystemExit(1)

    with open(recipe_path, "w", encoding="utf-8") as handle:
        handle.write(template)

    print(f"Created recipe: {recipe_path}")
    print(f"Template: {template_name}")
    print("Opening in editor...")
    _open_editor(recipe_path)


def cmd_edit(args: List[str]) -> None:
    """Open recipe in editor."""
    if not args:
        print("Usage: train recipe edit <name>")
        raise SystemExit(1)

    recipe_path = find_user_recipe(args[0])
    if not recipe_path:
        if _is_bundled_example(find_recipe(args[0])):
            print(f"Bundled examples cannot be edited in place: {args[0]}")
            print("Use 'train recipe new <name>' to copy one into your recipes directory.")
            raise SystemExit(1)
        print(f"Recipe not found: {args[0]}")
        print("Use 'train recipe new' to create one.")
        raise SystemExit(1)
    _open_editor(recipe_path)


def cmd_rm(args: List[str]) -> None:
    """Remove a recipe."""
    if not args:
        print("Usage: train recipe remove <name>")
        raise SystemExit(1)

    recipe_path = find_user_recipe(args[0])
    if not recipe_path:
        if _is_bundled_example(find_recipe(args[0])):
            print(f"Bundled examples cannot be removed: {args[0]}")
            print("Use 'train recipe new <name>' to copy one into your recipes directory.")
            raise SystemExit(1)
        print(f"Recipe not found: {args[0]}")
        raise SystemExit(1)

    try:
        confirm = prompt_input(f"Remove recipe '{recipe_path}'? (y/N): ")
        if confirm is None or confirm.lower() != "y":
            print("Cancelled.")
            return
        os.remove(recipe_path)
        print(f"Recipe removed: {recipe_path}")
    except OSError as exc:
        print(f"Failed to remove recipe: {exc}")
        raise SystemExit(1)


def main(args: List[str]) -> Optional[str]:
    """Main entry point for recipe file-management subcommands."""
    if not args:
        print(usage)
        return None
    if args[0] in {"-h", "--help", "help"}:
        print(render_top_level_help())
        return None

    subcommand = args[0]
    subargs = args[1:]
    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "new": cmd_new,
        "edit": cmd_edit,
        "remove": cmd_rm,
    }

    if subcommand in RUNTIME_REDIRECTS:
        print(f"Use '{RUNTIME_REDIRECTS[subcommand]}' instead.")
        raise SystemExit(1)

    handler = commands.get(subcommand)
    if handler is None:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        raise SystemExit(1)

    handler(subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Manage Python recipe files"
    cd["short_desc"] = "Manage Python recipe files"
