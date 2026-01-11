# kitten-trainsh Recipe TUI
# Interactive recipe configuration and execution

import sys
import os
import tty
import termios
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from ..core.dsl_parser import parse_recipe, DSLRecipe
from ..commands.recipe import get_recipes_dir, list_recipes


# ANSI escape codes
ESC = "\033"
CSI = f"{ESC}["

def clear_screen():
    print(f"{CSI}2J{CSI}H", end="", flush=True)

def move_cursor(row: int, col: int):
    print(f"{CSI}{row};{col}H", end="", flush=True)

def hide_cursor():
    print(f"{CSI}?25l", end="", flush=True)

def show_cursor():
    print(f"{CSI}?25h", end="", flush=True)

def bold(text: str) -> str:
    return f"{CSI}1m{text}{CSI}0m"

def dim(text: str) -> str:
    return f"{CSI}2m{text}{CSI}0m"

def reverse(text: str) -> str:
    return f"{CSI}7m{text}{CSI}0m"

def color(text: str, fg: int) -> str:
    return f"{CSI}{fg}m{text}{CSI}0m"

def green(text: str) -> str:
    return color(text, 32)

def yellow(text: str) -> str:
    return color(text, 33)

def cyan(text: str) -> str:
    return color(text, 36)

def red(text: str) -> str:
    return color(text, 31)


def get_terminal_size() -> tuple[int, int]:
    """Get terminal size (rows, cols)."""
    try:
        size = os.get_terminal_size()
        return size.lines, size.columns
    except OSError:
        return 24, 80


