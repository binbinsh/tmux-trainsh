# kitten-trainsh Management TUI
# Interactive TUI for managing hosts and storage backends

import sys
import os
import tty
import termios
from typing import Optional, List
from dataclasses import dataclass

from ..core.models import Host, Storage, HostType, StorageType, AuthMethod


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


def clear_line():
    print(f"{CSI}2K", end="", flush=True)


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
        if ch == '\x1b':
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                ch3 = sys.stdin.read(1)
                return f"\x1b[{ch3}"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@dataclass
class MenuItem:
    """Menu item for selection lists."""
    key: str
    label: str
    value: any = None


class ManageTUI:
    """
    Interactive TUI for managing hosts, storage backends, and settings.

    Features:
    - List/Add/Edit/Remove hosts
    - List/Add/Edit/Remove storage
    - Configure settings (currency, SSH keys, API keys)
    - Test connections
    """

    def __init__(self, mode: str = "main"):
        """
        Initialize management TUI.

        Args:
            mode: Starting mode - 'main', 'hosts', 'storage', or 'settings'
        """
        self.state = mode
        self.selected_index = 0
        self.message = ""
        self.running = True
        self.hosts = {}
        self.storages = {}
        self.config = {}
        self._load_data()

    def _load_data(self):
        """Load hosts, storage, and config."""
        from ..commands.host import load_hosts
        from ..commands.storage import load_storages
        from ..config import load_config

        self.hosts = load_hosts()
        self.storages = load_storages()
        self.config = load_config()

    def _save_hosts(self):
        """Save hosts to config."""
        from ..commands.host import save_hosts
        save_hosts(self.hosts)

    def _save_storages(self):
        """Save storages to config."""
        from ..commands.storage import save_storages
        save_storages(self.storages)

    def _save_config(self):
        """Save config."""
        from ..config import save_config
        save_config(self.config)

    def run(self):
        """Run the management TUI."""
        hide_cursor()
        try:
            while self.running:
                self._draw()
                self._handle_input()
        finally:
            show_cursor()
            clear_screen()

    def _draw(self):
        """Draw current state."""
        clear_screen()
        rows, cols = get_terminal_size()

        # Header
        move_cursor(1, 1)
        title = {
            "main": " Configuration Manager ",
            "hosts": " Host Manager ",
            "storage": " Storage Manager ",
            "settings": " Settings ",
            "add_host": " Add Host ",
            "edit_host": " Edit Host ",
            "add_storage": " Add Storage ",
            "edit_storage": " Edit Storage ",
        }.get(self.state, " Manager ")
        print(reverse(title.center(cols)), end="")

        # State-specific drawing
        if self.state == "main":
            self._draw_main_menu()
        elif self.state == "hosts":
            self._draw_hosts_list()
        elif self.state == "storage":
            self._draw_storage_list()
        elif self.state == "settings":
            self._draw_settings()
        elif self.state == "add_host":
            self._draw_add_host()
        elif self.state == "edit_host":
            self._draw_edit_host()
        elif self.state == "add_storage":
            self._draw_add_storage()
        elif self.state == "edit_storage":
            self._draw_edit_storage()

        # Message
        if self.message:
            move_cursor(rows - 2, 1)
            print(yellow(self.message), end="")
            self.message = ""

        # Footer
        move_cursor(rows, 1)
        self._draw_footer(cols)

    def _draw_footer(self, cols: int):
        """Draw footer with help text."""
        footers = {
            "main": " [↑↓] Navigate  [Enter] Select  [q] Quit ",
            "hosts": " [↑↓] Navigate  [a] Add  [e] Edit  [d] Delete  [t] Test  [b] Back  [q] Quit ",
            "storage": " [↑↓] Navigate  [a] Add  [e] Edit  [d] Delete  [t] Test  [b] Back  [q] Quit ",
            "settings": " [↑↓] Navigate  [Enter] Edit  [b] Back  [q] Quit ",
        }
        footer = footers.get(self.state, " [b] Back  [q] Quit ")
        print(reverse(footer.ljust(cols)), end="")

    def _draw_main_menu(self):
        """Draw main menu."""
        move_cursor(3, 2)
        print(bold("Select a category:"))
        move_cursor(4, 2)
        print("-" * 40)

        menu_items = [
            ("Hosts", f"{len(self.hosts)} configured"),
            ("Storage", f"{len(self.storages)} configured"),
            ("Settings", "API keys, SSH, Currency"),
        ]

        for i, (name, desc) in enumerate(menu_items):
            move_cursor(6 + i * 2, 4)
            if i == self.selected_index:
                print(reverse(f" {name} ".ljust(30)), end="")
            else:
                print(f" {name}", end="")
            move_cursor(6 + i * 2, 36)
            print(dim(desc), end="")

    def _draw_hosts_list(self):
        """Draw hosts list."""
        move_cursor(3, 2)
        print(bold("Configured Hosts:"))
        move_cursor(4, 2)
        print("-" * 70)

        if not self.hosts:
            move_cursor(6, 4)
            print(dim("No hosts configured."))
            move_cursor(7, 4)
            print(dim("Press [a] to add a new host."))
            return

        hosts_list = list(self.hosts.items())
        for i, (name, host) in enumerate(hosts_list):
            move_cursor(5 + i, 4)
            status = ""
            if host.vast_instance_id:
                status = yellow(f" [vast #{host.vast_instance_id}]")

            line = f"{name:<15} {host.username}@{host.hostname}:{host.port}{status}"

            if i == self.selected_index:
                print(reverse(f" {line} ".ljust(68)), end="")
            else:
                print(f" {green(name):<25} {host.username}@{host.hostname}:{host.port}{status}", end="")

    def _draw_storage_list(self):
        """Draw storage list."""
        move_cursor(3, 2)
        print(bold("Configured Storage Backends:"))
        move_cursor(4, 2)
        print("-" * 60)

        if not self.storages:
            move_cursor(6, 4)
            print(dim("No storage backends configured."))
            move_cursor(7, 4)
            print(dim("Press [a] to add a new storage backend."))
            return

        storages_list = list(self.storages.items())
        for i, (name, storage) in enumerate(storages_list):
            move_cursor(5 + i, 4)
            default_mark = yellow(" (default)") if storage.is_default else ""
            line = f"{name:<15} {storage.type.value}{default_mark}"

            if i == self.selected_index:
                print(reverse(f" {line} ".ljust(56)), end="")
            else:
                print(f" {cyan(name):<25} {storage.type.value}{default_mark}", end="")

    def _draw_add_host(self):
        """Draw add host form."""
        # Form is handled in _handle_add_host
        pass

    def _draw_edit_host(self):
        """Draw edit host form."""
        # Form is handled in _handle_edit_host
        pass

    def _draw_add_storage(self):
        """Draw add storage form."""
        # Form is handled in _handle_add_storage
        pass

    def _draw_edit_storage(self):
        """Draw edit storage form."""
        # Form is handled in _handle_edit_storage
        pass

    def _draw_settings(self):
        """Draw settings menu."""
        from ..core.secrets import get_secrets_manager
        from ..constants import SecretKeys

        move_cursor(3, 2)
        print(bold("Settings:"))
        move_cursor(4, 2)
        print("-" * 60)

        secrets = get_secrets_manager()

        # Build settings list
        settings_items = [
            ("defaults.ssh_key_path", "Default SSH Key", self.config.get("defaults", {}).get("ssh_key_path", "~/.ssh/id_rsa")),
            ("defaults.transfer_method", "Transfer Method", self.config.get("defaults", {}).get("transfer_method", "rsync")),
            ("ui.currency", "Currency", self.config.get("ui", {}).get("currency", "USD")),
            ("ui.show_costs", "Show Costs", str(self.config.get("ui", {}).get("show_costs", True))),
            ("vast.default_image", "Vast Default Image", self.config.get("vast", {}).get("default_image", "")[:30]),
            ("vast.default_disk_gb", "Vast Default Disk (GB)", str(self.config.get("vast", {}).get("default_disk_gb", 50))),
        ]

        # API Keys section
        api_keys = [
            (SecretKeys.VAST_API_KEY, "Vast.ai API Key"),
            (SecretKeys.HF_TOKEN, "HuggingFace Token"),
            (SecretKeys.GITHUB_TOKEN, "GitHub Token"),
            (SecretKeys.OPENAI_API_KEY, "OpenAI API Key"),
            (SecretKeys.ANTHROPIC_API_KEY, "Anthropic API Key"),
        ]

        row = 5
        move_cursor(row, 4)
        print(bold("General Settings:"))
        row += 1

        for i, (key, label, value) in enumerate(settings_items):
            move_cursor(row + i, 4)
            display = f"{label:<25} {value}"
            if i == self.selected_index:
                print(reverse(f" {display} ".ljust(56)), end="")
            else:
                print(f" {cyan(label):<35} {value}", end="")

        row += len(settings_items) + 1
        move_cursor(row, 4)
        print(bold("API Keys:"))
        row += 1

        for j, (key, label) in enumerate(api_keys):
            i = len(settings_items) + j
            move_cursor(row + j, 4)
            has_value = secrets.exists(key)
            value = green("Set") if has_value else dim("Not set")
            display = f"{label:<25} {value}"
            if i == self.selected_index:
                print(reverse(f" {display} ".ljust(56)), end="")
            else:
                print(f" {cyan(label):<35} {value}", end="")

        self._settings_items = settings_items
        self._api_keys = api_keys

    def _handle_input(self):
        """Handle keyboard input."""
        ch = getch()

        if ch == 'q':
            self.running = False
            return

        handlers = {
            "main": self._handle_main_menu,
            "hosts": self._handle_hosts_list,
            "storage": self._handle_storage_list,
            "settings": self._handle_settings,
        }

        handler = handlers.get(self.state)
        if handler:
            handler(ch)

    def _handle_main_menu(self, ch: str):
        """Handle main menu input."""
        if ch == '\x1b[A':  # Up
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == '\x1b[B':  # Down
            self.selected_index = min(2, self.selected_index + 1)
        elif ch in ('\r', '\n'):  # Enter
            if self.selected_index == 0:
                self.state = "hosts"
            elif self.selected_index == 1:
                self.state = "storage"
            else:
                self.state = "settings"
            self.selected_index = 0

    def _handle_hosts_list(self, ch: str):
        """Handle hosts list input."""
        hosts_list = list(self.hosts.keys())

        if ch == '\x1b[A' and hosts_list:  # Up
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == '\x1b[B' and hosts_list:  # Down
            self.selected_index = min(len(hosts_list) - 1, self.selected_index + 1)
        elif ch == 'a':  # Add
            self._add_host_interactive()
        elif ch == 'e' and hosts_list:  # Edit
            host_name = hosts_list[self.selected_index]
            self._edit_host_interactive(host_name)
        elif ch == 'd' and hosts_list:  # Delete
            host_name = hosts_list[self.selected_index]
            self._delete_host(host_name)
        elif ch == 't' and hosts_list:  # Test
            host_name = hosts_list[self.selected_index]
            self._test_host(host_name)
        elif ch == 'b':  # Back
            self.state = "main"
            self.selected_index = 0

    def _handle_storage_list(self, ch: str):
        """Handle storage list input."""
        storages_list = list(self.storages.keys())

        if ch == '\x1b[A' and storages_list:  # Up
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == '\x1b[B' and storages_list:  # Down
            self.selected_index = min(len(storages_list) - 1, self.selected_index + 1)
        elif ch == 'a':  # Add
            self._add_storage_interactive()
        elif ch == 'e' and storages_list:  # Edit
            storage_name = storages_list[self.selected_index]
            self._edit_storage_interactive(storage_name)
        elif ch == 'd' and storages_list:  # Delete
            storage_name = storages_list[self.selected_index]
            self._delete_storage(storage_name)
        elif ch == 't' and storages_list:  # Test
            storage_name = storages_list[self.selected_index]
            self._test_storage(storage_name)
        elif ch == 'b':  # Back
            self.state = "main"
            self.selected_index = 1

    def _handle_settings(self, ch: str):
        """Handle settings input."""
        from ..core.secrets import get_secrets_manager
        from ..constants import SecretKeys
        from ..config import set_config_value

        # Rebuild items list
        settings_items = [
            ("defaults.ssh_key_path", "Default SSH Key"),
            ("defaults.transfer_method", "Transfer Method"),
            ("ui.currency", "Currency"),
            ("ui.show_costs", "Show Costs"),
            ("vast.default_image", "Vast Default Image"),
            ("vast.default_disk_gb", "Vast Default Disk (GB)"),
        ]

        api_keys = [
            (SecretKeys.VAST_API_KEY, "Vast.ai API Key"),
            (SecretKeys.HF_TOKEN, "HuggingFace Token"),
            (SecretKeys.GITHUB_TOKEN, "GitHub Token"),
            (SecretKeys.OPENAI_API_KEY, "OpenAI API Key"),
            (SecretKeys.ANTHROPIC_API_KEY, "Anthropic API Key"),
        ]

        total_items = len(settings_items) + len(api_keys)

        if ch == '\x1b[A':  # Up
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == '\x1b[B':  # Down
            self.selected_index = min(total_items - 1, self.selected_index + 1)
        elif ch in ('\r', '\n'):  # Enter - edit
            if self.selected_index < len(settings_items):
                # Edit config setting
                key, label = settings_items[self.selected_index]
                self._edit_config_setting(key, label)
            else:
                # Edit API key
                api_idx = self.selected_index - len(settings_items)
                key, label = api_keys[api_idx]
                self._edit_api_key(key, label)
        elif ch == 'b':  # Back
            self.state = "main"
            self.selected_index = 2

    def _edit_config_setting(self, key: str, label: str):
        """Edit a config setting."""
        from ..config import get_config_value, set_config_value

        show_cursor()
        rows, _ = get_terminal_size()

        current_value = get_config_value(key, "")

        # Special handling for boolean values
        if key == "ui.show_costs":
            move_cursor(rows - 3, 2)
            clear_line()
            print(f"Toggle {label}? Current: {current_value} (y/n): ", end="", flush=True)
            try:
                choice = input().strip().lower()
                if choice == 'y':
                    set_config_value(key, True)
                    self.message = f"Set {label} = True"
                elif choice == 'n':
                    set_config_value(key, False)
                    self.message = f"Set {label} = False"
                self._load_data()  # Reload config
            except (EOFError, KeyboardInterrupt):
                pass
            hide_cursor()
            return

        # Special handling for transfer method
        if key == "defaults.transfer_method":
            options = [("rsync", "rsync"), ("rclone", "rclone")]
            result = self._select_option(options, f"Select {label}:")
            if result:
                set_config_value(key, result)
                self.message = f"Set {label} = {result}"
                self._load_data()
            return

        # Special handling for currency
        if key == "ui.currency":
            options = [
                ("USD", "USD - US Dollar"),
                ("CNY", "CNY - Chinese Yuan"),
                ("EUR", "EUR - Euro"),
                ("GBP", "GBP - British Pound"),
                ("JPY", "JPY - Japanese Yen"),
            ]
            result = self._select_option(options, f"Select {label}:")
            if result:
                set_config_value(key, result)
                self.message = f"Set {label} = {result}"
                self._load_data()
            return

        # Default: text input
        move_cursor(rows - 3, 2)
        clear_line()
        print(f"Enter {label} [{current_value}]: ", end="", flush=True)

        try:
            new_value = input().strip()
            if new_value:
                # Handle numeric values
                if key.endswith("_gb"):
                    new_value = int(new_value)
                set_config_value(key, new_value)
                self.message = f"Set {label} = {new_value}"
                self._load_data()
        except (EOFError, KeyboardInterrupt):
            pass
        except ValueError as e:
            self.message = f"Invalid value: {e}"

        hide_cursor()

    def _edit_api_key(self, key: str, label: str):
        """Edit an API key."""
        from ..core.secrets import get_secrets_manager

        secrets = get_secrets_manager()
        show_cursor()
        clear_screen()
        move_cursor(1, 1)
        print(bold(f"Edit {label}"))
        print("-" * 40)
        print()

        has_value = secrets.exists(key)
        if has_value:
            print(f"Current: {green('Set (hidden)')}")
            print()
            print("Options:")
            print("  1. Update value")
            print("  2. Delete value")
            print("  3. Cancel")
            print()

            try:
                choice = input("Choice [3]: ").strip() or "3"
                if choice == "1":
                    new_value = input(f"Enter new {label}: ").strip()
                    if new_value:
                        secrets.set(key, new_value)
                        self.message = f"Updated {label}"
                elif choice == "2":
                    secrets.delete(key)
                    self.message = f"Deleted {label}"
            except (EOFError, KeyboardInterrupt):
                pass
        else:
            try:
                new_value = input(f"Enter {label}: ").strip()
                if new_value:
                    secrets.set(key, new_value)
                    self.message = f"Set {label}"
            except (EOFError, KeyboardInterrupt):
                pass
            except Exception as e:
                self.message = f"Error: {e}"

        hide_cursor()

    def _input_prompt(self, prompt: str, default: str = "") -> Optional[str]:
        """Show input prompt and get user input."""
        show_cursor()
        rows, _ = get_terminal_size()

        move_cursor(rows - 3, 2)
        clear_line()
        print(prompt, end="", flush=True)

        try:
            value = input()
            hide_cursor()
            return value if value else default
        except (EOFError, KeyboardInterrupt):
            hide_cursor()
            return None

    def _select_option(self, options: List[tuple], prompt: str) -> Optional[str]:
        """Show option selection menu."""
        show_cursor()
        clear_screen()
        move_cursor(1, 1)
        print(bold(prompt))
        print("-" * 40)

        for i, (value, label) in enumerate(options, 1):
            print(f"  {i}. {label}")

        print()
        try:
            choice = input("Enter number: ").strip()
            hide_cursor()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return options[idx][0]
            return None
        except (EOFError, KeyboardInterrupt):
            hide_cursor()
            return None

    def _add_host_interactive(self):
        """Add a new host interactively."""
        show_cursor()
        clear_screen()
        move_cursor(1, 1)
        print(bold("Add New Host"))
        print("-" * 40)
        print()

        try:
            name = input("Host name: ").strip()
            if not name:
                self.message = "Cancelled - name is required."
                hide_cursor()
                return

            hostname = input("Hostname/IP: ").strip()
            if not hostname:
                self.message = "Cancelled - hostname is required."
                hide_cursor()
                return

            port_str = input("Port [22]: ").strip()
            port = int(port_str) if port_str else 22

            username = input("Username [root]: ").strip() or "root"

            print("\nAuth method:")
            print("  1. SSH Key (default)")
            print("  2. SSH Agent")
            print("  3. Password")
            auth_choice = input("Choice [1]: ").strip() or "1"

            auth_method = {
                "1": AuthMethod.KEY,
                "2": AuthMethod.AGENT,
                "3": AuthMethod.PASSWORD,
            }.get(auth_choice, AuthMethod.KEY)

            ssh_key_path = None
            if auth_method == AuthMethod.KEY:
                default_key = "~/.ssh/id_rsa"
                ssh_key_path = input(f"SSH key path [{default_key}]: ").strip() or default_key

            host = Host(
                name=name,
                type=HostType.SSH,
                hostname=hostname,
                port=port,
                username=username,
                auth_method=auth_method,
                ssh_key_path=ssh_key_path,
            )

            self.hosts[name] = host
            self._save_hosts()
            self.message = f"Added host: {name}"

        except (EOFError, KeyboardInterrupt):
            self.message = "Cancelled."

        hide_cursor()

    def _edit_host_interactive(self, host_name: str):
        """Edit a host interactively."""
        host = self.hosts.get(host_name)
        if not host:
            return

        show_cursor()
        clear_screen()
        move_cursor(1, 1)
        print(bold(f"Edit Host: {host_name}"))
        print("-" * 40)
        print()
        print(dim("Press Enter to keep current value."))
        print()

        try:
            hostname = input(f"Hostname [{host.hostname}]: ").strip() or host.hostname

            port_str = input(f"Port [{host.port}]: ").strip()
            port = int(port_str) if port_str else host.port

            username = input(f"Username [{host.username}]: ").strip() or host.username

            current_auth = host.auth_method.value if host.auth_method else "key"
            print(f"\nAuth method (current: {current_auth}):")
            print("  1. SSH Key")
            print("  2. SSH Agent")
            print("  3. Password")
            print("  (Enter to keep)")
            auth_choice = input("Choice: ").strip()

            auth_method = host.auth_method
            if auth_choice:
                auth_method = {
                    "1": AuthMethod.KEY,
                    "2": AuthMethod.AGENT,
                    "3": AuthMethod.PASSWORD,
                }.get(auth_choice, host.auth_method)

            ssh_key_path = host.ssh_key_path
            if auth_method == AuthMethod.KEY:
                current_key = host.ssh_key_path or "~/.ssh/id_rsa"
                new_key = input(f"SSH key path [{current_key}]: ").strip()
                ssh_key_path = new_key if new_key else current_key

            # Update host
            host.hostname = hostname
            host.port = port
            host.username = username
            host.auth_method = auth_method
            host.ssh_key_path = ssh_key_path

            self._save_hosts()
            self.message = f"Updated host: {host_name}"

        except (EOFError, KeyboardInterrupt):
            self.message = "Cancelled."

        hide_cursor()

    def _delete_host(self, host_name: str):
        """Delete a host with confirmation."""
        show_cursor()
        rows, _ = get_terminal_size()

        move_cursor(rows - 3, 2)
        clear_line()

        try:
            confirm = input(f"Delete host '{host_name}'? (y/N): ").strip()
            if confirm.lower() == 'y':
                del self.hosts[host_name]
                self._save_hosts()
                self.message = f"Deleted host: {host_name}"
                # Adjust selection
                if self.selected_index >= len(self.hosts):
                    self.selected_index = max(0, len(self.hosts) - 1)
            else:
                self.message = "Cancelled."
        except (EOFError, KeyboardInterrupt):
            self.message = "Cancelled."

        hide_cursor()

    def _test_host(self, host_name: str):
        """Test connection to a host."""
        host = self.hosts.get(host_name)
        if not host:
            return

        show_cursor()
        rows, _ = get_terminal_size()

        move_cursor(rows - 3, 2)
        clear_line()
        print(f"Testing connection to {host_name}...", end="", flush=True)

        from ..services.ssh import SSHClient
        ssh = SSHClient.from_host(host)

        if ssh.test_connection():
            self.message = f"Connection to {host_name} successful!"
        else:
            self.message = f"Connection to {host_name} failed."

        hide_cursor()

    def _add_storage_interactive(self):
        """Add a new storage interactively."""
        show_cursor()
        clear_screen()
        move_cursor(1, 1)
        print(bold("Add New Storage Backend"))
        print("-" * 40)
        print()

        try:
            name = input("Storage name: ").strip()
            if not name:
                self.message = "Cancelled - name is required."
                hide_cursor()
                return

            print("\nStorage type:")
            print("  1. Local filesystem")
            print("  2. SSH/SFTP")
            print("  3. Google Drive")
            print("  4. Cloudflare R2")
            print("  5. Backblaze B2")
            print("  6. Amazon S3")
            print("  7. Google Cloud Storage")
            print("  8. SMB/CIFS")
            type_choice = input("Choice [1]: ").strip() or "1"

            type_map = {
                "1": StorageType.LOCAL,
                "2": StorageType.SSH,
                "3": StorageType.GOOGLE_DRIVE,
                "4": StorageType.R2,
                "5": StorageType.B2,
                "6": StorageType.S3,
                "7": StorageType.GCS,
                "8": StorageType.SMB,
            }
            storage_type = type_map.get(type_choice, StorageType.LOCAL)

            config = {}

            if storage_type == StorageType.LOCAL:
                path = input("Base path: ").strip()
                config["path"] = path

            elif storage_type == StorageType.SSH:
                host = input("Host: ").strip()
                port_str = input("Port [22]: ").strip()
                port = int(port_str) if port_str else 22
                user = input("Username: ").strip()
                path = input("Base path: ").strip()
                key_path = input("SSH key path [~/.ssh/id_rsa]: ").strip() or "~/.ssh/id_rsa"
                config["host"] = host
                config["port"] = port
                config["user"] = user
                config["path"] = path
                config["key_file"] = key_path

            elif storage_type == StorageType.GOOGLE_DRIVE:
                print("\nGoogle Drive requires rclone setup.")
                print("Run 'rclone config' first, then enter the remote name.")
                remote_name = input("Rclone remote name: ").strip()
                config["remote_name"] = remote_name

            elif storage_type == StorageType.R2:
                account_id = input("Cloudflare Account ID: ").strip()
                bucket = input("Bucket name: ").strip()
                print("\nAccess keys should be stored in secrets.")
                print("Run 'kitty +kitten trainsh secrets set R2_ACCESS_KEY' and 'R2_SECRET_KEY'")
                config["account_id"] = account_id
                config["bucket"] = bucket
                config["endpoint"] = f"https://{account_id}.r2.cloudflarestorage.com"

            elif storage_type == StorageType.B2:
                bucket = input("Bucket name: ").strip()
                print("\nApplication keys should be stored in secrets.")
                print("Run 'kitty +kitten trainsh secrets set B2_KEY_ID' and 'B2_APPLICATION_KEY'")
                config["bucket"] = bucket

            elif storage_type == StorageType.S3:
                bucket = input("Bucket name: ").strip()
                region = input("Region [us-east-1]: ").strip() or "us-east-1"
                endpoint = input("Custom endpoint (optional, for S3-compatible): ").strip()
                print("\nAWS credentials should be stored in secrets.")
                print("Run 'kitty +kitten trainsh secrets set AWS_ACCESS_KEY_ID' and 'AWS_SECRET_ACCESS_KEY'")
                config["bucket"] = bucket
                config["region"] = region
                if endpoint:
                    config["endpoint"] = endpoint

            elif storage_type == StorageType.GCS:
                bucket = input("Bucket name: ").strip()
                config["bucket"] = bucket

            elif storage_type == StorageType.SMB:
                server = input("Server: ").strip()
                share = input("Share name: ").strip()
                username = input("Username: ").strip()
                config["server"] = server
                config["share"] = share
                config["username"] = username

            is_default = input("\nSet as default? (y/N): ").lower() == "y"

            storage = Storage(
                name=name,
                type=storage_type,
                config=config,
                is_default=is_default,
            )

            # If setting as default, unset others
            if is_default:
                for s in self.storages.values():
                    s.is_default = False

            self.storages[name] = storage
            self._save_storages()
            self.message = f"Added storage: {name} ({storage_type.value})"

        except (EOFError, KeyboardInterrupt):
            self.message = "Cancelled."

        hide_cursor()

    def _edit_storage_interactive(self, storage_name: str):
        """Edit a storage interactively."""
        storage = self.storages.get(storage_name)
        if not storage:
            return

        show_cursor()
        clear_screen()
        move_cursor(1, 1)
        print(bold(f"Edit Storage: {storage_name}"))
        print("-" * 40)
        print(f"Type: {storage.type.value}")
        print()
        print(dim("Press Enter to keep current value."))
        print()

        try:
            config = dict(storage.config)

            if storage.type == StorageType.LOCAL:
                current = config.get("path", "")
                path = input(f"Base path [{current}]: ").strip() or current
                config["path"] = path

            elif storage.type == StorageType.SSH:
                for key, label in [
                    ("host", "Host"),
                    ("port", "Port"),
                    ("user", "Username"),
                    ("path", "Base path"),
                    ("key_file", "SSH key path"),
                ]:
                    current = config.get(key, "")
                    value = input(f"{label} [{current}]: ").strip() or current
                    if key == "port" and value:
                        value = int(value)
                    config[key] = value

            elif storage.type == StorageType.GOOGLE_DRIVE:
                current = config.get("remote_name", "")
                remote = input(f"Rclone remote name [{current}]: ").strip() or current
                config["remote_name"] = remote

            elif storage.type == StorageType.R2:
                for key, label in [
                    ("account_id", "Account ID"),
                    ("bucket", "Bucket"),
                    ("endpoint", "Endpoint"),
                ]:
                    current = config.get(key, "")
                    value = input(f"{label} [{current}]: ").strip() or current
                    config[key] = value

            elif storage.type == StorageType.B2:
                current = config.get("bucket", "")
                bucket = input(f"Bucket [{current}]: ").strip() or current
                config["bucket"] = bucket

            elif storage.type == StorageType.S3:
                for key, label in [
                    ("bucket", "Bucket"),
                    ("region", "Region"),
                    ("endpoint", "Endpoint (optional)"),
                ]:
                    current = config.get(key, "")
                    value = input(f"{label} [{current}]: ").strip() or current
                    if value or key != "endpoint":
                        config[key] = value

            elif storage.type == StorageType.GCS:
                current = config.get("bucket", "")
                bucket = input(f"Bucket [{current}]: ").strip() or current
                config["bucket"] = bucket

            elif storage.type == StorageType.SMB:
                for key, label in [
                    ("server", "Server"),
                    ("share", "Share name"),
                    ("username", "Username"),
                ]:
                    current = config.get(key, "")
                    value = input(f"{label} [{current}]: ").strip() or current
                    config[key] = value

            current_default = "yes" if storage.is_default else "no"
            is_default_str = input(f"\nSet as default? (current: {current_default}) (y/n): ").strip()

            if is_default_str.lower() == 'y':
                # Unset other defaults
                for s in self.storages.values():
                    s.is_default = False
                storage.is_default = True
            elif is_default_str.lower() == 'n':
                storage.is_default = False

            storage.config = config
            self._save_storages()
            self.message = f"Updated storage: {storage_name}"

        except (EOFError, KeyboardInterrupt):
            self.message = "Cancelled."

        hide_cursor()

    def _delete_storage(self, storage_name: str):
        """Delete a storage with confirmation."""
        show_cursor()
        rows, _ = get_terminal_size()

        move_cursor(rows - 3, 2)
        clear_line()

        try:
            confirm = input(f"Delete storage '{storage_name}'? (y/N): ").strip()
            if confirm.lower() == 'y':
                del self.storages[storage_name]
                self._save_storages()
                self.message = f"Deleted storage: {storage_name}"
                if self.selected_index >= len(self.storages):
                    self.selected_index = max(0, len(self.storages) - 1)
            else:
                self.message = "Cancelled."
        except (EOFError, KeyboardInterrupt):
            self.message = "Cancelled."

        hide_cursor()

    def _test_storage(self, storage_name: str):
        """Test connection to storage."""
        storage = self.storages.get(storage_name)
        if not storage:
            return

        show_cursor()
        rows, _ = get_terminal_size()

        move_cursor(rows - 3, 2)
        clear_line()
        print(f"Testing storage: {storage_name}...", end="", flush=True)

        import subprocess

        if storage.type == StorageType.LOCAL:
            path = os.path.expanduser(storage.config.get("path", ""))
            if os.path.exists(path):
                self.message = f"Storage {storage_name}: path exists."
            else:
                self.message = f"Storage {storage_name}: path does not exist."

        elif storage.type == StorageType.SSH:
            from ..services.ssh import SSHClient
            host = Host(
                name=storage_name,
                type=HostType.SSH,
                hostname=storage.config.get("host", ""),
                port=storage.config.get("port", 22),
                username=storage.config.get("user", ""),
                ssh_key_path=storage.config.get("key_file"),
            )
            ssh = SSHClient.from_host(host)
            if ssh.test_connection():
                self.message = f"Storage {storage_name}: connection successful!"
            else:
                self.message = f"Storage {storage_name}: connection failed."

        elif storage.type.value in ("gdrive", "r2", "gcs", "b2", "s3"):
            result = subprocess.run(
                ["rclone", "lsd", f"{storage_name}:"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                self.message = f"Storage {storage_name}: connection successful!"
            else:
                self.message = f"Storage {storage_name}: {result.stderr.strip()}"
        else:
            self.message = f"Test not implemented for {storage.type.value}"

        hide_cursor()


def run_manage_tui(mode: str = "main"):
    """Run the management TUI."""
    tui = ManageTUI(mode=mode)
    tui.run()


def run_hosts_tui():
    """Run TUI for host management."""
    run_manage_tui(mode="hosts")


def run_storage_tui():
    """Run TUI for storage management."""
    run_manage_tui(mode="storage")


def run_settings_tui():
    """Run TUI for settings management."""
    run_manage_tui(mode="settings")
