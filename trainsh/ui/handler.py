# kitten-trainsh TUI handler
# Kitty TUI interface for GPU training workflow automation

import sys
import os
import re
from typing import Optional, List, Any, Dict, Callable
from dataclasses import dataclass, field

# ============================================================================
# Kitty TUI Integration
# ============================================================================

KITTY_TUI_AVAILABLE = False
KittyHandler = object  # Fallback for type checking

try:
    from kittens.tui.handler import Handler as KittyHandler
    from kittens.tui.loop import Loop
    from kittens.tui.operations import styled, MouseTracking
    KITTY_TUI_AVAILABLE = True
except ImportError:
    def styled(text: str, **kwargs) -> str:
        return text
    MouseTracking = None


def is_kitty() -> bool:
    """Check if running inside kitty terminal."""
    return os.environ.get('TERM_PROGRAM') == 'kitty' or 'KITTY_PID' in os.environ


# ============================================================================
# Kitty Remote Control
# ============================================================================

class KittyRemote:
    """Remote control interface for kitty terminal."""

    def __init__(self):
        self.available = is_kitty()
        self._boss = None

    def _get_boss(self):
        """Get kitty boss for remote control (works from within kitten)."""
        if self._boss is None:
            try:
                from kitty.remote_control import create_basic_command, encode_send
                self._use_rc_protocol = True
            except ImportError:
                self._use_rc_protocol = False
        return self._boss

    def _send_rc_command(self, cmd: str, payload: dict) -> tuple[str, int]:
        """Send remote control command via TTY escape sequences."""
        import json
        import sys

        # Build the remote control command
        data = {"cmd": cmd, "version": [0, 14, 2]}
        data.update(payload)

        # Encode as base64 JSON
        import base64
        json_data = json.dumps(data)
        b64_data = base64.b64encode(json_data.encode()).decode()

        # Send via escape sequence (kitty's remote control protocol)
        # Format: ESC P @ kitty-cmd <base64> ESC \
        escape_seq = f"\x1bP@kitty-cmd{b64_data}\x1b\\"

        try:
            # Write to TTY
            sys.stdout.write(escape_seq)
            sys.stdout.flush()
            return "", 0
        except Exception as e:
            return str(e), 1

    def _run_kitten(self, *args) -> tuple[str, int]:
        """Run kitty @ command for remote control.

        Returns:
            Tuple of (output_or_error, return_code)
        """
        import subprocess
        import os

        cmd = ['kitty', '@']

        # Check for KITTY_LISTEN_ON (socket path)
        listen_on = os.environ.get('KITTY_LISTEN_ON')
        if listen_on:
            cmd.extend(['--to', listen_on])

        cmd.extend(list(args))

        # Use 'kitty @' for remote control
        # IMPORTANT: Do not use capture_output=True in TUI context
        # kitty @ needs access to /dev/tty for communication
        # Open /dev/tty explicitly to allow kitty remote control to work
        try:
            tty_fd = os.open('/dev/tty', os.O_RDWR)
            result = subprocess.run(
                cmd,
                stdin=tty_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            os.close(tty_fd)
            # Return stderr if command failed, stdout otherwise
            output = result.stderr if result.returncode != 0 else result.stdout
            return output, result.returncode
        except OSError as e:
            # Fallback: try without explicit TTY (may work with KITTY_LISTEN_ON)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )
            output = result.stderr if result.returncode != 0 else result.stdout
            return output, result.returncode

    def launch_ssh(self, host: str, user: str = "root", port: int = 22,
                   key_file: Optional[str] = None, title: Optional[str] = None,
                   remote_cmd: Optional[str] = None) -> tuple[bool, str]:
        """Launch SSH in new kitty tab.

        Args:
            host: The hostname to connect to
            user: SSH username
            port: SSH port
            key_file: Path to SSH key file
            title: Tab title
            remote_cmd: Command to execute on the remote host after connecting

        Returns:
            Tuple of (success, error_message)
        """
        if not self.available:
            return False, "Not running in kitty terminal"

        # Build SSH command
        ssh_args = ['ssh']
        if user:
            ssh_args.extend(['-l', user])
        if port != 22:
            ssh_args.extend(['-p', str(port)])
        if key_file:
            ssh_args.extend(['-i', os.path.expanduser(key_file)])
        # Allocate TTY for interactive commands like tmux
        if remote_cmd:
            ssh_args.append('-t')
        ssh_args.append(host)
        if remote_cmd:
            ssh_args.append(remote_cmd)

        # Try using subprocess to call kitty @ launch
        # This works when allow_remote_control=yes because kitty
        # detects KITTY_PID and uses TTY for communication
        args = ['launch', '--type', 'tab']
        if title:
            args.extend(['--title', title])
        args.extend(ssh_args)

        output, code = self._run_kitten(*args)
        if code == 0:
            return True, ""
        return False, output or f"kitty @ launch failed with code {code}"

    def get_remote_tmux_sessions(self, host: str, user: str = "root", port: int = 22,
                                  key_file: Optional[str] = None) -> tuple[list[str], str]:
        """Fetch the list of tmux sessions on a remote host.

        Args:
            host: The hostname to connect to
            user: SSH username
            port: SSH port
            key_file: Path to SSH key file

        Returns:
            Tuple of (list of session names, error_message)
        """
        # Build SSH command to list tmux sessions
        ssh_cmd = ['ssh', '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes']
        if user:
            ssh_cmd.extend(['-l', user])
        if port != 22:
            ssh_cmd.extend(['-p', str(port)])
        if key_file:
            ssh_cmd.extend(['-i', os.path.expanduser(key_file)])
        ssh_cmd.append(host)
        ssh_cmd.append('tmux list-sessions -F "#{session_name}" 2>/dev/null || echo ""')

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                sessions = [s.strip() for s in result.stdout.strip().split('\n') if s.strip()]
                return sessions, ""
            return [], result.stderr or "Failed to list tmux sessions"
        except subprocess.TimeoutExpired:
            return [], "SSH connection timed out"
        except Exception as e:
            return [], str(e)


# Global remote instance
_remote: Optional[KittyRemote] = None

def get_remote() -> KittyRemote:
    global _remote
    if _remote is None:
        _remote = KittyRemote()
    return _remote


# ============================================================================
# Form Components
# ============================================================================

@dataclass
class FormField:
    """A form field definition."""
    name: str
    label: str
    field_type: str = "text"  # text, password, select, number
    value: str = ""
    options: List[tuple] = field(default_factory=list)  # For select: [(value, label), ...]
    required: bool = False
    placeholder: str = ""


@dataclass
class ListItem:
    """An item in a list view."""
    id: str
    title: str
    subtitle: str = ""
    data: Any = None


class MenuItem:
    """A menu item."""
    def __init__(self, key: str, label: str, description: str = "", action: str = ""):
        self.key = key
        self.label = label
        self.description = description
        self.action = action


# ============================================================================
# Kitty TUI Handler
# ============================================================================

if KITTY_TUI_AVAILABLE:
    class TrainshKittyHandler(KittyHandler):
        """TUI handler using kitty's TUI framework."""

        use_alternate_screen = True
        mouse_tracking = MouseTracking.buttons_only

        def __init__(self) -> None:
            # View state
            self.current_view = "main"
            self.previous_view = "main"
            self.message = ""
            self.message_type = "info"  # info, success, error

            # Main menu
            self.selected_index = 0
            self.menu_items: List[MenuItem] = []

            # List view state
            self.list_items: List[ListItem] = []
            self.list_selected = 0
            self.list_scroll = 0

            # Form state
            self.form_title = ""
            self.form_fields: List[FormField] = []
            self.form_field_index = 0
            self.form_cursor_pos = 0
            self.form_callback: Optional[Callable] = None
            self.form_mode = "navigate"  # navigate, edit

            # Dialog state
            self.dialog_title = ""
            self.dialog_message = ""
            self.dialog_options: List[str] = []
            self.dialog_selected = 0
            self.dialog_callback: Optional[Callable] = None

            # Async loading state for Vast.ai
            self._vast_instances: List[Any] = []
            self._vast_loading = False
            self._vast_loaded = False
            self._vast_load_thread: Optional[Any] = None
            self._vast_error = ""

            # Status monitoring state for Vast.ai instance start/stop
            self._vast_monitoring_id: Optional[int] = None
            self._vast_monitoring_status = ""

            # Pending SSH connection params for tmux session selection
            self._pending_ssh: Dict[str, Any] = {}

        # ====================================================================
        # Utilities
        # ====================================================================

        def _pad_line(self, text: str, width: int, fill: str = " ") -> str:
            """Pad line to width, accounting for ANSI codes."""
            ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
            visible_text = ansi_escape.sub('', text)
            visible_len = len(visible_text)
            if visible_len < width:
                return text + fill * (width - visible_len)
            return text

        def _goto(self, row: int, col: int) -> None:
            """Move cursor to (row, col). Row 0 is top, col 0 is left."""
            self.cmd.set_cursor_position(col, row)

        def _create_menu(self) -> List[MenuItem]:
            return [
                MenuItem("g", "General", "Settings & preferences", "settings"),
                MenuItem("h", "Hosts", "SSH hosts & Vast.ai instances", "hosts"),
                MenuItem("s", "Storage", "Storage backends", "storage"),
                MenuItem("r", "Recipes", "Run automation workflows", "recipes"),
                MenuItem("k", "Secrets", "Manage API keys", "secrets"),
                MenuItem("?", "Help", "Show keyboard shortcuts", "help"),
            ]

        def _show_message(self, msg: str, msg_type: str = "info") -> None:
            """Show a status message."""
            self.message = msg
            self.message_type = msg_type

        # ====================================================================
        # Form Methods
        # ====================================================================

        def _show_form(self, title: str, fields: List[FormField],
                       callback: Callable[[Dict[str, str]], None]) -> None:
            """Show a form for input."""
            self.previous_view = self.current_view
            self.current_view = "form"
            self.form_title = title
            self.form_fields = fields
            self.form_field_index = 0
            self.form_cursor_pos = len(fields[0].value) if fields else 0
            self.form_callback = callback
            self.form_mode = "navigate"
            self.draw_screen()

        def _form_submit(self) -> None:
            """Submit the form."""
            if self.form_callback:
                data = {f.name: f.value for f in self.form_fields}
                self.form_callback(data)
            self.current_view = self.previous_view
            self.draw_screen()

        def _form_cancel(self) -> None:
            """Cancel the form."""
            self.current_view = self.previous_view
            self.draw_screen()

        # ====================================================================
        # Dialog Methods
        # ====================================================================

        def _show_dialog(self, title: str, message: str, options: List[str],
                         callback: Callable[[int], None]) -> None:
            """Show a dialog with options."""
            self.previous_view = self.current_view
            self.current_view = "dialog"
            self.dialog_title = title
            self.dialog_message = message
            self.dialog_options = options
            self.dialog_selected = 0
            self.dialog_callback = callback
            self.draw_screen()

        # ====================================================================
        # Lifecycle
        # ====================================================================

        def initialize(self) -> None:
            self.menu_items = self._create_menu()
            self.cmd.set_cursor_visible(False)
            self.draw_screen()

        def finalize(self) -> None:
            self.cmd.set_cursor_visible(True)

        # ====================================================================
        # Async Vast.ai Loading
        # ====================================================================

        def _start_vast_load(self) -> None:
            """Start loading Vast.ai instances in background thread."""
            if self._vast_loading or self._vast_loaded:
                return

            self._vast_loading = True
            self._vast_instances = []
            self._vast_error = ""

            import threading

            def load_vast():
                try:
                    from ..services.vast_api import get_vast_client
                    client = get_vast_client()
                    instances = client.list_instances()
                    self._vast_instances = instances
                    self._vast_error = ""
                except Exception as e:
                    self._vast_instances = []
                    self._vast_error = str(e)
                finally:
                    self._vast_loading = False
                    self._vast_loaded = True
                    # Schedule redraw on main thread
                    try:
                        self.asyncio_loop.call_soon_threadsafe(self._on_vast_loaded)
                    except Exception:
                        pass

            self._vast_load_thread = threading.Thread(target=load_vast, daemon=True)
            self._vast_load_thread.start()

        def _on_vast_loaded(self) -> None:
            """Called when Vast.ai loading completes."""
            if self.current_view == "hosts":
                self.draw_screen()

        def _reset_vast_cache(self) -> None:
            """Reset Vast.ai cache to force reload."""
            self._vast_instances = []
            self._vast_loaded = False
            self._vast_loading = False

        # ====================================================================
        # Draw Methods
        # ====================================================================

        def draw_screen(self) -> None:
            if self.current_view == "main":
                self._draw_main()
            elif self.current_view == "vast":
                self._draw_vast()
            elif self.current_view == "hosts":
                self._draw_hosts()
            elif self.current_view == "storage":
                self._draw_storage()
            elif self.current_view == "recipes":
                self._draw_recipes()
            elif self.current_view == "secrets":
                self._draw_secrets()
            elif self.current_view == "settings":
                self._draw_settings()
            elif self.current_view == "help":
                self._draw_help()
            elif self.current_view == "form":
                self._draw_form()
            elif self.current_view == "dialog":
                self._draw_dialog()
            elif self.current_view == "host_add":
                self._draw_host_add()
            elif self.current_view == "storage_add":
                self._draw_storage_add()
            elif self.current_view == "secret_edit":
                self._draw_secret_edit()

        def _draw_header(self, title: str) -> None:
            """Draw the header bar."""
            sz = self.screen_size
            self._goto(0, 0)
            header = styled(f" kitten-trainsh | {title} ", reverse=True)
            self.print(self._pad_line(header, sz.cols))

        def _draw_footer(self, keys: str) -> None:
            """Draw the footer bar."""
            sz = self.screen_size
            self._goto(sz.rows - 1, 0)
            footer = styled(f" {keys} ", reverse=True)
            self.print(self._pad_line(footer, sz.cols))

        def _draw_message(self) -> None:
            """Draw status message if any."""
            if self.message:
                sz = self.screen_size
                self._goto(sz.rows - 3, 2)
                color = "green" if self.message_type == "success" else \
                        "red" if self.message_type == "error" else "yellow"
                self.print(styled(self.message, fg=color))
                self.message = ""

        @KittyHandler.atomic_update
        def _draw_main(self) -> None:
            self.cmd.clear_screen()
            sz = self.screen_size

            self._draw_header("Main Menu")

            self._goto(2, 2)
            self.print(styled("Welcome to kitten-trainsh", bold=True))
            self._goto(3, 2)
            self.print("GPU training workflow automation")

            for i, item in enumerate(self.menu_items):
                self._goto(5 + i, 4)
                key_display = styled(f"[{item.key}]", fg="cyan")
                if i == self.selected_index:
                    line = f"  {key_display} {styled(item.label, bold=True)} "
                    self.print(styled(line, reverse=True))
                else:
                    self.print(f"  {key_display} {item.label}")

            self._draw_message()
            self._draw_footer("q:Quit  j/k:Navigate  Enter:Select")

        @KittyHandler.atomic_update
        def _draw_vast(self) -> None:
            self.cmd.clear_screen()
            sz = self.screen_size

            self._draw_header("Vast.ai Dashboard")

            try:
                from ..services.vast_api import get_vast_client
                from ..services.pricing import load_pricing_settings, format_currency
                from ..config import load_config
                client = get_vast_client()
                instances = client.list_instances()

                settings = load_pricing_settings()
                config = load_config()
                # Read display currency from config.toml (ui.currency), fallback to pricing.json
                display_curr = config.get("ui", {}).get("currency", settings.display_currency)
                rates = settings.exchange_rates

                if not instances:
                    self._goto(2, 2)
                    self.print("No instances found.")
                else:
                    # Show both USD and converted currency if different
                    if display_curr != "USD":
                        header = f"{'ID':>10}  {'Status':>10}  {'GPU':>15}  {'$/hr':>8}  {display_curr + '/hr':>10}"
                    else:
                        header = f"{'ID':>10}  {'Status':>10}  {'GPU':>15}  {'$/hr':>8}"

                    self._goto(2, 2)
                    self.print(styled(header, bold=True))
                    self._goto(3, 2)
                    self.print("-" * len(header))

                    for i, inst in enumerate(instances[:10]):
                        self._goto(4 + i, 2)
                        status = inst.actual_status or "unknown"
                        sc = "green" if status == "running" else "yellow" if status == "loading" else "red"
                        usd_price = inst.dph_total or 0

                        if display_curr != "USD":
                            converted = rates.convert(usd_price, "USD", display_curr)
                            self.print(f"{inst.id:>10}  {styled(status, fg=sc):>20}  "
                                       f"{(inst.gpu_name or 'N/A'):>15}  ${usd_price:>7.3f}  "
                                       f"{format_currency(converted, display_curr):>10}")
                        else:
                            self.print(f"{inst.id:>10}  {styled(status, fg=sc):>20}  "
                                       f"{(inst.gpu_name or 'N/A'):>15}  ${usd_price:>7.3f}")

                    self._goto(15, 2)
                    self.print(f"Total: {len(instances)} instances")

            except Exception as e:
                self._goto(4, 2)
                self.print(styled(f"Error: {e}", fg="red"))

            self._draw_message()
            self._draw_footer("b:Back  r:Refresh  q:Quit")

        @KittyHandler.atomic_update
        def _draw_hosts(self) -> None:
            self.cmd.clear_screen()
            sz = self.screen_size

            self._draw_header("Hosts")

            from ..commands.host import load_hosts
            from ..config import load_config
            hosts = load_hosts()

            # Load currency settings for Vast.ai price display
            config = load_config()
            display_curr = "USD"
            rates = None
            try:
                from ..services.pricing import load_pricing_settings, format_currency, ExchangeRates
                settings = load_pricing_settings()
                display_curr = config.get("ui", {}).get("currency", settings.display_currency)
                rates = ExchangeRates()
            except Exception:
                pass

            # Build list items: configured hosts first, then Vast.ai instances
            self.list_items = []
            self._vast_section_start = 0  # Track where Vast.ai section starts

            # Add configured hosts
            if hosts:
                for name, h in hosts.items():
                    self.list_items.append(
                        ListItem(name, name, f"{h.username}@{h.hostname}:{h.port}", h)
                    )

            self._vast_section_start = len(self.list_items)

            # Start async loading of Vast.ai instances if not already done
            if not self._vast_loaded and not self._vast_loading:
                self._start_vast_load()

            # Use cached Vast.ai instances
            vast_instances = self._vast_instances

            for inst in vast_instances:
                status = inst.actual_status or "unknown"
                gpu = inst.gpu_name or "N/A"
                subtitle = f"[{status}] {gpu}"
                # Store instance data with a marker
                self.list_items.append(
                    ListItem(f"vast:{inst.id}", f"vast-{inst.id}", subtitle, ("vast", inst))
                )

            row = 2
            self._goto(row, 2)
            self.print(styled("Configured Hosts:", bold=True))
            row += 1
            self._goto(row, 2)
            self.print("-" * 60)
            row += 1

            if not hosts:
                self._goto(row, 2)
                self.print("  (No configured hosts. Press 'a' to add one.)")
                row += 1
            else:
                for i in range(self._vast_section_start):
                    item = self.list_items[i]
                    self._goto(row, 2)
                    if i == self.list_selected:
                        self.print(styled(f"> {item.title:<18} {item.subtitle}", reverse=True))
                    else:
                        self.print(f"  {item.title:<18} {item.subtitle}")
                    row += 1

            # Vast.ai section
            row += 1
            self._goto(row, 2)
            self.print(styled("Vast.ai Instances:", bold=True))
            row += 1
            self._goto(row, 2)
            self.print("-" * 60)
            row += 1

            if self._vast_loading:
                self._goto(row, 2)
                self.print(styled("  Loading Vast.ai instances...", fg="yellow"))
                row += 1
            elif self._vast_error:
                self._goto(row, 2)
                # Truncate error message if too long
                err_msg = self._vast_error
                if len(err_msg) > 50:
                    err_msg = err_msg[:50] + "..."
                self.print(styled(f"  Error: {err_msg}", fg="red"))
                row += 1
            elif not vast_instances:
                self._goto(row, 2)
                self.print("  (No Vast.ai instances)")
                row += 1
            else:
                for i in range(self._vast_section_start, len(self.list_items)):
                    item = self.list_items[i]
                    _, inst = item.data
                    status = inst.actual_status or "unknown"

                    # Check if this instance is being monitored for startup
                    is_monitoring = (hasattr(self, '_vast_monitoring_id') and
                                     self._vast_monitoring_id == inst.id)

                    if is_monitoring:
                        # Show animated status indicator
                        monitoring_status = getattr(self, '_vast_monitoring_status', 'starting')
                        status_styled = styled(f"[{monitoring_status}...]", fg="yellow", bold=True)
                    else:
                        sc = "green" if status == "running" else "yellow" if status == "loading" else "red"
                        status_styled = styled(f"[{status}]", fg=sc)

                    gpu = inst.gpu_name or "N/A"

                    # Format price with currency conversion
                    price = ""
                    if inst.dph_total:
                        if rates and display_curr != "USD":
                            converted = rates.convert(inst.dph_total, "USD", display_curr)
                            price = f"{format_currency(converted, display_curr)}/hr"
                        else:
                            price = f"${inst.dph_total:.3f}/hr"

                    self._goto(row, 2)
                    if i == self.list_selected:
                        line = f"> {item.title:<12} {status_styled} {gpu:<15} {price}"
                        self.print(styled(line, reverse=True))
                    else:
                        self.print(f"  {item.title:<12} {status_styled} {gpu:<15} {price}")
                    row += 1

            self._draw_message()
            self._draw_footer("a:Add  d:Delete  s:SSH  S:Start  X:Stop  r:Refresh  b:Back  q:Quit")

        @KittyHandler.atomic_update
        def _draw_storage(self) -> None:
            self.cmd.clear_screen()
            sz = self.screen_size

            self._draw_header("Storage")

            from ..commands.storage import load_storages
            storages = load_storages()

            self._goto(2, 2)
            self.print(styled("Storage Backends:", bold=True))
            self._goto(3, 2)
            self.print("-" * 50)

            if not storages:
                self._goto(4, 2)
                self.print("No storage backends. Press 'a' to add one.")
            else:
                self.list_items = [
                    ListItem(name, name, f"{s.type.value}", s)
                    for name, s in storages.items()
                ]
                for i, item in enumerate(self.list_items[:15]):
                    self._goto(4 + i, 2)
                    default_mark = styled("*", fg="green") if item.data.is_default else " "
                    if i == self.list_selected:
                        self.print(styled(f"> {item.title:<18} {item.subtitle:<10} {default_mark}", reverse=True))
                    else:
                        self.print(f"  {item.title:<18} {item.subtitle:<10} {default_mark}")

            self._draw_message()
            self._draw_footer("a:Add  d:Delete  *:SetDefault  b:Back  q:Quit")

        @KittyHandler.atomic_update
        def _draw_recipes(self) -> None:
            self.cmd.clear_screen()
            self._draw_header("Recipes")

            from ..commands.recipe import list_recipes
            recipes = list_recipes()

            self._goto(2, 2)
            self.print(styled("Available Recipes:", bold=True))
            self._goto(3, 2)
            self.print("-" * 50)

            if not recipes:
                self._goto(4, 2)
                self.print("No recipes found.")
            else:
                for i, recipe in enumerate(recipes[:15]):
                    self._goto(4 + i, 4)
                    name = recipe.rsplit('.', 1)[0]
                    if i == self.list_selected:
                        self.print(styled(f"> {name}", reverse=True))
                    else:
                        self.print(f"  {name}")

            self._draw_message()
            self._draw_footer("Enter:Run  b:Back  q:Quit")

        @KittyHandler.atomic_update
        def _draw_secrets(self) -> None:
            self.cmd.clear_screen()
            self._draw_header("Secrets")

            from ..core.secrets import get_secrets_manager
            from ..constants import SecretKeys

            secrets = get_secrets_manager()
            keys = [
                (SecretKeys.VAST_API_KEY, "Vast.ai API Key"),
                (SecretKeys.HF_TOKEN, "HuggingFace Token"),
                (SecretKeys.GITHUB_TOKEN, "GitHub Token"),
                (SecretKeys.R2_ACCESS_KEY, "R2 Access Key"),
                (SecretKeys.R2_SECRET_KEY, "R2 Secret Key"),
                (SecretKeys.B2_KEY_ID, "B2 Key ID"),
                (SecretKeys.B2_APPLICATION_KEY, "B2 App Key"),
                (SecretKeys.AWS_ACCESS_KEY_ID, "AWS Access Key"),
                (SecretKeys.AWS_SECRET_ACCESS_KEY, "AWS Secret Key"),
                (SecretKeys.OPENAI_API_KEY, "OpenAI API Key"),
                (SecretKeys.ANTHROPIC_API_KEY, "Anthropic API Key"),
            ]

            # Use cached existence check to avoid calling keyring every render
            if not hasattr(self, '_secrets_cache') or not self._secrets_cache:
                self._secrets_cache = {key: secrets.exists(key) for key, _ in keys}

            self.list_items = [
                ListItem(key, label, "Set" if self._secrets_cache.get(key, False) else "Not set", key)
                for key, label in keys
            ]

            self._goto(2, 2)
            self.print(styled("API Keys & Credentials:", bold=True))
            self._goto(3, 2)
            self.print("-" * 50)

            for i, item in enumerate(self.list_items):
                self._goto(4 + i, 4)
                status = styled("Set", fg="green") if item.subtitle == "Set" else styled("Not set", fg="red")
                if i == self.list_selected:
                    self.print(styled(f"> {item.title:<25} ", reverse=True) + status)
                else:
                    self.print(f"  {item.title:<25} {status}")

            self._draw_message()
            self._draw_footer("Enter:Set  d:Delete  b:Back  q:Quit")

        @KittyHandler.atomic_update
        def _draw_settings(self) -> None:
            self.cmd.clear_screen()
            self._draw_header("Settings")

            from ..config import load_config
            config = load_config()

            # Store settings config keys for editing
            self._settings_keys = [
                ("defaults.ssh_key_path", "SSH Key", config.get("defaults", {}).get("ssh_key_path", "~/.ssh/id_rsa")),
                ("defaults.transfer_method", "Transfer Method", config.get("defaults", {}).get("transfer_method", "rsync")),
                ("ui.currency", "Currency", config.get("ui", {}).get("currency", "USD")),
                ("ui.show_costs", "Show Costs", str(config.get("ui", {}).get("show_costs", True))),
                ("vast.default_image", "Vast Default Image", config.get("vast", {}).get("default_image", "")[:30] or "N/A"),
                ("vast.default_disk_gb", "Vast Default Disk", f"{config.get('vast', {}).get('default_disk_gb', 50)} GB"),
            ]

            self._goto(2, 2)
            self.print(styled("Configuration:", bold=True))
            self._goto(3, 2)
            self.print("-" * 50)

            for i, (key, label, value) in enumerate(self._settings_keys):
                self._goto(4 + i, 4)
                if i == self.list_selected:
                    self.print(styled(f"> {label:<20} {value}", reverse=True))
                else:
                    self.print(f"  {label:<20} {value}")

            self._draw_message()
            self._draw_footer("Enter:Edit  j/k:Navigate  b:Back  q:Quit")

        @KittyHandler.atomic_update
        def _draw_help(self) -> None:
            self.cmd.clear_screen()
            self._draw_header("Help")

            help_lines = [
                styled("GPU Training Workflow Automation", bold=True), "",
                styled("Navigation:", bold=True),
                "  j/k or Up/Down  Move selection",
                "  Enter           Select / Confirm",
                "  a               Add new item",
                "  d               Delete item",
                "  e               Edit item",
                "  b / Esc         Go back",
                "  q               Quit", "",
                styled("Forms:", bold=True),
                "  Tab / Enter     Next field",
                "  Shift+Tab       Previous field",
                "  Esc             Cancel", "",
                styled("CLI Usage:", bold=True),
                "  kitty +kitten trainsh config tui",
                "  kitty +kitten trainsh vast list",
                "  kitty +kitten trainsh host add",
            ]

            for i, line in enumerate(help_lines):
                self._goto(2 + i, 2)
                self.print(line)

            self._draw_footer("b:Back  q:Quit")

        @KittyHandler.atomic_update
        def _draw_form(self) -> None:
            self.cmd.clear_screen()
            sz = self.screen_size

            self._draw_header(self.form_title)

            self._goto(2, 2)
            mode_indicator = styled("[EDIT]", fg="green") if self.form_mode == "edit" else styled("[NAV]", fg="cyan")
            self.print(f"Mode: {mode_indicator}  (Tab: switch mode)")

            for i, fld in enumerate(self.form_fields):
                self._goto(4 + i * 2, 2)
                label = styled(fld.label + ":", bold=True)
                if fld.required:
                    label += styled(" *", fg="red")
                self.print(label)

                self._goto(4 + i * 2 + 1, 4)
                if fld.field_type == "select":
                    # Draw select box
                    options_str = " | ".join(
                        styled(opt[1], reverse=True) if fld.value == opt[0] else opt[1]
                        for opt in fld.options
                    )
                    line = f"[ {options_str} ]"
                else:
                    # Draw text input
                    display_value = "*" * len(fld.value) if fld.field_type == "password" else fld.value
                    if not display_value and fld.placeholder:
                        display_value = styled(fld.placeholder, dim=True)
                    line = f"[ {display_value:<30} ]"

                if i == self.form_field_index:
                    self.print(styled(line, fg="cyan"))
                else:
                    self.print(line)

            self._draw_message()
            self._draw_footer("Tab:Mode  Enter:Next/Submit  Esc:Cancel")

        @KittyHandler.atomic_update
        def _draw_dialog(self) -> None:
            self.cmd.clear_screen()
            sz = self.screen_size

            # Center the dialog
            box_width = 50
            box_height = 8
            start_row = (sz.rows - box_height) // 2
            start_col = (sz.cols - box_width) // 2

            # Draw box
            self._goto(start_row, start_col)
            self.print("+" + "-" * (box_width - 2) + "+")

            self._goto(start_row + 1, start_col)
            title = f" {self.dialog_title} "
            self.print("|" + styled(title.center(box_width - 2), bold=True) + "|")

            self._goto(start_row + 2, start_col)
            self.print("|" + " " * (box_width - 2) + "|")

            self._goto(start_row + 3, start_col)
            self.print("|" + self.dialog_message.center(box_width - 2) + "|")

            self._goto(start_row + 4, start_col)
            self.print("|" + " " * (box_width - 2) + "|")

            # Draw options
            self._goto(start_row + 5, start_col)
            options_line = "  ".join(
                styled(f"[{opt}]", reverse=True) if i == self.dialog_selected else f"[{opt}]"
                for i, opt in enumerate(self.dialog_options)
            )
            self.print("|" + options_line.center(box_width - 2) + "|")

            self._goto(start_row + 6, start_col)
            self.print("|" + " " * (box_width - 2) + "|")

            self._goto(start_row + 7, start_col)
            self.print("+" + "-" * (box_width - 2) + "+")

        @KittyHandler.atomic_update
        def _draw_host_add(self) -> None:
            """Draw host add form."""
            self.cmd.clear_screen()
            self._draw_header("Add Host")

            self._goto(2, 2)
            self.print(styled("Select host type:", bold=True))

            types = [
                ("ssh", "SSH", "Standard SSH connection"),
                ("colab_cf", "Colab (cloudflared)", "Google Colab via cloudflared"),
                ("colab_ngrok", "Colab (ngrok)", "Google Colab via ngrok"),
            ]

            for i, (key, name, desc) in enumerate(types):
                self._goto(4 + i, 4)
                if i == self.list_selected:
                    self.print(styled(f"> {name:<20} {desc}", reverse=True))
                else:
                    self.print(f"  {name:<20} {desc}")

            self._draw_footer("Enter:Select  b:Back")

        @KittyHandler.atomic_update
        def _draw_storage_add(self) -> None:
            """Draw storage add form."""
            self.cmd.clear_screen()
            self._draw_header("Add Storage")

            self._goto(2, 2)
            self.print(styled("Select storage type:", bold=True))

            types = [
                ("ssh", "SSH/SFTP", "Remote server via SSH"),
                ("r2", "Cloudflare R2", "S3-compatible object storage"),
                ("b2", "Backblaze B2", "Cloud storage"),
                ("s3", "Amazon S3", "AWS S3 bucket"),
                ("gdrive", "Google Drive", "Google Drive storage"),
            ]

            for i, (key, name, desc) in enumerate(types):
                self._goto(4 + i, 4)
                if i == self.list_selected:
                    self.print(styled(f"> {name:<20} {desc}", reverse=True))
                else:
                    self.print(f"  {name:<20} {desc}")

            self._draw_footer("Enter:Select  b:Back")

        @KittyHandler.atomic_update
        def _draw_secret_edit(self) -> None:
            """Draw secret edit form."""
            self.cmd.clear_screen()
            self._draw_header("Set Secret")

            if self.form_fields:
                fld = self.form_fields[0]
                self._goto(2, 2)
                self.print(styled(f"Setting: {fld.label}", bold=True))
                self._goto(4, 2)
                self.print("Enter value (hidden):")
                self._goto(5, 4)
                display = "*" * len(fld.value) if fld.value else styled("(empty)", dim=True)
                self.print(f"[ {display:<40} ]")

            self._draw_footer("Enter:Save  Esc:Cancel")

        # ====================================================================
        # Event Handlers
        # ====================================================================

        def on_key(self, key_event: Any) -> None:
            if key_event.matches('ctrl+c'):
                self.quit_loop(0)
                return

            # Form mode
            if self.current_view == "form":
                self._handle_form_key(key_event)
                return

            # Secret edit mode
            if self.current_view == "secret_edit":
                self._handle_secret_edit_key(key_event)
                return

            # Dialog mode
            if self.current_view == "dialog":
                self._handle_dialog_key(key_event)
                return

            # Navigation keys
            if key_event.matches('up'):
                self._nav_up()
            elif key_event.matches('down'):
                self._nav_down()
            elif key_event.matches('enter'):
                self._nav_select()
            elif key_event.matches('escape'):
                self._nav_back()

        def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
            if not text:
                return

            # Form edit mode
            if self.current_view == "form" and self.form_mode == "edit":
                self._handle_form_text(text)
                return

            # Secret edit mode
            if self.current_view == "secret_edit":
                self._handle_secret_edit_text(text)
                return

            char = text.lower()

            # Global quit
            if char == 'q':
                self.quit_loop(0)
                return

            if self.current_view == "main":
                if char == 'k':
                    self._nav_up()
                elif char == 'j':
                    self._nav_down()
                else:
                    for item in self.menu_items:
                        if char == item.key.lower():
                            self.current_view = item.action
                            self.list_selected = 0
                            self.draw_screen()
                            break
            elif self.current_view in ("hosts", "storage", "secrets", "recipes",
                                        "host_add", "storage_add", "settings"):
                if char == 'b':
                    self._nav_back()
                elif char == 'r':
                    # Reset Vast.ai cache on refresh in hosts view
                    if self.current_view == "hosts":
                        self._reset_vast_cache()
                    self.draw_screen()
                elif char == 'j':
                    self._nav_down()
                elif char == 'k':
                    self._nav_up()
                elif char == 'a':
                    self._action_add()
                elif char == 'd':
                    self._action_delete()
                elif char == 'e':
                    self._action_edit()
                elif char == 's':
                    self._action_ssh()
                elif char == '*':
                    self._action_set_default()
                elif text == 'S':  # Capital S for Vast.ai start
                    self._action_vast_start()
                elif text == 'X':  # Capital X for Vast.ai stop
                    self._action_vast_stop()
            else:
                if char == 'b':
                    self._nav_back()
                elif char == 'r':
                    self.draw_screen()

        def _nav_up(self) -> None:
            if self.current_view == "main":
                self.selected_index = max(0, self.selected_index - 1)
            else:
                self.list_selected = max(0, self.list_selected - 1)
            self.draw_screen()

        def _nav_down(self) -> None:
            if self.current_view == "main":
                self.selected_index = min(len(self.menu_items) - 1, self.selected_index + 1)
            elif self.current_view == "storage_add":
                # storage_add has 5 options
                self.list_selected = min(4, self.list_selected + 1)
            elif self.current_view == "host_add":
                # host_add has 3 options
                self.list_selected = min(2, self.list_selected + 1)
            elif self.current_view == "settings":
                # settings has 6 options
                self.list_selected = min(5, self.list_selected + 1)
            else:
                max_idx = len(self.list_items) - 1 if self.list_items else 0
                self.list_selected = min(max_idx, self.list_selected + 1)
            self.draw_screen()

        def _nav_select(self) -> None:
            if self.current_view == "main":
                item = self.menu_items[self.selected_index]
                self.current_view = item.action
                self.list_selected = 0
                self.draw_screen()
            elif self.current_view == "host_add":
                self._host_add_select()
            elif self.current_view == "storage_add":
                self._storage_add_select()
            elif self.current_view == "secrets":
                self._secret_edit_start()
            elif self.current_view == "settings":
                self._settings_edit_start()

        def _nav_back(self) -> None:
            if self.current_view in ("vast", "hosts", "storage", "recipes",
                                      "secrets", "settings", "help"):
                self.current_view = "main"
            elif self.current_view in ("host_add", "storage_add", "secret_edit"):
                self.current_view = self.previous_view
            self.draw_screen()

        # ====================================================================
        # Actions
        # ====================================================================

        def _action_add(self) -> None:
            if self.current_view == "hosts":
                self.previous_view = "hosts"
                self.current_view = "host_add"
                self.list_selected = 0
                self.draw_screen()
            elif self.current_view == "storage":
                self.previous_view = "storage"
                self.current_view = "storage_add"
                self.list_selected = 0
                self.draw_screen()

        def _action_delete(self) -> None:
            if not self.list_items or self.list_selected >= len(self.list_items):
                return

            item = self.list_items[self.list_selected]

            if self.current_view == "hosts":
                self._show_dialog(
                    "Delete Host",
                    f"Delete '{item.title}'?",
                    ["Yes", "No"],
                    lambda idx: self._do_delete_host(item.id) if idx == 0 else None
                )
            elif self.current_view == "storage":
                self._show_dialog(
                    "Delete Storage",
                    f"Delete '{item.title}'?",
                    ["Yes", "No"],
                    lambda idx: self._do_delete_storage(item.id) if idx == 0 else None
                )
            elif self.current_view == "secrets":
                self._show_dialog(
                    "Delete Secret",
                    f"Delete '{item.title}'?",
                    ["Yes", "No"],
                    lambda idx: self._do_delete_secret(item.data) if idx == 0 else None
                )

        def _action_edit(self) -> None:
            if self.current_view == "hosts" and self.list_items:
                self._show_message("Edit not implemented yet", "info")
                self.draw_screen()

        def _action_ssh(self) -> None:
            if self.current_view == "hosts" and self.list_items:
                if self.list_selected >= len(self.list_items):
                    return
                item = self.list_items[self.list_selected]
                remote = get_remote()
                if not remote.available:
                    self._show_message("Not running in kitty terminal", "error")
                    self.draw_screen()
                    return

                # Check if this is a Vast.ai instance
                if isinstance(item.data, tuple) and item.data[0] == "vast":
                    _, inst = item.data
                    if inst.actual_status != "running":
                        self._show_message("Instance not running. Press 'S' to start.", "error")
                        self.draw_screen()
                        return
                    # SSH into Vast.ai instance with tmux
                    ssh_host = inst.ssh_host or inst.public_ipaddr
                    ssh_port = inst.ssh_port or 22
                    self._ssh_with_tmux(remote, ssh_host, "root", ssh_port, None, f"vast-{inst.id}")
                else:
                    # Regular host with tmux
                    host = item.data
                    self._ssh_with_tmux(remote, host.hostname, host.username, host.port,
                                        host.ssh_key_path, item.title)

        def _ssh_with_tmux(self, remote: KittyRemote, host: str, user: str, port: int,
                           key_file: Optional[str], title: str) -> None:
            """Connect to host via SSH and attach to tmux session."""
            self._show_message(f"Checking tmux sessions on {title}...", "info")
            self.draw_screen()

            # Get remote tmux sessions
            sessions, err = remote.get_remote_tmux_sessions(host, user, port, key_file)

            if err:
                # Connection failed or tmux error, just connect without tmux
                self._show_message(f"Connecting to {title}...", "info")
                self.draw_screen()
                success, err = remote.launch_ssh(host, user, port, key_file, title=title)
                if success:
                    self._show_message(f"SSH to {title} opened in new tab", "success")
                else:
                    self._show_message(f"SSH failed: {err[:40]}" if err else "SSH failed", "error")
                self.draw_screen()
                return

            if not sessions:
                # No sessions, create a new "main" session
                tmux_cmd = 'tmux new-session -s main'
                success, err = remote.launch_ssh(host, user, port, key_file, title=title, remote_cmd=tmux_cmd)
                if success:
                    self._show_message(f"SSH to {title} with tmux:main opened", "success")
                else:
                    self._show_message(f"SSH failed: {err[:40]}" if err else "SSH failed", "error")
                self.draw_screen()
            else:
                # Has sessions, show selection dialog (even for 1 session)
                # Store connection params for later use
                self._pending_ssh = {
                    "remote": remote, "host": host, "user": user, "port": port,
                    "key_file": key_file, "title": title, "sessions": sessions
                }
                options = sessions + ["+ New Session"]
                self._show_dialog(
                    "Select tmux Session",
                    f"Found {len(sessions)} session(s) on {title}",
                    options,
                    self._on_tmux_session_selected
                )

        def _on_tmux_session_selected(self, idx: int) -> None:
            """Handle tmux session selection from dialog."""
            params = self._pending_ssh
            sessions = params["sessions"]

            if idx < len(sessions):
                # Selected an existing session
                self._do_ssh_tmux_session(
                    params["remote"], params["host"], params["user"], params["port"],
                    params["key_file"], params["title"], sessions[idx]
                )
            else:
                # Selected "+ New Session", show form to input session name
                self._show_form(
                    "New tmux Session",
                    [FormField("session_name", "Session Name", "main")],
                    self._on_new_session_name_submitted
                )

        def _on_new_session_name_submitted(self, data: Dict[str, str]) -> None:
            """Handle new session name form submission."""
            params = self._pending_ssh
            session_name = data.get("session_name", "main").strip() or "main"
            tmux_cmd = f'tmux new-session -s {session_name}'
            success, err = params["remote"].launch_ssh(
                params["host"], params["user"], params["port"],
                params["key_file"], title=params["title"], remote_cmd=tmux_cmd
            )
            if success:
                self._show_message(f"SSH to {params['title']} with tmux:{session_name} opened", "success")
            else:
                self._show_message(f"SSH failed: {err[:40]}" if err else "SSH failed", "error")
            self.current_view = "hosts"
            self.draw_screen()

        def _do_ssh_tmux_session(self, remote: KittyRemote, host: str, user: str, port: int,
                                  key_file: Optional[str], title: str, session: Optional[str]) -> None:
            """Execute SSH connection with specified tmux session."""
            if session:
                tmux_cmd = f'tmux attach-session -t {session}'
            else:
                tmux_cmd = 'tmux new-session -s main'
            success, err = remote.launch_ssh(host, user, port, key_file, title=title, remote_cmd=tmux_cmd)
            if success:
                session_name = session or "main"
                self._show_message(f"SSH to {title} with tmux:{session_name} opened", "success")
            else:
                self._show_message(f"SSH failed: {err[:40]}" if err else "SSH failed", "error")
            self.current_view = "hosts"
            self.draw_screen()

        def _action_vast_start(self) -> None:
            """Start a Vast.ai instance."""
            if self.current_view != "hosts" or not self.list_items:
                return
            if self.list_selected >= len(self.list_items):
                return

            item = self.list_items[self.list_selected]
            if not isinstance(item.data, tuple) or item.data[0] != "vast":
                self._show_message("Select a Vast.ai instance to start", "error")
                self.draw_screen()
                return

            _, inst = item.data
            if inst.actual_status == "running":
                self._show_message("Instance already running", "info")
                self.draw_screen()
                return

            self._show_dialog(
                "Start Instance",
                f"Start vast-{inst.id}?",
                ["Yes", "No"],
                lambda idx: self._do_vast_start(inst.id) if idx == 0 else None
            )

        def _action_vast_stop(self) -> None:
            """Stop a Vast.ai instance."""
            if self.current_view != "hosts" or not self.list_items:
                return
            if self.list_selected >= len(self.list_items):
                return

            item = self.list_items[self.list_selected]
            if not isinstance(item.data, tuple) or item.data[0] != "vast":
                self._show_message("Select a Vast.ai instance to stop", "error")
                self.draw_screen()
                return

            _, inst = item.data
            if inst.actual_status != "running":
                self._show_message("Instance not running", "info")
                self.draw_screen()
                return

            self._show_dialog(
                "Stop Instance",
                f"Stop vast-{inst.id}? (You will still be charged for storage)",
                ["Yes", "No"],
                lambda idx: self._do_vast_stop(inst.id) if idx == 0 else None
            )

        def _do_vast_start(self, instance_id: int) -> None:
            """Execute Vast.ai instance start and monitor status."""
            try:
                from ..services.vast_api import get_vast_client
                client = get_vast_client()
                client.start_instance(instance_id)
                self._show_message(f"Starting vast-{instance_id}...", "success")
                # Start monitoring the instance status
                self._start_vast_status_monitor(instance_id)
            except Exception as e:
                self._show_message(f"Failed to start: {e}", "error")
            self.current_view = "hosts"
            self.draw_screen()

        def _start_vast_status_monitor(self, instance_id: int) -> None:
            """Start monitoring Vast.ai instance status after start command."""
            import threading
            import time

            # Track the monitoring state
            self._vast_monitoring_id = instance_id
            self._vast_monitoring_status = "starting"

            def monitor_status():
                """Poll the instance status until it's running or failed."""
                from ..services.vast_api import get_vast_client

                max_attempts = 60  # 5 minutes max (60 * 5 seconds)
                attempt = 0

                while attempt < max_attempts:
                    try:
                        client = get_vast_client()
                        inst = client.get_instance(instance_id)

                        if not inst:
                            self._vast_monitoring_status = "not_found"
                            break

                        status = inst.actual_status or "unknown"
                        self._vast_monitoring_status = status

                        # Update the cached instance data
                        for i, cached_inst in enumerate(self._vast_instances):
                            if cached_inst.id == instance_id:
                                self._vast_instances[i] = inst
                                break

                        # Trigger UI update on main thread
                        try:
                            self.asyncio_loop.call_soon_threadsafe(self._on_vast_status_update)
                        except Exception:
                            pass

                        if status == "running":
                            # Instance is now running
                            self._vast_monitoring_id = None
                            try:
                                self.asyncio_loop.call_soon_threadsafe(
                                    lambda: self._show_message(f"vast-{instance_id} is now running!", "success")
                                )
                            except Exception:
                                pass
                            break
                        elif status in ("exited", "error", "offline"):
                            # Instance failed to start
                            self._vast_monitoring_id = None
                            try:
                                self.asyncio_loop.call_soon_threadsafe(
                                    lambda: self._show_message(f"vast-{instance_id} failed: {status}", "error")
                                )
                            except Exception:
                                pass
                            break

                        # Wait before next poll
                        time.sleep(5)
                        attempt += 1

                    except Exception as e:
                        # Log error but continue monitoring
                        attempt += 1
                        time.sleep(5)

                # Timeout or completion
                self._vast_monitoring_id = None
                if attempt >= max_attempts:
                    try:
                        self.asyncio_loop.call_soon_threadsafe(
                            lambda: self._show_message(f"Timeout waiting for vast-{instance_id}", "error")
                        )
                    except Exception:
                        pass

            thread = threading.Thread(target=monitor_status, daemon=True)
            thread.start()

        def _on_vast_status_update(self) -> None:
            """Called when Vast.ai status monitoring has an update."""
            if self.current_view == "hosts":
                self.draw_screen()

        def _do_vast_stop(self, instance_id: int) -> None:
            """Execute Vast.ai instance stop and monitor status."""
            try:
                from ..services.vast_api import get_vast_client
                client = get_vast_client()
                client.stop_instance(instance_id)
                self._show_message(f"Stopping vast-{instance_id}...", "success")
                # Start monitoring the instance status for stopping
                self._start_vast_stop_monitor(instance_id)
            except Exception as e:
                self._show_message(f"Failed to stop: {e}", "error")
            self.current_view = "hosts"
            self.draw_screen()

        def _start_vast_stop_monitor(self, instance_id: int) -> None:
            """Start monitoring Vast.ai instance status after stop command."""
            import threading
            import time

            # Track the monitoring state
            self._vast_monitoring_id = instance_id
            self._vast_monitoring_status = "stopping"

            def monitor_status():
                """Poll the instance status until it's stopped or failed."""
                from ..services.vast_api import get_vast_client

                max_attempts = 30  # 2.5 minutes max (30 * 5 seconds)
                attempt = 0

                while attempt < max_attempts:
                    try:
                        client = get_vast_client()
                        inst = client.get_instance(instance_id)

                        if not inst:
                            self._vast_monitoring_status = "not_found"
                            break

                        status = inst.actual_status or "unknown"
                        self._vast_monitoring_status = status

                        # Update the cached instance data
                        for i, cached_inst in enumerate(self._vast_instances):
                            if cached_inst.id == instance_id:
                                self._vast_instances[i] = inst
                                break

                        # Trigger UI update on main thread
                        try:
                            self.asyncio_loop.call_soon_threadsafe(self._on_vast_status_update)
                        except Exception:
                            pass

                        if status in ("stopped", "exited", "offline"):
                            # Instance is now stopped
                            self._vast_monitoring_id = None
                            try:
                                self.asyncio_loop.call_soon_threadsafe(
                                    lambda: self._show_message(f"vast-{instance_id} stopped", "success")
                                )
                            except Exception:
                                pass
                            break

                        # Wait before next poll
                        time.sleep(5)
                        attempt += 1

                    except Exception as e:
                        # Log error but continue monitoring
                        attempt += 1
                        time.sleep(5)

                # Timeout or completion
                self._vast_monitoring_id = None

            thread = threading.Thread(target=monitor_status, daemon=True)
            thread.start()

        def _action_set_default(self) -> None:
            if self.current_view == "storage" and self.list_items:
                item = self.list_items[self.list_selected]
                self._do_set_default_storage(item.id)

        # ====================================================================
        # Host Actions
        # ====================================================================

        def _host_add_select(self) -> None:
            types = ["ssh", "colab_cf", "colab_ngrok"]
            if self.list_selected >= len(types):
                return

            host_type = types[self.list_selected]

            if host_type == "ssh":
                fields = [
                    FormField("name", "Name", required=True, placeholder="my-server"),
                    FormField("hostname", "Hostname", required=True, placeholder="192.168.1.1"),
                    FormField("port", "Port", "number", "22"),
                    FormField("username", "Username", value="root"),
                    FormField("ssh_key_path", "SSH Key Path", placeholder="~/.ssh/id_rsa"),
                ]
                self._show_form("Add SSH Host", fields, self._do_add_ssh_host)
            elif host_type.startswith("colab"):
                tunnel = "cloudflared" if host_type == "colab_cf" else "ngrok"
                fields = [
                    FormField("name", "Name", required=True, placeholder="my-colab"),
                    FormField("hostname", "Hostname", required=True,
                              placeholder="xxx.trycloudflare.com" if tunnel == "cloudflared" else "0.tcp.ngrok.io"),
                    FormField("port", "Port", "number", "22" if tunnel == "cloudflared" else "12345"),
                ]
                self._show_form(f"Add Colab Host ({tunnel})", fields,
                                lambda d: self._do_add_colab_host(d, tunnel))

        def _do_add_ssh_host(self, data: Dict[str, str]) -> None:
            from ..core.models import Host, HostType, AuthMethod
            from ..commands.host import load_hosts, save_hosts

            host = Host(
                name=data["name"],
                type=HostType.SSH,
                hostname=data["hostname"],
                port=int(data.get("port") or 22),
                username=data.get("username") or "root",
                auth_method=AuthMethod.KEY,
                ssh_key_path=data.get("ssh_key_path") or None,
            )

            hosts = load_hosts()
            hosts[host.name] = host
            save_hosts(hosts)

            self._show_message(f"Host '{host.name}' added", "success")
            self.current_view = "hosts"

        def _do_add_colab_host(self, data: Dict[str, str], tunnel: str) -> None:
            from ..core.models import Host, HostType, AuthMethod
            from ..commands.host import load_hosts, save_hosts

            host = Host(
                name=data["name"],
                type=HostType.COLAB,
                hostname=data["hostname"],
                port=int(data.get("port") or 22),
                username="root",
                auth_method=AuthMethod.PASSWORD,
                env_vars={"tunnel_type": tunnel},
            )

            hosts = load_hosts()
            hosts[host.name] = host
            save_hosts(hosts)

            self._show_message(f"Colab host '{host.name}' added", "success")
            self.current_view = "hosts"

        def _do_delete_host(self, name: str) -> None:
            from ..commands.host import load_hosts, save_hosts

            hosts = load_hosts()
            if name in hosts:
                del hosts[name]
                save_hosts(hosts)
                self._show_message(f"Host '{name}' deleted", "success")
            self.list_selected = 0
            self.current_view = "hosts"
            self.draw_screen()

        # ====================================================================
        # Storage Actions
        # ====================================================================

        def _storage_add_select(self) -> None:
            types = ["ssh", "r2", "b2", "s3", "gdrive"]
            if self.list_selected >= len(types):
                return

            storage_type = types[self.list_selected]

            if storage_type == "ssh":
                fields = [
                    FormField("name", "Name", required=True, placeholder="my-server"),
                    FormField("hostname", "Hostname", required=True),
                    FormField("port", "Port", "number", "22"),
                    FormField("username", "Username", value="root"),
                    FormField("path", "Remote Path", value="/"),
                ]
                self._show_form("Add SSH Storage", fields, self._do_add_ssh_storage)
            elif storage_type == "r2":
                fields = [
                    FormField("name", "Name", required=True, placeholder="my-r2"),
                    FormField("account_id", "Account ID", required=True),
                    FormField("bucket", "Bucket", required=True),
                ]
                self._show_form("Add R2 Storage", fields, self._do_add_r2_storage)
            elif storage_type == "b2":
                fields = [
                    FormField("name", "Name", required=True, placeholder="my-b2"),
                    FormField("bucket", "Bucket", required=True),
                ]
                self._show_form("Add B2 Storage", fields, self._do_add_b2_storage)
            elif storage_type == "s3":
                fields = [
                    FormField("name", "Name", required=True, placeholder="my-s3"),
                    FormField("bucket", "Bucket", required=True),
                    FormField("region", "Region", value="us-east-1"),
                ]
                self._show_form("Add S3 Storage", fields, self._do_add_s3_storage)
            else:
                self._show_message("Not implemented", "error")
                self.current_view = "storage"
                self.draw_screen()

        def _do_add_ssh_storage(self, data: Dict[str, str]) -> None:
            from ..core.models import Storage, StorageType
            from ..commands.storage import load_storages, save_storages

            storage = Storage(
                name=data["name"],
                type=StorageType.SSH,
                config={
                    "hostname": data["hostname"],
                    "port": int(data.get("port") or 22),
                    "username": data.get("username") or "root",
                    "path": data.get("path") or "/",
                },
            )

            storages = load_storages()
            storages[storage.name] = storage
            save_storages(storages)

            self._show_message(f"Storage '{storage.name}' added", "success")
            self.current_view = "storage"

        def _do_add_r2_storage(self, data: Dict[str, str]) -> None:
            from ..core.models import Storage, StorageType
            from ..commands.storage import load_storages, save_storages

            storage = Storage(
                name=data["name"],
                type=StorageType.R2,
                config={
                    "account_id": data["account_id"],
                    "bucket": data["bucket"],
                },
            )

            storages = load_storages()
            storages[storage.name] = storage
            save_storages(storages)

            self._show_message(f"R2 Storage '{storage.name}' added", "success")
            self.current_view = "storage"

        def _do_add_b2_storage(self, data: Dict[str, str]) -> None:
            from ..core.models import Storage, StorageType
            from ..commands.storage import load_storages, save_storages

            storage = Storage(
                name=data["name"],
                type=StorageType.B2,
                config={"bucket": data["bucket"]},
            )

            storages = load_storages()
            storages[storage.name] = storage
            save_storages(storages)

            self._show_message(f"B2 Storage '{storage.name}' added", "success")
            self.current_view = "storage"

        def _do_add_s3_storage(self, data: Dict[str, str]) -> None:
            from ..core.models import Storage, StorageType
            from ..commands.storage import load_storages, save_storages

            storage = Storage(
                name=data["name"],
                type=StorageType.S3,
                config={
                    "bucket": data["bucket"],
                    "region": data.get("region") or "us-east-1",
                },
            )

            storages = load_storages()
            storages[storage.name] = storage
            save_storages(storages)

            self._show_message(f"S3 Storage '{storage.name}' added", "success")
            self.current_view = "storage"

        def _do_delete_storage(self, name: str) -> None:
            from ..commands.storage import load_storages, save_storages

            storages = load_storages()
            if name in storages:
                del storages[name]
                save_storages(storages)
                self._show_message(f"Storage '{name}' deleted", "success")
            self.list_selected = 0
            self.current_view = "storage"
            self.draw_screen()

        def _do_set_default_storage(self, name: str) -> None:
            from ..commands.storage import load_storages, save_storages

            storages = load_storages()
            for n, s in storages.items():
                s.is_default = (n == name)
            save_storages(storages)
            self._show_message(f"'{name}' set as default", "success")
            self.draw_screen()

        # ====================================================================
        # Secret Actions
        # ====================================================================

        def _secret_edit_start(self) -> None:
            if not self.list_items:
                return
            item = self.list_items[self.list_selected]
            self.previous_view = "secrets"
            self.current_view = "secret_edit"
            self.form_fields = [FormField(item.data, item.title, "password")]
            self.draw_screen()

        def _handle_secret_edit_key(self, key_event: Any) -> None:
            if key_event.matches('escape'):
                self.current_view = "secrets"
                self.draw_screen()
            elif key_event.matches('enter'):
                self._do_save_secret()
            elif key_event.matches('backspace'):
                if self.form_fields and self.form_fields[0].value:
                    self.form_fields[0].value = self.form_fields[0].value[:-1]
                    self.draw_screen()

        def _handle_secret_edit_text(self, text: str) -> None:
            if self.form_fields:
                self.form_fields[0].value += text
                self.draw_screen()

        def _do_save_secret(self) -> None:
            if not self.form_fields:
                return
            fld = self.form_fields[0]
            if fld.value:
                from ..core.secrets import get_secrets_manager
                secrets = get_secrets_manager()
                secrets.set(fld.name, fld.value)
                # Update cache
                if hasattr(self, '_secrets_cache'):
                    self._secrets_cache[fld.name] = True
                self._show_message(f"Secret '{fld.label}' saved", "success")
            self.current_view = "secrets"
            self.draw_screen()

        def _do_delete_secret(self, key: str) -> None:
            from ..core.secrets import get_secrets_manager
            secrets = get_secrets_manager()
            secrets.delete(key)
            # Update cache
            if hasattr(self, '_secrets_cache'):
                self._secrets_cache[key] = False
            self._show_message("Secret deleted", "success")
            self.current_view = "secrets"
            self.draw_screen()

        # ====================================================================
        # Settings Actions
        # ====================================================================

        def _settings_edit_start(self) -> None:
            if not hasattr(self, '_settings_keys') or not self._settings_keys:
                return
            if self.list_selected >= len(self._settings_keys):
                return

            key, label, current_value = self._settings_keys[self.list_selected]

            # Special handling for different config types
            if key == "defaults.transfer_method":
                fields = [
                    FormField(key, label, "select", current_value,
                              [("rsync", "rsync"), ("rclone", "rclone")])
                ]
            elif key == "ui.currency":
                fields = [
                    FormField(key, label, "select", current_value,
                              [("USD", "USD"), ("CNY", "CNY"), ("EUR", "EUR"),
                               ("GBP", "GBP"), ("JPY", "JPY")])
                ]
            elif key == "ui.show_costs":
                fields = [
                    FormField(key, label, "select", current_value,
                              [("True", "Yes"), ("False", "No")])
                ]
            else:
                # Text input for other settings
                # Clean up display value
                display_val = current_value
                if key == "vast.default_disk_gb":
                    display_val = current_value.replace(" GB", "")
                elif current_value == "N/A":
                    display_val = ""
                fields = [
                    FormField(key, label, "text", display_val)
                ]

            self._show_form(f"Edit {label}", fields, self._do_save_setting)

        def _do_save_setting(self, data: dict) -> None:
            from ..config import set_config_value

            for key, value in data.items():
                # Type conversion
                if key == "ui.show_costs":
                    value = value == "True"
                elif key == "vast.default_disk_gb":
                    try:
                        value = int(value)
                    except ValueError:
                        self._show_message("Invalid disk size", "error")
                        return

                set_config_value(key, value)
                self._show_message(f"Saved {key}", "success")

            self.current_view = "settings"
            self.draw_screen()

        # ====================================================================
        # Form Handlers
        # ====================================================================

        def _handle_form_key(self, key_event: Any) -> None:
            if key_event.matches('escape'):
                self._form_cancel()
            elif key_event.matches('tab'):
                if self.form_mode == "navigate":
                    self.form_mode = "edit"
                else:
                    self.form_mode = "navigate"
                self.draw_screen()
            elif key_event.matches('enter'):
                if self.form_field_index < len(self.form_fields) - 1:
                    self.form_field_index += 1
                else:
                    self._form_submit()
                self.draw_screen()
            elif key_event.matches('up') and self.form_mode == "navigate":
                self.form_field_index = max(0, self.form_field_index - 1)
                self.draw_screen()
            elif key_event.matches('down') and self.form_mode == "navigate":
                self.form_field_index = min(len(self.form_fields) - 1, self.form_field_index + 1)
                self.draw_screen()
            elif key_event.matches('backspace') and self.form_mode == "edit":
                fld = self.form_fields[self.form_field_index]
                if fld.value:
                    fld.value = fld.value[:-1]
                    self.draw_screen()
            elif key_event.matches('left') and self.form_mode == "edit":
                fld = self.form_fields[self.form_field_index]
                if fld.field_type == "select" and fld.options:
                    idx = next((i for i, o in enumerate(fld.options) if o[0] == fld.value), 0)
                    idx = (idx - 1) % len(fld.options)
                    fld.value = fld.options[idx][0]
                    self.draw_screen()
            elif key_event.matches('right') and self.form_mode == "edit":
                fld = self.form_fields[self.form_field_index]
                if fld.field_type == "select" and fld.options:
                    idx = next((i for i, o in enumerate(fld.options) if o[0] == fld.value), 0)
                    idx = (idx + 1) % len(fld.options)
                    fld.value = fld.options[idx][0]
                    self.draw_screen()

        def _handle_form_text(self, text: str) -> None:
            fld = self.form_fields[self.form_field_index]
            if fld.field_type in ("text", "password", "number"):
                fld.value += text
                self.draw_screen()

        # ====================================================================
        # Dialog Handlers
        # ====================================================================

        def _handle_dialog_key(self, key_event: Any) -> None:
            if key_event.matches('escape'):
                self.current_view = self.previous_view
                self.draw_screen()
            elif key_event.matches('left'):
                self.dialog_selected = max(0, self.dialog_selected - 1)
                self.draw_screen()
            elif key_event.matches('right'):
                self.dialog_selected = min(len(self.dialog_options) - 1, self.dialog_selected + 1)
                self.draw_screen()
            elif key_event.matches('enter'):
                if self.dialog_callback:
                    self.dialog_callback(self.dialog_selected)
                self.current_view = self.previous_view
                self.draw_screen()

        def on_resize(self, screen_size: Any) -> None:
            super().on_resize(screen_size)
            self.draw_screen()

        def print(self, *args: Any, sep: str = ' ', end: str = '\r\n') -> None:
            self.write(sep.join(str(a) for a in args) + end)


# ============================================================================
# Entry Point
# ============================================================================

def run_tui(args: list) -> Optional[str]:
    """Run the TUI interface."""
    if not KITTY_TUI_AVAILABLE:
        print("Error: TUI requires running inside kitty terminal.")
        print("Use: kitty +kitten trainsh config tui")
        raise SystemExit(1)

    if not is_kitty():
        print("Error: TUI requires running inside kitty terminal.")
        print("Use: kitty +kitten trainsh config tui")
        raise SystemExit(1)

    loop = Loop()
    handler = TrainshKittyHandler()
    loop.loop(handler)
    raise SystemExit(loop.return_code or 0)