def getch() -> str:
    """Read a single character from stdin."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        # Handle escape sequences
        if ch == '\x1b':
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                ch3 = sys.stdin.read(1)
                return f"\x1b[{ch3}"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@dataclass
class RecipeConfig:
    """Configuration for running a recipe."""
    recipe_path: str = ""
    recipe: Optional[DSLRecipe] = None
    variables: Dict[str, str] = field(default_factory=dict)
    hosts: Dict[str, str] = field(default_factory=dict)
    visual: bool = True


class RecipeTUI:
    """
    Interactive TUI for configuring and running recipes.

    Flow:
    1. Select recipe
    2. Configure variables
    3. Select hosts (from vast.ai or manual)
    4. Review and run
    """

    def __init__(self):
        self.config = RecipeConfig()
        self.state = "select_recipe"  # select_recipe, config_vars, config_hosts, review
        self.selected_index = 0
        self.message = ""
        self.running = True

    def run(self) -> Optional[RecipeConfig]:
        """Run the TUI and return configuration if confirmed."""
        hide_cursor()
        try:
            while self.running:
                self._draw()
                self._handle_input()

            if self.config.recipe:
                return self.config
            return None
        finally:
            show_cursor()
            clear_screen()

    def _draw(self):
        """Draw current state."""
        clear_screen()
        rows, cols = get_terminal_size()

        # Header
        move_cursor(1, 1)
        print(reverse(f" Recipe Runner ".center(cols)), end="")

        # State-specific drawing
        if self.state == "select_recipe":
            self._draw_recipe_list()
        elif self.state == "config_vars":
            self._draw_var_config()
        elif self.state == "config_hosts":
            self._draw_host_config()
        elif self.state == "review":
            self._draw_review()

        # Message
        if self.message:
            move_cursor(rows - 2, 1)
            print(yellow(self.message), end="")
            self.message = ""

        # Footer
        move_cursor(rows, 1)
        if self.state == "select_recipe":
            print(reverse(" [↑↓] Navigate  [Enter] Select  [q] Quit ".ljust(cols)), end="")
        elif self.state in ("config_vars", "config_hosts"):
            print(reverse(" [↑↓] Navigate  [Enter] Edit  [n] Next  [b] Back  [q] Quit ".ljust(cols)), end="")
        elif self.state == "review":
            print(reverse(" [Enter] Run  [b] Back  [q] Quit ".ljust(cols)), end="")

    def _draw_recipe_list(self):
        """Draw recipe selection list."""
        move_cursor(3, 2)
        print(bold("Select a recipe:"))
        move_cursor(4, 2)
        print("-" * 50)

        recipes = list_recipes()

        if not recipes:
            move_cursor(6, 4)
            print(dim("No recipes found."))
            move_cursor(7, 4)
            print(dim(f"Create recipes in: {get_recipes_dir()}"))
            return

        for i, recipe in enumerate(recipes):
            move_cursor(5 + i, 4)
            name = recipe.rsplit(".", 1)[0]
            if i == self.selected_index:
                print(reverse(f" {name} ".ljust(40)), end="")
            else:
                print(f" {name}", end="")

    def _draw_var_config(self):
        """Draw variable configuration."""
        move_cursor(3, 2)
        print(bold(f"Configure variables for: {self.config.recipe.name}"))
        move_cursor(4, 2)
        print("-" * 50)

        if not self.config.variables:
            move_cursor(6, 4)
            print(dim("No variables defined."))
            return

        vars_list = list(self.config.variables.items())
        for i, (name, value) in enumerate(vars_list):
            move_cursor(5 + i, 4)
            display = f"{name} = {value}"
            if i == self.selected_index:
                print(reverse(f" {display} ".ljust(50)), end="")
            else:
                print(f" {cyan(name)} = {value}", end="")

    def _draw_host_config(self):
        """Draw host configuration."""
        move_cursor(3, 2)
        print(bold(f"Configure hosts for: {self.config.recipe.name}"))
        move_cursor(4, 2)
        print("-" * 50)

        hosts = {k: v for k, v in self.config.hosts.items() if k != "local"}

        if not hosts:
            move_cursor(6, 4)
            print(dim("No hosts to configure."))
            return

        hosts_list = list(hosts.items())
        for i, (name, value) in enumerate(hosts_list):
            move_cursor(5 + i, 4)
            display = f"@{name} = {value}"
            if i == self.selected_index:
                print(reverse(f" {display} ".ljust(50)), end="")
            else:
                print(f" {green('@' + name)} = {value}", end="")

        # Show vast.ai hint
        move_cursor(5 + len(hosts_list) + 1, 4)
        print(dim("Press [v] to select from vast.ai instances"))

    def _draw_review(self):
        """Draw review screen before running."""
        move_cursor(3, 2)
        print(bold(f"Review: {self.config.recipe.name}"))
        move_cursor(4, 2)
        print("-" * 50)

        row = 6

        # Variables
        if self.config.variables:
            move_cursor(row, 4)
            print(bold("Variables:"))
            row += 1
            for name, value in self.config.variables.items():
                move_cursor(row, 6)
                print(f"{cyan(name)} = {value}")
                row += 1
            row += 1

        # Hosts
        hosts = {k: v for k, v in self.config.hosts.items() if k != "local"}
        if hosts:
            move_cursor(row, 4)
            print(bold("Hosts:"))
            row += 1
            for name, value in hosts.items():
                move_cursor(row, 6)
                print(f"{green('@' + name)} = {value}")
                row += 1
            row += 1

        # Steps preview
        move_cursor(row, 4)
        print(bold(f"Steps ({len(self.config.recipe.steps)}):"))
        row += 1
        for i, step in enumerate(self.config.recipe.steps[:5]):
            move_cursor(row, 6)
            step_text = step.raw[:50] + "..." if len(step.raw) > 50 else step.raw
            print(dim(f"{i+1}. {step_text}"))
            row += 1

        if len(self.config.recipe.steps) > 5:
            move_cursor(row, 6)
            print(dim(f"... and {len(self.config.recipe.steps) - 5} more"))
            row += 1

        # Mode
        row += 1
        move_cursor(row, 4)
        mode = "Visual (kitty tabs)" if self.config.visual else "Headless"
        print(f"Mode: {bold(mode)}")

    def _handle_input(self):
        """Handle keyboard input."""
        ch = getch()

        if ch == 'q':
            self.config.recipe = None
            self.running = False
            return

        if self.state == "select_recipe":
            self._handle_recipe_select(ch)
        elif self.state == "config_vars":
            self._handle_var_config(ch)
        elif self.state == "config_hosts":
            self._handle_host_config(ch)
        elif self.state == "review":
            self._handle_review(ch)

    def _handle_recipe_select(self, ch: str):
        """Handle input in recipe selection state."""
        recipes = list_recipes()
        if not recipes:
            return

        if ch == '\x1b[A':  # Up
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == '\x1b[B':  # Down
            self.selected_index = min(len(recipes) - 1, self.selected_index + 1)
        elif ch in ('\r', '\n'):  # Enter
            recipe_file = recipes[self.selected_index]
            recipe_path = os.path.join(get_recipes_dir(), recipe_file)
            self.config.recipe_path = recipe_path
            self.config.recipe = parse_recipe(recipe_path)
            self.config.variables = dict(self.config.recipe.variables)
            self.config.hosts = dict(self.config.recipe.hosts)
            self.state = "config_vars"
            self.selected_index = 0

    def _handle_var_config(self, ch: str):
        """Handle input in variable config state."""
        vars_list = list(self.config.variables.keys())
        if not vars_list:
            if ch == 'n':
                self.state = "config_hosts"
                self.selected_index = 0
            elif ch == 'b':
                self.state = "select_recipe"
                self.selected_index = 0
            return

        if ch == '\x1b[A':  # Up
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == '\x1b[B':  # Down
            self.selected_index = min(len(vars_list) - 1, self.selected_index + 1)
        elif ch in ('\r', '\n'):  # Enter - edit variable
            var_name = vars_list[self.selected_index]
            new_value = self._input_prompt(f"Enter value for {var_name}: ", self.config.variables[var_name])
            if new_value is not None:
                self.config.variables[var_name] = new_value
        elif ch == 'n':
            self.state = "config_hosts"
            self.selected_index = 0
        elif ch == 'b':
            self.state = "select_recipe"
            self.selected_index = 0

    def _handle_host_config(self, ch: str):
        """Handle input in host config state."""
        hosts = {k: v for k, v in self.config.hosts.items() if k != "local"}
        hosts_list = list(hosts.keys())

        if ch == '\x1b[A' and hosts_list:  # Up
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == '\x1b[B' and hosts_list:  # Down
            self.selected_index = min(len(hosts_list) - 1, self.selected_index + 1)
        elif ch in ('\r', '\n') and hosts_list:  # Enter - edit host
            host_name = hosts_list[self.selected_index]
            new_value = self._input_prompt(f"Enter host for @{host_name}: ", self.config.hosts[host_name])
            if new_value is not None:
                self.config.hosts[host_name] = new_value
        elif ch == 'v' and hosts_list:  # Select from vast.ai
            host_name = hosts_list[self.selected_index]
            vast_host = self._select_vast_host()
            if vast_host:
                self.config.hosts[host_name] = vast_host
        elif ch == 'n':
            self.state = "review"
            self.selected_index = 0
        elif ch == 'b':
            self.state = "config_vars"
            self.selected_index = 0

    def _handle_review(self, ch: str):
        """Handle input in review state."""
        if ch in ('\r', '\n'):  # Enter - run
            self.running = False
        elif ch == 'b':
            self.state = "config_hosts"
            self.selected_index = 0
        elif ch == 'm':  # Toggle mode
            self.config.visual = not self.config.visual

    def _input_prompt(self, prompt: str, default: str = "") -> Optional[str]:
        """Show input prompt and get user input."""
        show_cursor()
        rows, cols = get_terminal_size()

        move_cursor(rows - 3, 1)
        print(" " * cols, end="")  # Clear line
        move_cursor(rows - 3, 2)
        print(prompt, end="", flush=True)

        # Simple line input
        try:
            value = input() or default
            hide_cursor()
            return value
        except (EOFError, KeyboardInterrupt):
            hide_cursor()
            return None

    def _select_vast_host(self) -> Optional[str]:
        """Select from vast.ai instances."""
        from ..services.vast_api import get_vast_client

        show_cursor()
        clear_screen()
        move_cursor(1, 1)
        print(bold("Select vast.ai instance:"))
        print("-" * 60)

        try:
            client = get_vast_client()
            instances = client.list_instances()
            running = [i for i in instances if i.is_running]

            if not running:
                print("\nNo running instances.")
                input("Press Enter to continue...")
                hide_cursor()
                return None

            print(f"{'#':<4} {'ID':<10} {'GPU':<20} {'$/hr':<8}")
            print("-" * 60)

            for idx, inst in enumerate(running, 1):
                gpu = inst.gpu_name or "N/A"
                price = f"${inst.dph_total:.3f}" if inst.dph_total else "N/A"
                print(f"{idx:<4} {inst.id:<10} {gpu:<20} {price:<8}")

            print("-" * 60)
            choice = input(f"Enter number (1-{len(running)}): ").strip()

            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(running):
                    inst = running[num - 1]
                    if inst.ssh_host and inst.ssh_port:
                        hide_cursor()
                        return f"root@{inst.ssh_host} -p {inst.ssh_port}"

            hide_cursor()
            return None

        except Exception as e:
            print(f"\nError: {e}")
            input("Press Enter to continue...")
            hide_cursor()
            return None


def run_recipe_tui() -> bool:
    """
    Run the recipe TUI and execute the selected recipe.

    Returns:
        True if recipe was executed successfully
    """
    tui = RecipeTUI()
    config = tui.run()

    if not config or not config.recipe:
        print("Cancelled.")
        return False

    # Build overrides
    host_overrides = {k: v for k, v in config.hosts.items() if k != "local"}
    var_overrides = config.variables

    # Run
    from ..core.dsl_executor import run_recipe

    print(f"\nRunning recipe: {config.recipe.name}")
    print("-" * 40)

    return run_recipe(
        config.recipe_path,
        visual=config.visual,
        host_overrides=host_overrides,
        var_overrides=var_overrides,
    )
