# kitten-trainsh DSL executor
# Executes parsed DSL recipes using kitty kitten API

import subprocess
import time
import re
import os
import shlex
from typing import Optional, Dict, List, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from .dsl_parser import DSLRecipe, DSLStep, StepType, parse_recipe
from .execution_log import ExecutionLogger
from .secrets import get_secrets_manager
from .models import Host, HostType


@dataclass
class WindowInfo:
    """Tracks a kitty window/tab."""
    name: str
    host: str
    window_id: Optional[str] = None
    tab_id: Optional[str] = None


@dataclass
class ExecutionContext:
    """Runtime context for recipe execution."""
    recipe: DSLRecipe
    variables: Dict[str, str] = field(default_factory=dict)
    windows: Dict[str, WindowInfo] = field(default_factory=dict)
    exec_id: str = ""
    start_time: Optional[datetime] = None
    log_callback: Optional[Callable[[str], None]] = None


SSH_OPTION_ARGS = {
    "-p",
    "-i",
    "-J",
    "-o",
    "-F",
    "-S",
    "-L",
    "-R",
    "-D",
}


def _split_ssh_spec(spec: str) -> Tuple[str, List[str]]:
    """Split SSH spec into host and option args."""
    tokens = shlex.split(spec) if spec else []
    host = ""
    options: List[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            options.append(token)
            if token in SSH_OPTION_ARGS and i + 1 < len(tokens):
                options.append(tokens[i + 1])
                i += 1
            i += 1
            continue
        if not host:
            host = token
        else:
            options.append(token)
        i += 1
    if not host:
        host = spec
    return host, options


def _build_ssh_args(spec: str, command: Optional[str] = None, tty: bool = False) -> List[str]:
    """Build SSH command args from a host spec and optional command."""
    host, options = _split_ssh_spec(spec)
    args = ["ssh"]
    if tty:
        args.append("-t")
    args.extend(options)
    args.append(host)
    if command:
        args.append(command)
    return args


def _host_from_ssh_spec(spec: str) -> Host:
    """Parse SSH spec into a Host object for rsync/ssh."""
    host_token, options = _split_ssh_spec(spec)
    username = ""
    hostname = host_token
    if "@" in host_token:
        username, hostname = host_token.split("@", 1)

    port = 22
    key_path = None
    jump_host = None
    i = 0
    while i < len(options):
        opt = options[i]
        if opt == "-p" and i + 1 < len(options):
            try:
                port = int(options[i + 1])
            except ValueError:
                port = 22
            i += 2
            continue
        if opt == "-i" and i + 1 < len(options):
            key_path = options[i + 1]
            i += 2
            continue
        if opt == "-J" and i + 1 < len(options):
            jump_host = options[i + 1]
            i += 2
            continue
        if opt in SSH_OPTION_ARGS:
            i += 2
            continue
        i += 1

    return Host(
        id=spec,
        name=spec,
        type=HostType.SSH,
        hostname=hostname,
        port=port,
        username=username,
        ssh_key_path=key_path,
        jump_host=jump_host,
    )


def _format_duration(seconds: float) -> str:
    """Format seconds into a compact duration string."""
    total_seconds = int(seconds)
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


class KittyController:
    """
    Interface to kitty terminal via kitten @ commands.

    Provides:
    - launch: Open new tabs/windows with SSH
    - send_text: Type text into a window
    - send_key: Send key presses
    - get_text: Read window contents
    - focus: Focus a window
    - close: Close a window
    """

    def __init__(self):
        self._check_kitty()

    def _check_kitty(self) -> bool:
        """Check if running in kitty."""
        return os.environ.get('TERM_PROGRAM') == 'kitty' or 'KITTY_PID' in os.environ

    def _run(self, *args, timeout: int = 30) -> tuple[str, int]:
        """Run kitten @ command."""
        cmd = ['kitten', '@'] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout, result.returncode
        except subprocess.TimeoutExpired:
            return "", -1
        except FileNotFoundError:
            return "kitten command not found", -1

    def launch(
        self,
        host: str,
        title: str,
        command: Optional[str] = None,
        tab_type: str = "tab",
        location: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Launch a new tab/window with SSH connection.

        Args:
            host: SSH host (user@hostname or host alias)
            title: Window title
            command: Optional command to run after connecting
            tab_type: 'tab', 'window', or 'overlay'
            location: Optional window location (e.g., 'vsplit', 'hsplit')

        Returns:
            (success, window_id or error message)
        """
        args = ['launch', '--type', tab_type, '--title', title]
        if location:
            args.extend(['--location', location])

        # Add hold flag to keep window open
        args.append('--hold')

        # Build SSH command
        if host != 'local':
            ssh_cmd = _build_ssh_args(host, command=command, tty=True)
            args.extend(ssh_cmd)
        elif command:
            args.extend(['bash', '-c', command])

        stdout, code = self._run(*args)

        if code == 0:
            # Try to extract window ID from output
            return True, stdout.strip() if stdout.strip() else title
        return False, stdout

    def send_text(
        self,
        target: str,
        text: str,
        match_type: str = "title",
    ) -> bool:
        """
        Send text to a window (like typing).

        Args:
            target: Window title or ID to match
            text: Text to send (use \\n for Enter)
            match_type: 'title', 'id', or 'recent'
        """
        args = ['send-text', '--match', f'{match_type}:{target}']

        # Process escape sequences
        text = text.replace('\\n', '\n')

        # Use stdin for the text
        cmd = ['kitten', '@'] + args
        try:
            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def send_key(self, target: str, *keys: str) -> bool:
        """
        Send key presses to a window.

        Args:
            target: Window title to match
            keys: Keys to send (e.g., 'ctrl+c', 'enter')
        """
        args = ['send-key', '--match', f'title:{target}'] + list(keys)
        _, code = self._run(*args)
        return code == 0

    def get_text(
        self,
        target: str,
        extent: str = "screen",
        ansi: bool = False,
    ) -> str:
        """
        Get text content from a window.

        Args:
            target: Window title to match
            extent: 'screen', 'all', or 'selection'
            ansi: Include ANSI escape codes

        Returns:
            Window text content
        """
        args = ['get-text', '--match', f'title:{target}', '--extent', extent]
        if ansi:
            args.append('--ansi')

        stdout, code = self._run(*args, timeout=5)
        return stdout if code == 0 else ""

    def focus(self, target: str) -> bool:
        """Focus a window by title."""
        _, code = self._run('focus-window', '--match', f'title:{target}')
        return code == 0

    def close(self, target: str) -> bool:
        """Close a window by title."""
        _, code = self._run('close-window', '--match', f'title:{target}')
        return code == 0

    def list_windows(self) -> List[Dict]:
        """List all kitty windows."""
        import json
        stdout, code = self._run('ls')
        if code == 0:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                pass
        return []


class DSLExecutor:
    """
    Executes DSL recipes step by step.

    Integrates with:
    - KittyController for terminal automation
    - TransferEngine for file transfers
    - VastAPI for GPU instance management
    """

    def __init__(
        self,
        recipe: DSLRecipe,
        log_callback: Optional[Callable[[str], None]] = None,
        visual: bool = True,
    ):
        """
        Initialize executor.

        Args:
            recipe: Parsed DSL recipe
            log_callback: Optional callback for log messages
            visual: Use kitty visual mode (open tabs)
        """
        self.recipe = recipe
        self.log_callback = log_callback or print
        self.visual = visual

        # Runtime state
        self.ctx = ExecutionContext(
            recipe=recipe,
            variables=dict(recipe.variables),
            exec_id=self._generate_id(),
            start_time=datetime.now(),
            log_callback=self.log_callback,
        )

        # Kitty controller
        self.kitty = KittyController()

        # Secrets manager
        self.secrets = get_secrets_manager()

        # Execution logger
        self.logger: Optional[ExecutionLogger] = None

    def _generate_id(self) -> str:
        """Generate unique execution ID."""
        import uuid
        return str(uuid.uuid4())[:8]

    def log(self, msg: str) -> None:
        """Log a message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{timestamp}] {msg}")

    def execute(self) -> bool:
        """
        Execute all steps in the recipe.

        Returns:
            True if all steps completed successfully
        """
        self.log(f"Starting recipe: {self.recipe.name}")
        self.log(f"Execution ID: {self.ctx.exec_id}")

        # Initialize logger
        self.logger = ExecutionLogger(
            exec_id=self.ctx.exec_id,
            recipe_id=self.recipe.name,
        )
        self.logger.start(self.recipe.name, self.ctx.variables)

        success = True

        for i, step in enumerate(self.recipe.steps):
            step_name = f"Step {i + 1}: {step.raw[:50]}"
            self.log(f"→ {step_name}")

            if self.logger:
                self.logger.step_start(str(i + 1), step_name, step.type.value)

            start = datetime.now()

            try:
                ok, output = self._execute_step(step)
                duration_ms = int((datetime.now() - start).total_seconds() * 1000)

                if self.logger:
                    if output:
                        self.logger.step_output(str(i + 1), output)
                    self.logger.step_end(str(i + 1), ok, duration_ms, "" if ok else output)

                if not ok:
                    self.log(f"  ✗ Failed: {output}")
                    success = False
                    break
                else:
                    self.log(f"  ✓ Done ({duration_ms}ms)")

            except Exception as e:
                self.log(f"  ✗ Error: {e}")
                if self.logger:
                    self.logger.step_end(str(i + 1), False, 0, str(e))
                success = False
                break

        # Finalize
        total_ms = int((datetime.now() - self.ctx.start_time).total_seconds() * 1000)
        if self.logger:
            self.logger.end(success, total_ms)

        status = "completed" if success else "failed"
        self.log(f"Recipe {status} in {total_ms}ms")

        return success

    def _execute_step(self, step: DSLStep) -> tuple[bool, str]:
        """Execute a single step."""
        handlers = {
            StepType.CONTROL: self._exec_control,
            StepType.EXECUTE: self._exec_execute,
            StepType.TRANSFER: self._exec_transfer,
            StepType.WAIT: self._exec_wait,
        }

        handler = handlers.get(step.type)
        if handler:
            return handler(step)

        return False, f"Unknown step type: {step.type}"

    def _exec_control(self, step: DSLStep) -> tuple[bool, str]:
        """Execute control command."""
        cmd = step.command
        args = step.args

        # Parse command
        if cmd == "kitty.open":
            return self._cmd_kitty_open(args)
        elif cmd == "kitty.close":
            return self._cmd_kitty_close(args)
        elif cmd == "notify":
            return self._cmd_notify(args)
        elif cmd == "vast.start":
            return self._cmd_vast_start(args)
        elif cmd == "vast.stop":
            return self._cmd_vast_stop(args)
        elif cmd == "vast.pick":
            return self._cmd_vast_pick(args)
        elif cmd == "vast.wait":
            return self._cmd_vast_wait(args)
        elif cmd == "vast.cost":
            return self._cmd_vast_cost(args)
        elif cmd == "sleep":
            return self._cmd_sleep(args)
        else:
            return False, f"Unknown control command: {cmd}"

    def _cmd_kitty_open(self, args: List[str]) -> tuple[bool, str]:
        """
        Handle: > kitty.open @host as name [command] [type=window] [location=vsplit]
        """
        if len(args) < 3 or args[1] != "as":
            return False, "Usage: kitty.open @host as name [command] [type=window] [location=vsplit]"

        host_ref = args[0]
        window_name = args[2]
        command = None
        launch_type = "tab"
        location = None

        for arg in args[3:]:
            if "=" in arg:
                key, _, value = arg.partition("=")
                if key == "type":
                    launch_type = value
                    continue
                if key == "location":
                    location = value
                    continue
            if command is None:
                command = arg
            else:
                command = f"{command} {arg}"

        # Resolve host
        host = self._resolve_host(host_ref)

        if self.visual:
            ok, result = self.kitty.launch(
                host=host,
                title=window_name,
                command=command,
                tab_type=launch_type,
                location=location,
            )

            if ok:
                self.ctx.windows[window_name] = WindowInfo(
                    name=window_name,
                    host=host,
                    window_id=result,
                )
                # Give SSH time to connect
                time.sleep(2)
                return True, f"Opened window: {window_name}"
            return False, result
        else:
            # Non-visual mode: just track the host
            self.ctx.windows[window_name] = WindowInfo(
                name=window_name,
                host=host,
            )
            return True, f"Registered window: {window_name} (non-visual)"

    def _cmd_kitty_close(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > kitty.close name"""
        if not args:
            return False, "Usage: kitty.close name"

        window_name = args[0]

        if self.visual:
            ok = self.kitty.close(window_name)
            if ok:
                self.ctx.windows.pop(window_name, None)
                return True, f"Closed window: {window_name}"
            return False, f"Failed to close: {window_name}"
        else:
            self.ctx.windows.pop(window_name, None)
            return True, f"Unregistered window: {window_name}"

    def _cmd_notify(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > notify "message" """
        message = " ".join(args)
        self.log(f"📢 {message}")

        # Try system notification
        try:
            subprocess.run(
                ['osascript', '-e', f'display notification "{message}" with title "trainsh"'],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

        return True, message

    def _cmd_vast_start(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > vast.start template/search"""
        from ..services.vast_api import get_vast_client, VastAPIError

        try:
            client = get_vast_client()

            if args:
                instance_id = self._interpolate(args[0])
                try:
                    inst_id = int(instance_id)
                except ValueError:
                    return False, f"Invalid instance ID: {instance_id}"

                instance = client.get_instance(inst_id)
                if instance.is_running:
                    self.ctx.variables["_vast_instance_id"] = str(inst_id)
                    return True, f"Instance already running: {inst_id}"

                try:
                    client.start_instance(inst_id)
                    self.ctx.variables["_vast_instance_id"] = str(inst_id)
                    return True, f"Started instance: {inst_id}"
                except VastAPIError as e:
                    msg = f"Failed to start instance {inst_id}: {e}"
                    try:
                        client.stop_instance(inst_id)
                        msg += "; instance stopped"
                    except VastAPIError as stop_err:
                        msg += f"; failed to stop instance: {stop_err}"
                    return False, msg

            # For now, just search and create
            offers = client.search_offers(limit=1)
            if not offers:
                return False, "No GPU offers available"

            instance_id = client.create_instance(
                offer_id=offers[0].id,
                image="pytorch/pytorch:latest",
                disk=50,
            )

            self.ctx.variables["_vast_instance_id"] = str(instance_id)
            return True, f"Created instance: {instance_id}"

        except (VastAPIError, RuntimeError) as e:
            return False, str(e)

    def _cmd_vast_stop(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > vast.stop <instance_id>"""
        from ..services.vast_api import get_vast_client, VastAPIError

        try:
            client = get_vast_client()

            instance_id = None
            if args:
                instance_id = self._interpolate(args[0])
            if not instance_id:
                instance_id = self.ctx.variables.get("_vast_instance_id")
            if not instance_id:
                return False, "No instance to stop"

            client.stop_instance(int(instance_id))
            return True, f"Stopped instance: {instance_id}"

        except (VastAPIError, RuntimeError) as e:
            return False, str(e)

    def _cmd_vast_pick(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > vast.pick @host gpu=RTX_5090 num_gpus=8 min_gpu_ram=24"""
        from ..services.vast_api import get_vast_client, VastAPIError

        host_name = None
        gpu_name = None
        num_gpus = None
        min_gpu_ram = None
        max_dph = None
        limit = 20
        image = "pytorch/pytorch:latest"
        disk = 50.0
        label = None
        onstart = None
        direct = False
        skip_if_set = True

        for arg in args:
            if "=" in arg:
                key, _, value = arg.partition("=")
                value = self._interpolate(value)
                if key in ("host", "host_name"):
                    host_name = value
                elif key in ("gpu", "gpu_name"):
                    gpu_name = value
                elif key in ("num_gpus", "gpus"):
                    try:
                        num_gpus = int(value)
                    except ValueError:
                        return False, f"Invalid num_gpus: {value}"
                elif key in ("min_gpu_ram", "min_vram_gb"):
                    try:
                        min_gpu_ram = float(value)
                    except ValueError:
                        return False, f"Invalid min_gpu_ram: {value}"
                elif key in ("max_dph", "max_price"):
                    try:
                        max_dph = float(value)
                    except ValueError:
                        return False, f"Invalid max_dph: {value}"
                elif key == "limit":
                    try:
                        limit = int(value)
                    except ValueError:
                        return False, f"Invalid limit: {value}"
                elif key == "image":
                    image = value
                elif key == "disk":
                    try:
                        disk = float(value)
                    except ValueError:
                        return False, f"Invalid disk: {value}"
                elif key == "label":
                    label = value
                elif key == "onstart":
                    onstart = value
                elif key == "direct":
                    direct = value.lower() in ("1", "true", "yes", "y")
                elif key == "skip_if_set":
                    skip_if_set = value.lower() in ("1", "true", "yes", "y")
                continue

            if host_name is None:
                host_name = self._interpolate(arg)

        if host_name:
            if host_name.startswith("@"):
                host_name = host_name[1:]
        elif "gpu" in self.recipe.hosts:
            host_name = "gpu"
        else:
            return False, "No host alias provided for vast.pick"

        existing_id = None
        if skip_if_set:
            for key in ("_vast_instance_id", "VAST_ID"):
                value = self.ctx.variables.get(key)
                if value and value.isdigit() and int(value) > 0:
                    existing_id = int(value)
                    break

        if existing_id:
            self.recipe.hosts[host_name] = f"vast:{existing_id}"
            self.ctx.variables["_vast_instance_id"] = str(existing_id)
            self.ctx.variables["VAST_ID"] = str(existing_id)
            return True, f"Using existing instance: {existing_id}"

        try:
            client = get_vast_client()
            offers = client.search_offers(
                gpu_name=gpu_name,
                num_gpus=num_gpus,
                min_gpu_ram=min_gpu_ram,
                max_dph=max_dph,
                limit=limit,
            )

            if not offers:
                return False, "No Vast.ai offers found"

            offers = sorted(offers, key=lambda o: o.dph_total or 0.0)

            print("\nSelect a Vast.ai offer:")
            print("-" * 78)
            print(f"{'#':<4} {'ID':<10} {'GPU':<18} {'GPUs':<5} {'VRAM':<8} {'$/hr':<8} {'Rel':<6}")
            print("-" * 78)
            for idx, offer in enumerate(offers, 1):
                gpu = offer.gpu_name or "N/A"
                gpus = offer.num_gpus or 0
                vram = offer.display_gpu_ram if hasattr(offer, "display_gpu_ram") else "N/A"
                price = f"${offer.dph_total:.3f}" if offer.dph_total else "N/A"
                rel = f"{offer.reliability2:.2f}" if offer.reliability2 else "N/A"
                print(f"{idx:<4} {offer.id:<10} {gpu:<18} {gpus:<5} {vram:<8} {price:<8} {rel:<6}")
            print("-" * 78)

            try:
                choice = input(f"Enter number (1-{len(offers)}) or offer ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                return False, "Selection cancelled"

            selected = None
            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(offers):
                    selected = offers[num - 1]
                else:
                    for offer in offers:
                        if offer.id == num:
                            selected = offer
                            break

            if not selected:
                return False, "Invalid selection"

            instance_id = client.create_instance(
                offer_id=selected.id,
                image=image,
                disk=disk,
                label=label,
                onstart=onstart,
                direct=direct,
            )

            self.ctx.variables["_vast_instance_id"] = str(instance_id)
            self.ctx.variables["VAST_ID"] = str(instance_id)
            self.recipe.hosts[host_name] = f"vast:{instance_id}"

            return True, f"Created instance {instance_id} from offer {selected.id}"

        except (VastAPIError, RuntimeError) as e:
            return False, str(e)

    def _cmd_vast_wait(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > vast.wait <instance_id> timeout=10m poll=10s stop_on_fail=true"""
        from ..services.vast_api import get_vast_client, VastAPIError

        instance_id = None
        timeout = 600
        poll_interval = 10
        stop_on_fail = True

        for arg in args:
            if "=" in arg:
                key, _, value = arg.partition("=")
                if key == "timeout":
                    timeout = self._parse_duration(self._interpolate(value))
                elif key in ("poll", "poll_interval"):
                    poll_interval = self._parse_duration(self._interpolate(value))
                elif key == "stop_on_fail":
                    stop_on_fail = value.lower() in ("1", "true", "yes", "y")
                continue
            if instance_id is None:
                instance_id = self._interpolate(arg)

        if not instance_id:
            instance_id = self.ctx.variables.get("_vast_instance_id")
        if not instance_id:
            instance_id = self.ctx.variables.get("VAST_ID")
        if not instance_id:
            return False, "No instance ID provided for vast.wait"

        try:
            inst_id = int(instance_id)
        except ValueError:
            return False, f"Invalid instance ID: {instance_id}"

        self.ctx.variables["_vast_instance_id"] = str(inst_id)

        try:
            client = get_vast_client()
            start_time = time.time()
            last_status = "unknown"
            while time.time() - start_time < timeout:
                instance = client.get_instance(inst_id)
                last_status = instance.actual_status or "unknown"
                ssh_ready = bool(instance.ssh_host and instance.ssh_port)

                if instance.is_running and ssh_ready:
                    self.ctx.variables["_vast_ssh_host"] = instance.ssh_host or ""
                    self.ctx.variables["_vast_ssh_port"] = str(instance.ssh_port or "")
                    msg = f"Instance {inst_id} is ready ({last_status})"
                    self.log(msg)
                    return True, msg

                self.log(f"Waiting for instance {inst_id}... ({last_status})")
                time.sleep(poll_interval)

            msg = f"Instance {inst_id} not ready after {_format_duration(timeout)} (status: {last_status})"
            if stop_on_fail:
                try:
                    client.stop_instance(inst_id)
                    msg += "; instance stopped"
                except VastAPIError as e:
                    msg += f"; failed to stop instance: {e}"
            self.log(msg)
            return False, msg

        except (VastAPIError, RuntimeError) as e:
            msg = f"Vast wait failed: {e}"
            self.log(msg)
            return False, msg

    def _cmd_vast_cost(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > vast.cost <instance_id>"""
        from ..services.vast_api import get_vast_client, VastAPIError
        from ..services.pricing import load_pricing_settings, format_currency
        from ..config import load_config

        instance_id = None
        if args:
            instance_id = self._interpolate(args[0])
        if not instance_id:
            instance_id = self.ctx.variables.get("_vast_instance_id")
        if not instance_id:
            instance_id = self.ctx.variables.get("VAST_ID")
        if not instance_id:
            msg = "Vast cost skipped: no instance ID provided"
            self.log(msg)
            return True, msg

        try:
            inst_id = int(instance_id)
        except ValueError:
            msg = f"Vast cost skipped: invalid instance ID '{instance_id}'"
            self.log(msg)
            return True, msg

        try:
            client = get_vast_client()
            inst = client.get_instance(inst_id)
            hourly_usd = inst.dph_total or 0.0

            if hourly_usd <= 0:
                msg = f"Vast cost skipped: no pricing for instance {inst_id}"
                self.log(msg)
                return True, msg

            start_time = self.ctx.start_time or datetime.now()
            duration_secs = (datetime.now() - start_time).total_seconds()
            cost_usd = hourly_usd * (duration_secs / 3600.0)

            settings = load_pricing_settings()
            config = load_config()
            display_curr = config.get("ui", {}).get("currency", settings.display_currency)
            rates = settings.exchange_rates

            usage_str = _format_duration(duration_secs)
            cost_line = f"${cost_usd:.4f}"
            if display_curr != "USD":
                converted = rates.convert(cost_usd, "USD", display_curr)
                cost_line = f"${cost_usd:.4f} ({format_currency(converted, display_curr)})"

            msg = (
                f"Vast usage: {usage_str}, "
                f"instance {inst_id}, "
                f"{inst.gpu_name or 'GPU'} @ ${hourly_usd:.4f}/hr, "
                f"total cost {cost_line}"
            )
            self.log(msg)
            return True, msg

        except (VastAPIError, RuntimeError) as e:
            msg = f"Vast cost skipped: {e}"
            self.log(msg)
            return True, msg

    def _cmd_sleep(self, args: List[str]) -> tuple[bool, str]:
        """Handle: > sleep duration"""
        if not args:
            return False, "Usage: sleep 10s/5m/1h"

        # Interpolate the duration argument
        duration_str = self._interpolate(args[0])
        duration = self._parse_duration(duration_str)
        time.sleep(duration)
        return True, f"Slept for {duration}s"

    def _exec_execute(self, step: DSLStep) -> tuple[bool, str]:
        """Execute remote command: host: command"""
        window_name = step.host
        commands = self._interpolate(step.commands)

        if self.visual:
            # Send text to kitty window
            text = commands + "\n"
            ok = self.kitty.send_text(window_name, text)

            if step.background:
                # Don't wait for completion
                return ok, "Command sent (background)"
            else:
                # Wait a bit for command to start
                time.sleep(1)
                return ok, "Command sent"
        else:
            # Non-visual mode: use SSH directly
            window = self.ctx.windows.get(window_name)
            if not window:
                return False, f"Unknown window: {window_name}"

            host = window.host
            if host == "local":
                result = subprocess.run(
                    commands,
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0, result.stdout or result.stderr
            else:
                ssh_args = _build_ssh_args(host, command=commands, tty=False)
                result = subprocess.run(
                    ssh_args,
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0, result.stdout or result.stderr

    def _exec_transfer(self, step: DSLStep) -> tuple[bool, str]:
        """Execute file transfer: source -> dest"""
        from ..services.transfer_engine import TransferEngine
        from ..core.models import TransferEndpoint

        source = self._interpolate(step.source)
        dest = self._interpolate(step.dest)

        # Parse endpoints
        src_endpoint = self._parse_endpoint(source)
        dst_endpoint = self._parse_endpoint(dest)

        engine = TransferEngine()
        hosts = self._build_transfer_hosts()
        result = engine.transfer(
            source=src_endpoint,
            destination=dst_endpoint,
            hosts=hosts,
        )

        if result.success:
            return True, f"Transferred {result.bytes_transferred} bytes"
        return False, result.message

    def _exec_wait(self, step: DSLStep) -> tuple[bool, str]:
        """Execute wait condition."""
        target = step.target
        pattern = step.pattern
        condition = step.condition
        timeout = step.timeout or 300

        start = time.time()
        poll_interval = 5

        while time.time() - start < timeout:
            # Check pattern match in terminal output
            if pattern and target:
                if self.visual:
                    text = self.kitty.get_text(target)
                    if re.search(pattern, text):
                        return True, f"Pattern matched: {pattern}"
                else:
                    # Non-visual: can't read terminal
                    pass

            # Check file condition
            if condition and condition.startswith("file:"):
                filepath = condition[5:]
                filepath = self._interpolate(filepath)

                # Resolve host from target
                window = self.ctx.windows.get(target)
                if window and window.host != "local":
                    # Remote file check
                    ssh_args = _build_ssh_args(
                        window.host,
                        command=f"test -f {filepath} && echo exists",
                        tty=False,
                    )
                    result = subprocess.run(
                        ssh_args,
                        capture_output=True,
                        text=True,
                    )
                    if "exists" in result.stdout:
                        return True, f"File found: {filepath}"
                else:
                    # Local file check
                    if os.path.exists(os.path.expanduser(filepath)):
                        return True, f"File found: {filepath}"

            # Check port condition
            if condition and condition.startswith("port:"):
                port = int(condition[5:])
                # Check if port is open
                window = self.ctx.windows.get(target)
                host = "localhost"
                if window and window.host != "local":
                    host = _host_from_ssh_spec(window.host).hostname
                result = subprocess.run(
                    ["nc", "-z", host, str(port)],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True, f"Port {port} is open"

            self.log(f"  Waiting... ({int(time.time() - start)}s / {timeout}s)")
            time.sleep(poll_interval)

        return False, f"Timeout after {timeout}s"

    def _resolve_host(self, host_ref: str) -> str:
        """Resolve @host reference to actual host."""
        if host_ref.startswith('@'):
            name = host_ref[1:]
            host = self.recipe.hosts.get(name, name)
        else:
            host = host_ref

        if host.startswith("vast:"):
            return _resolve_vast_host(host[5:])
        return host

    def _interpolate(self, text: str) -> str:
        """Interpolate variables and secrets."""
        def replace(match):
            ref = match.group(1)
            if ref.startswith('secret:'):
                secret_name = ref[7:]
                return self.secrets.get(secret_name) or ""
            return self.ctx.variables.get(ref, match.group(0))

        return re.sub(r'\$\{([^}]+)\}', replace, text)

    def _parse_endpoint(self, spec: str) -> 'TransferEndpoint':
        """Parse transfer endpoint: @host:/path or /local/path"""
        from ..core.models import TransferEndpoint

        if spec.startswith('@'):
            # Remote: @host:/path
            if ':' in spec:
                host_part, path = spec.split(':', 1)
                host_name = host_part[1:]
                host = self.recipe.hosts.get(host_name, host_name)
                return TransferEndpoint(type="host", path=path, host_id=host)
            else:
                return TransferEndpoint(type="host", path="/", host_id=spec[1:])
        else:
            # Local path
            return TransferEndpoint(type="local", path=os.path.expanduser(spec))

    def _build_transfer_hosts(self) -> Dict[str, Host]:
        """Build host mapping for transfers from recipe host specs."""
        hosts: Dict[str, Host] = {}
        for spec in self.recipe.hosts.values():
            if spec == "local":
                continue
            resolved_spec = spec
            if spec.startswith("vast:"):
                resolved_spec = _resolve_vast_host(spec[5:])
            hosts[spec] = _host_from_ssh_spec(resolved_spec)
        return hosts

    def _parse_duration(self, value: str) -> int:
        """Parse duration: 10s, 5m, 1h"""
        value = value.strip().lower()
        if value.endswith('h'):
            return int(value[:-1]) * 3600
        elif value.endswith('m'):
            return int(value[:-1]) * 60
        elif value.endswith('s'):
            return int(value[:-1])
        return int(value)


def run_recipe(
    path: str,
    visual: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
    host_overrides: Optional[Dict[str, str]] = None,
    var_overrides: Optional[Dict[str, str]] = None,
) -> bool:
    """
    Load and execute a DSL recipe file.

    Args:
        path: Path to .recipe file
        visual: Use kitty visual mode
        log_callback: Optional log callback
        host_overrides: Override hosts (e.g., {"gpu": "vast:12345"})
        var_overrides: Override variables (e.g., {"MODEL": "mistral"})

    Returns:
        True if successful
    """
    recipe = parse_recipe(path)

    # Apply host overrides
    if host_overrides:
        for name, value in host_overrides.items():
            # Handle vast:ID format
            if value.startswith("vast:"):
                instance_id = value[5:]
                recipe.hosts[name] = f"vast:{instance_id}"
                if not var_overrides or "VAST_ID" not in var_overrides:
                    recipe.variables["VAST_ID"] = instance_id
            else:
                recipe.hosts[name] = value

    # Apply variable overrides
    if var_overrides:
        for name, value in var_overrides.items():
            recipe.variables[name] = value

    executor = DSLExecutor(recipe, log_callback=log_callback, visual=visual)
    return executor.execute()


def _resolve_vast_host(instance_id: str) -> str:
    """Resolve vast.ai instance ID to SSH host spec."""
    from ..services.vast_api import get_vast_client

    try:
        client = get_vast_client()
        instance = client.get_instance(int(instance_id))

        if instance.ssh_host and instance.ssh_port:
            return f"root@{instance.ssh_host} -p {instance.ssh_port}"
        return f"vast-{instance_id}"

    except Exception:
        return f"vast-{instance_id}"
