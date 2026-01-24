# tmux-trainsh DSL executor
# Executes parsed DSL recipes using remote tmux sessions for persistence

import subprocess
import time
import re
import os
import shlex
import getpass
from typing import Optional, Dict, List, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from .dsl_parser import DSLRecipe, DSLStep, StepType, parse_recipe
from .execution_log import ExecutionLogger
from .secrets import get_secrets_manager
from .models import Host, HostType
from .job_state import (
    JobState, JobStateManager, generate_job_id, get_tmux_session_name
)


@dataclass
class WindowInfo:
    """Tracks a remote tmux session."""
    name: str
    host: str
    remote_session: Optional[str] = None  # Remote tmux session name (for nohup-like behavior)


@dataclass
class ExecutionContext:
    """Runtime context for recipe execution."""
    recipe: DSLRecipe
    variables: Dict[str, str] = field(default_factory=dict)
    windows: Dict[str, WindowInfo] = field(default_factory=dict)
    exec_id: str = ""
    job_id: str = ""  # Persistent job ID for resume
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


def _build_ssh_args(spec: str, command: Optional[str] = None, tty: bool = False, set_term: bool = False) -> List[str]:
    """Build SSH command args from a host spec and optional command.

    Args:
        spec: SSH host spec (e.g., "user@host -p 22")
        command: Optional command to run on remote
        tty: Request a TTY (-t flag)
        set_term: Set TERM and LC_ALL for compatibility
    """
    host, options = _split_ssh_spec(spec)
    args = ["ssh"]
    if tty:
        args.append("-t")
    args.extend(options)
    args.append(host)

    # Environment prefix for remote compatibility
    env_prefix = "TERM=xterm-256color LC_ALL=en_US.UTF-8"

    if set_term:
        # Wrap command to set env for compatibility with servers missing xterm-256color terminfo
        if command:
            args.append(f"{env_prefix} {command}")
        else:
            args.append(f"{env_prefix} exec bash -l")
    elif command:
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



class DSLExecutor:
    """
    Executes DSL recipes step by step.

    Integrates with:
    - Remote tmux sessions for persistent command execution
    - TransferEngine for file transfers
    - VastAPI for GPU instance management

    Architecture:
    - Commands run in remote tmux sessions (survive SSH disconnect)
    - No local tmux needed - use Ghostty/terminal splits to view
    - Manual attach: ssh host && tmux attach -t <session_name>
    """

    def __init__(
        self,
        recipe: DSLRecipe,
        log_callback: Optional[Callable[[str], None]] = None,
        job_id: Optional[str] = None,
        recipe_path: Optional[str] = None,
        is_resuming: bool = False,
        allow_host_execute: bool = False,
    ):
        """
        Initialize executor.

        Args:
            recipe: Parsed DSL recipe
            log_callback: Optional callback for log messages
            job_id: Optional job ID for resume (if None, generates new one)
            recipe_path: Optional path to recipe file (for state persistence)
            is_resuming: Whether this is a resume execution (affects sync strategy)
        """
        self.recipe = recipe
        self.log_callback = log_callback or print
        self.recipe_path = recipe_path
        self.is_resuming = is_resuming
        self.allow_host_execute = allow_host_execute

        # Job state management
        self.state_manager = JobStateManager()
        self.job_state: Optional[JobState] = None

        # Generate or use provided job ID
        job_id = job_id or generate_job_id()

        # Runtime state
        self.ctx = ExecutionContext(
            recipe=recipe,
            variables=dict(recipe.variables),
            exec_id=self._generate_id(),
            job_id=job_id,
            start_time=datetime.now(),
            log_callback=self.log_callback,
        )

        # Secrets manager
        self.secrets = get_secrets_manager()

        # Execution logger
        self.logger: Optional[ExecutionLogger] = None

        # SSH retry settings
        self.ssh_max_retries = 10
        self.ssh_retry_base_interval = 30  # seconds
        self.ssh_retry_max_interval = 300  # 5 minutes

        # Track last sudo auth prompt per host to reduce repeated prompts
        self._sudo_last_prompt: Dict[str, float] = {}

    def _generate_id(self) -> str:
        """Generate unique execution ID."""
        import uuid
        return str(uuid.uuid4())[:8]

    def _save_checkpoint(self, step_num: int, status: str = "running") -> None:
        """Save current execution state for resume capability."""
        if not self.recipe_path:
            return

        # Collect all windows (including local hosts)
        hosts = {}
        for name, window in self.ctx.windows.items():
            if window.host:
                hosts[name] = window.host

        # Get vast instance tracking info
        vast_instance_id = self.ctx.variables.get("VAST_ID") or self.ctx.variables.get("_vast_instance_id")
        vast_start_time = self.ctx.variables.get("_vast_start_time")

        self.job_state = JobState(
            job_id=self.ctx.job_id,
            recipe_path=os.path.abspath(os.path.expanduser(self.recipe_path)),
            recipe_name=self.recipe.name,
            current_step=step_num,
            total_steps=len(self.recipe.steps),
            status=status,
            variables=dict(self.ctx.variables),
            hosts=hosts,
            tmux_session=get_tmux_session_name(self.ctx.job_id),
            vast_instance_id=vast_instance_id,
            vast_start_time=vast_start_time,
        )
        self.state_manager.save(self.job_state)

    def _load_checkpoint(self, job_id: str) -> Optional[JobState]:
        """Load a saved checkpoint."""
        return self.state_manager.load(job_id)

    def _clear_checkpoint(self) -> None:
        """Clear checkpoint after successful completion."""
        if self.job_state:
            self.job_state.status = "completed"
            self.state_manager.save(self.job_state)

    def log(self, msg: str) -> None:
        """Log a message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{timestamp}] {msg}")

    def execute(self, resume_from: int = 0) -> bool:
        """
        Execute all steps in the recipe.

        Args:
            resume_from: Step index to resume from (0 = start from beginning)

        Returns:
            True if all steps completed successfully
        """
        self.log(f"Starting recipe: {self.recipe.name}")
        self.log(f"Job ID: {self.ctx.job_id}")
        self.log(f"Execution ID: {self.ctx.exec_id}")

        if resume_from > 0:
            self.log(f"Resuming from step {resume_from + 1}")

        # Initialize logger with job_id
        self.logger = ExecutionLogger(
            job_id=self.ctx.job_id,
            recipe_name=self.recipe.name,
        )
        self.logger.start(
            self.recipe.name,
            self.ctx.variables,
            self.recipe.hosts,
            self.recipe_path or "",
        )

        success = True

        for i, step in enumerate(self.recipe.steps):
            step_num = i + 1
            # Skip already completed steps on resume
            if i < resume_from:
                self.log(f"⏭ Step {step_num}: Skipping (already completed)")
                if self.logger:
                    self.logger.log_detail("skip", f"Step {step_num} skipped (resume)", {"step_num": step_num})
                continue

            step_name = f"Step {step_num}: {step.raw}"
            self.log(f"→ {step_name}")

            # Build step details for logging
            step_details = {
                "host": step.host,
                "command": step.command,
                "commands": step.commands,
                "args": step.args,
                "source": step.source,
                "dest": step.dest,
                "target": step.target,
                "pattern": step.pattern,
                "condition": step.condition,
                "timeout": step.timeout,
                "background": step.background,
            }

            if self.logger:
                self.logger.step_start(step_num, step.raw, step.type.value, step_details)

            # Save checkpoint before executing step
            self._save_checkpoint(i)

            start = datetime.now()

            try:
                ok, output = self._execute_step(step)
                duration_ms = int((datetime.now() - start).total_seconds() * 1000)

                if self.logger:
                    if output:
                        self.logger.step_output(step_num, output, "result")
                    self.logger.step_end(step_num, ok, duration_ms, result=output if ok else "", error="" if ok else output)

                if not ok:
                    self.log(f"  ✗ Failed: {output}")
                    self._save_checkpoint(i, status="failed")
                    success = False
                    break
                else:
                    self.log(f"  ✓ Done ({duration_ms}ms)")

            except Exception as e:
                import traceback
                error_detail = traceback.format_exc()
                self.log(f"  ✗ Error: {e}")
                if self.logger:
                    self.logger.step_output(step_num, error_detail, "exception")
                    self.logger.step_end(step_num, False, 0, error=str(e))
                self._save_checkpoint(i, status="failed")
                success = False
                break

        # Finalize
        total_ms = int((datetime.now() - self.ctx.start_time).total_seconds() * 1000)
        if self.logger:
            self.logger.end(success, total_ms, dict(self.ctx.variables))

        if success:
            self._clear_checkpoint()
            status = "completed"
        else:
            status = "failed"

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
        if cmd == "tmux.open":
            return self._cmd_tmux_open(args)
        elif cmd == "tmux.close":
            return self._cmd_tmux_close(args)
        elif cmd == "tmux.config":
            return self._cmd_tmux_config(args)
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

    def _cmd_tmux_open(self, args: List[str]) -> tuple[bool, str]:
        """
        Handle: tmux.open @host as name

        Creates a remote tmux session via SSH for persistent command execution.
        Commands survive SSH disconnect - attach manually with:
            ssh host && tmux attach -t <session_name>
        """
        if len(args) < 3 or args[1] != "as":
            return False, "Usage: tmux.open @host as name"

        host_ref = args[0]
        window_name = args[2]

        # Resolve host
        host = self._resolve_host(host_ref)

        # Generate remote session name (unique per job + window)
        remote_session_name = f"train_{self.ctx.job_id[:8]}_{window_name}"

        if self.logger:
            self.logger.log_detail("tmux_open", f"Creating remote tmux session {window_name}", {
                "host_ref": host_ref,
                "resolved_host": host,
                "window_name": window_name,
                "remote_session": remote_session_name if host != "local" else None,
            })

        if host == "local":
            # Local: create tmux session for persistence (same as remote)
            self.ctx.windows[window_name] = WindowInfo(
                name=window_name,
                host=host,
                remote_session=remote_session_name,
            )
            # Create local tmux session
            create_cmd = f"tmux new-session -d -s {remote_session_name} 2>/dev/null || tmux has-session -t {remote_session_name}"
            try:
                result = subprocess.run(
                    create_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0 and "already exists" not in result.stderr:
                    return False, f"Failed to create local tmux session: {result.stderr}"
                self.log(f"  Local tmux session: {remote_session_name}")
                self.log(f"  Attach with: tmux attach -t {remote_session_name}")
                return True, f"Created local tmux session: {remote_session_name}"
            except subprocess.TimeoutExpired:
                return False, "Timeout creating local tmux session"
            except Exception as e:
                return False, str(e)

        # Remote: create tmux session on remote host via SSH
        # Use 'tmux new-session -d -s name' to create detached session
        create_cmd = f"tmux new-session -d -s {remote_session_name} 2>/dev/null || tmux has-session -t {remote_session_name}"
        ssh_args = _build_ssh_args(host, command=create_cmd, tty=False)

        try:
            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                # Session might already exist, which is fine
                if "already exists" not in result.stderr and "has-session" not in create_cmd:
                    return False, f"Failed to create remote tmux session: {result.stderr}"

            self.ctx.windows[window_name] = WindowInfo(
                name=window_name,
                host=host,
                remote_session=remote_session_name,
            )

            self.log(f"  Remote tmux session: {remote_session_name}")
            self.log(f"  Attach with: ssh {host} -t 'tmux attach -t {remote_session_name}'")

            if self.logger:
                self.logger.log_detail("window_registered", f"Window {window_name} registered", {
                    "window_name": window_name,
                    "host": host,
                    "remote_session": remote_session_name,
                })

            return True, f"Created remote tmux session: {remote_session_name}"

        except subprocess.TimeoutExpired:
            return False, f"SSH timeout creating remote tmux session"
        except Exception as e:
            if self.logger:
                self.logger.log_detail("tmux_error", f"Failed to create session: {e}", {})
            return False, str(e)

    def _cmd_tmux_close(self, args: List[str]) -> tuple[bool, str]:
        """Handle: tmux.close @session

        Kills the remote tmux session via SSH.
        """
        if not args:
            return False, "Usage: tmux.close @session"

        window_name = args[0]
        if not window_name.startswith("@"):
            return False, "Usage: tmux.close @session"
        window_name = window_name[1:]
        window = self.ctx.windows.get(window_name)

        if not window:
            return False, f"Unknown window: {window_name}"

        if not window.remote_session:
            # No tmux session, just unregister
            self.ctx.windows.pop(window_name, None)
            return True, f"Unregistered window: {window_name}"

        if window.host == "local":
            # Local: kill the local tmux session
            kill_cmd = f"tmux kill-session -t {window.remote_session} 2>/dev/null || true"
            try:
                subprocess.run(
                    kill_cmd,
                    shell=True,
                    capture_output=True,
                    timeout=30,
                )
                self.ctx.windows.pop(window_name, None)
                return True, f"Killed local tmux session: {window.remote_session}"
            except Exception as e:
                return False, str(e)

        # Remote: kill the remote tmux session via SSH
        kill_cmd = f"tmux kill-session -t {window.remote_session} 2>/dev/null || true"
        ssh_args = _build_ssh_args(window.host, command=kill_cmd, tty=False)

        try:
            subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if self.logger:
                self.logger.log_detail("tmux_close", f"Killed remote session {window.remote_session}", {
                    "window_name": window_name,
                    "remote_session": window.remote_session,
                })

            self.ctx.windows.pop(window_name, None)
            return True, f"Killed remote session: {window.remote_session}"

        except subprocess.TimeoutExpired:
            self.ctx.windows.pop(window_name, None)
            return True, f"Timeout killing session (unregistered): {window_name}"
        except Exception as e:
            return False, str(e)

    def _cmd_tmux_config(self, args: List[str]) -> tuple[bool, str]:
        """
        Handle: tmux.config @host

        Applies tmux configuration from config.toml to a remote host.
        Writes tmux options to ~/.tmux.conf on the target and reloads.
        """
        if not args:
            return False, "Usage: tmux.config @host"

        host_ref = args[0]
        host = self._resolve_host(host_ref)

        # Load tmux options from config
        from ..config import load_config, get_default_config
        config = load_config()
        tmux_config = config.get("tmux", {})
        tmux_options = tmux_config.get("options", [])

        if not tmux_options:
            tmux_options = get_default_config().get("tmux", {}).get("options", [])

        # Generate tmux.conf content
        lines = [
            "# Generated by tmux-trainsh",
            "# Applied via: tmux.config @host",
            "",
        ]
        lines.extend(tmux_options)
        tmux_conf_content = "\n".join(lines)

        if self.logger:
            self.logger.log_detail("tmux_config", f"Applying tmux config to {host}", {
                "host_ref": host_ref,
                "resolved_host": host,
                "options_count": len(tmux_options),
            })

        if host == "local":
            # Local: write directly
            import os
            from pathlib import Path
            tmux_conf_path = Path(os.path.expanduser("~/.tmux.conf"))
            tmux_conf_path.write_text(tmux_conf_content)

            # Reload if tmux is running
            try:
                subprocess.run(
                    "tmux source-file ~/.tmux.conf 2>/dev/null || true",
                    shell=True,
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                pass

            return True, f"Applied tmux config to local ~/.tmux.conf"

        # Remote: write via SSH
        # Escape the content for shell
        escaped_content = tmux_conf_content.replace("'", "'\"'\"'")
        write_cmd = f"echo '{escaped_content}' > ~/.tmux.conf && tmux source-file ~/.tmux.conf 2>/dev/null || true"
        ssh_args = _build_ssh_args(host, command=write_cmd, tty=False)

        try:
            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return False, f"Failed to apply tmux config: {result.stderr}"

            return True, f"Applied tmux config to {host}"

        except subprocess.TimeoutExpired:
            return False, f"Timeout applying tmux config to {host}"
        except Exception as e:
            return False, str(e)

    def _cmd_notify(self, args: List[str]) -> tuple[bool, str]:
        """Handle: notify "message" """
        message = " ".join(args)
        self.log(f"📢 {message}")

        # Try system notification
        try:
            subprocess.run(
                ['osascript', '-e', f'display notification "{message}" with title "train"'],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

        return True, message

    def _cmd_vast_start(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.start [instance_id]"""
        from ..services.vast_api import get_vast_client, VastAPIError

        try:
            client = get_vast_client()

            # Get instance ID from args or variables
            instance_id = None
            if args:
                instance_id = self._interpolate(args[0])
            if not instance_id:
                instance_id = self.ctx.variables.get("_vast_instance_id")
            if not instance_id:
                instance_id = self.ctx.variables.get("VAST_ID")

            if instance_id:
                try:
                    inst_id = int(instance_id)
                except ValueError:
                    return False, f"Invalid instance ID: {instance_id}"

                if self.logger:
                    self.logger.log_detail("vast_start", f"Getting instance {inst_id}", {"instance_id": inst_id})

                instance = client.get_instance(inst_id)

                # Log instance details
                instance_info = {
                    "id": instance.id,
                    "status": instance.actual_status,
                    "is_running": instance.is_running,
                    "gpu_name": instance.gpu_name,
                    "num_gpus": instance.num_gpus,
                    "ssh_host": instance.ssh_host,
                    "ssh_port": instance.ssh_port,
                    "dph_total": instance.dph_total,
                    "start_date": instance.start_date,
                }
                if self.logger:
                    self.logger.log_vast("get_instance", inst_id, {"instance_id": inst_id}, instance_info, True)

                if instance.is_running:
                    self.ctx.variables["_vast_instance_id"] = str(inst_id)
                    # Record start time from API if available
                    if instance.start_date:
                        self.ctx.variables["_vast_start_time"] = datetime.fromtimestamp(instance.start_date).isoformat()
                    else:
                        self.ctx.variables["_vast_start_time"] = datetime.now().isoformat()

                    if self.logger:
                        self.logger.log_variable("_vast_instance_id", str(inst_id), "vast.start")
                        self.logger.log_variable("_vast_start_time", self.ctx.variables["_vast_start_time"], "vast.start")

                    return True, f"Instance already running: {inst_id}"

                try:
                    if self.logger:
                        self.logger.log_detail("vast_start", f"Starting instance {inst_id}", {"instance_id": inst_id})

                    client.start_instance(inst_id)
                    self.ctx.variables["_vast_instance_id"] = str(inst_id)
                    # Record start time now
                    self.ctx.variables["_vast_start_time"] = datetime.now().isoformat()

                    if self.logger:
                        self.logger.log_vast("start_instance", inst_id, {"instance_id": inst_id}, {"started": True}, True)
                        self.logger.log_variable("_vast_instance_id", str(inst_id), "vast.start")
                        self.logger.log_variable("_vast_start_time", self.ctx.variables["_vast_start_time"], "vast.start")

                    return True, f"Started instance: {inst_id}"
                except VastAPIError as e:
                    msg = f"Failed to start instance {inst_id}: {e}"
                    if self.logger:
                        self.logger.log_vast("start_instance", inst_id, {"instance_id": inst_id}, {"error": str(e)}, False)
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
            if self.logger:
                self.logger.log_vast("create_instance", instance_id, {"offer_id": offers[0].id}, {"created": True}, True)
            return True, f"Created instance: {instance_id}"

        except (VastAPIError, RuntimeError) as e:
            if self.logger:
                self.logger.log_vast("vast_start", None, {"args": args}, {"error": str(e)}, False)
            return False, str(e)

    def _cmd_vast_stop(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.stop <instance_id>"""
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

            if self.logger:
                self.logger.log_detail("vast_stop", f"Stopping instance {instance_id}", {"instance_id": instance_id})

            client.stop_instance(int(instance_id))

            if self.logger:
                self.logger.log_vast("stop_instance", int(instance_id), {"instance_id": instance_id}, {"stopped": True}, True)

            return True, f"Stopped instance: {instance_id}"

        except (VastAPIError, RuntimeError) as e:
            return False, str(e)

    def _cmd_vast_pick(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.pick @host gpu=RTX_5090 num_gpus=8 min_gpu_ram=24 (selects from rented instances)"""
        from ..services.vast_api import get_vast_client, VastAPIError

        host_name = None
        gpu_name = None
        num_gpus = None
        min_gpu_ram = None
        max_dph = None
        limit = 20
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

        pick_filters = {
            "host_name": host_name,
            "gpu_name": gpu_name,
            "num_gpus": num_gpus,
            "min_gpu_ram": min_gpu_ram,
            "max_dph": max_dph,
            "limit": limit,
            "skip_if_set": skip_if_set,
        }
        if self.logger:
            self.logger.log_detail("vast_pick", "Picking Vast instance", pick_filters)

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
            if self.logger:
                self.logger.log_vast("pick_existing", existing_id, pick_filters, {"using_existing": True}, True)
                self.logger.log_variable("VAST_ID", str(existing_id), "vast.pick")
            return True, f"Using existing instance: {existing_id}"

        try:
            client = get_vast_client()
            instances = client.list_instances()
            if not instances:
                return False, "No Vast.ai instances found"

            # Log all instances for debugging
            if self.logger:
                instances_info = [
                    {
                        "id": i.id,
                        "status": i.actual_status,
                        "gpu_name": i.gpu_name,
                        "num_gpus": i.num_gpus,
                        "gpu_memory_gb": i.gpu_memory_gb,
                        "dph_total": i.dph_total,
                    }
                    for i in instances
                ]
                self.logger.log_vast("list_instances", None, {}, {"instances": instances_info, "count": len(instances)}, True)

            def matches_filters(instance) -> bool:
                if gpu_name and (instance.gpu_name or "").upper() != gpu_name.upper():
                    return False
                if num_gpus and (instance.num_gpus or 0) < num_gpus:
                    return False
                if min_gpu_ram and instance.gpu_memory_gb < min_gpu_ram:
                    return False
                if max_dph and (instance.dph_total or 0.0) > max_dph:
                    return False
                return True

            instances = [i for i in instances if matches_filters(i)]
            if not instances:
                if self.logger:
                    self.logger.log_detail("vast_pick", "No instances match filters", pick_filters)
                return False, "No Vast.ai instances match filters"

            if limit and limit > 0:
                instances = instances[:limit]

            def status_rank(instance) -> int:
                status = (instance.actual_status or "").lower()
                if status == "running":
                    return 0
                if status in ("stopped", "exited"):
                    return 1
                return 2

            instances = sorted(instances, key=lambda i: (status_rank(i), i.dph_total or 0.0))

            # Log filtered instances
            if self.logger:
                filtered_info = [
                    {
                        "id": i.id,
                        "status": i.actual_status,
                        "gpu_name": i.gpu_name,
                        "num_gpus": i.num_gpus,
                        "dph_total": i.dph_total,
                    }
                    for i in instances
                ]
                self.logger.log_detail("vast_pick", f"Filtered to {len(instances)} instances", {"filtered_instances": filtered_info})

            # Use unified formatter for instance table
            from ..utils.vast_formatter import format_instance_header, format_instance_row, get_currency_settings
            currency = get_currency_settings()
            header, sep = format_instance_header(currency, show_index=True)

            print("\nSelect a Vast.ai instance:")
            print(sep)
            print(header)
            print(sep)
            for idx, inst in enumerate(instances, 1):
                row = format_instance_row(inst, currency, show_index=True, index=idx)
                print(row)
            print(sep)

            try:
                choice = input(f"Enter number (1-{len(instances)}) or instance ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                return False, "Selection cancelled"

            selected = None
            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(instances):
                    selected = instances[num - 1]
                else:
                    for inst in instances:
                        if inst.id == num:
                            selected = inst
                            break

            if not selected:
                return False, "Invalid selection"

            self.ctx.variables["_vast_instance_id"] = str(selected.id)
            self.ctx.variables["VAST_ID"] = str(selected.id)
            self.recipe.hosts[host_name] = f"vast:{selected.id}"

            if self.logger:
                self.logger.log_vast("pick_selected", selected.id, pick_filters, {
                    "selected_id": selected.id,
                    "gpu_name": selected.gpu_name,
                    "status": selected.actual_status,
                }, True)
                self.logger.log_variable("_vast_instance_id", str(selected.id), "vast.pick")
                self.logger.log_variable("VAST_ID", str(selected.id), "vast.pick")

            return True, f"Selected instance {selected.id}"

        except (VastAPIError, RuntimeError) as e:
            if self.logger:
                self.logger.log_vast("pick_error", None, pick_filters, {"error": str(e)}, False)
            return False, str(e)

    def _cmd_vast_wait(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.wait <instance_id> timeout=10m poll=10s stop_on_fail=true"""
        from ..services.vast_api import get_vast_client, VastAPIError
        from ..config import load_config

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

        wait_config = {
            "instance_id": inst_id,
            "timeout": timeout,
            "poll_interval": poll_interval,
            "stop_on_fail": stop_on_fail,
        }
        if self.logger:
            self.logger.log_detail("vast_wait", f"Waiting for instance {inst_id}", wait_config)

        try:
            client = get_vast_client()

            # Auto-attach SSH key if configured
            config = load_config()
            auto_attach = config.get("vast", {}).get("auto_attach_ssh_key", True)
            ssh_key_path = config.get("defaults", {}).get("ssh_key_path", "~/.ssh/id_rsa")

            if auto_attach and ssh_key_path:
                self._ensure_ssh_key_attached(client, ssh_key_path)

            start_time = time.time()
            last_status = "unknown"
            poll_count = 0

            while time.time() - start_time < timeout:
                poll_count += 1
                instance = client.get_instance(inst_id)
                last_status = instance.actual_status or "unknown"
                ssh_ready = bool(instance.ssh_host and instance.ssh_port)
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed

                # Log each poll
                if self.logger:
                    self.logger.log_wait(
                        f"vast:{inst_id}",
                        f"status={last_status},ssh_ready={ssh_ready}",
                        elapsed,
                        remaining,
                        f"poll #{poll_count}: {last_status}"
                    )

                if instance.is_running and ssh_ready:
                    # Print connection details
                    self.log(f"  Connection details for instance {inst_id}:")
                    proxy_cmd = instance.ssh_proxy_command
                    direct_cmd = instance.ssh_direct_command
                    if proxy_cmd:
                        self.log(f"    Proxy SSH: {proxy_cmd}")
                    if direct_cmd:
                        self.log(f"    Direct SSH: {direct_cmd}")

                    if self.logger:
                        self.logger.log_detail("vast_connection", "SSH connection details", {
                            "proxy_command": proxy_cmd,
                            "direct_command": direct_cmd,
                            "ssh_host": instance.ssh_host,
                            "ssh_port": instance.ssh_port,
                            "public_ipaddr": instance.public_ipaddr,
                            "direct_port_start": instance.direct_port_start,
                            "direct_port_end": instance.direct_port_end,
                        })

                    # Try both SSH connection methods
                    ssh_connected = False
                    working_ssh_spec = None

                    # Try direct SSH first (usually faster if available)
                    if direct_cmd and instance.public_ipaddr and instance.direct_port_start:
                        direct_spec = f"root@{instance.public_ipaddr} -p {instance.direct_port_start}"
                        self.log(f"  Trying direct SSH: {direct_cmd}")
                        if self._verify_ssh_connection(direct_spec):
                            ssh_connected = True
                            working_ssh_spec = direct_spec
                            self.log(f"  Direct SSH connected successfully")
                        else:
                            self.log(f"  Direct SSH failed, trying proxy...")

                    # Try proxy SSH if direct failed or not available
                    if not ssh_connected and proxy_cmd:
                        proxy_spec = f"root@{instance.ssh_host} -p {instance.ssh_port}"
                        self.log(f"  Trying proxy SSH: {proxy_cmd}")
                        if self._verify_ssh_connection(proxy_spec):
                            ssh_connected = True
                            working_ssh_spec = proxy_spec
                            self.log(f"  Proxy SSH connected successfully")
                        else:
                            self.log(f"  Proxy SSH failed")

                    if ssh_connected and working_ssh_spec:
                        # Save the working SSH spec to variables
                        if instance.public_ipaddr and instance.direct_port_start and instance.public_ipaddr in working_ssh_spec:
                            self.ctx.variables["_vast_ssh_host"] = instance.public_ipaddr
                            self.ctx.variables["_vast_ssh_port"] = str(instance.direct_port_start)
                        else:
                            self.ctx.variables["_vast_ssh_host"] = instance.ssh_host or ""
                            self.ctx.variables["_vast_ssh_port"] = str(instance.ssh_port or "")

                        # IMPORTANT: Update recipe.hosts with the working SSH spec
                        # This ensures subsequent steps (tmux.open, transfer) use the correct connection
                        for host_name, host_value in list(self.recipe.hosts.items()):
                            if host_value == f"vast:{inst_id}":
                                self.recipe.hosts[host_name] = working_ssh_spec
                                self.log(f"  Updated @{host_name} to use: {working_ssh_spec}")
                                if self.logger:
                                    self.logger.log_detail("vast_host_update", f"Updated host {host_name}", {
                                        "host_name": host_name,
                                        "old_value": f"vast:{inst_id}",
                                        "new_value": working_ssh_spec,
                                    })

                        # Disable Vast.ai auto-tmux so we can control our own tmux session
                        disable_cmd = "touch ~/.no_auto_tmux"
                        ssh_args = _build_ssh_args(working_ssh_spec, command=disable_cmd, tty=False)
                        try:
                            subprocess.run(ssh_args, capture_output=True, text=True, timeout=10)
                            if self.logger:
                                self.logger.log_detail("vast_config", "Disabled auto-tmux", {"command": disable_cmd})
                        except Exception:
                            pass  # Best effort, ignore errors

                        msg = f"Instance {inst_id} is ready ({last_status})"
                        self.log(msg)

                        if self.logger:
                            self.logger.log_vast("wait_ready", inst_id, wait_config, {
                                "status": last_status,
                                "ssh_host": self.ctx.variables["_vast_ssh_host"],
                                "ssh_port": self.ctx.variables["_vast_ssh_port"],
                                "connection_method": "direct" if instance.public_ipaddr in working_ssh_spec else "proxy",
                                "elapsed_sec": elapsed,
                                "poll_count": poll_count,
                            }, True)
                            self.logger.log_variable("_vast_ssh_host", self.ctx.variables["_vast_ssh_host"], "vast.wait")
                            self.logger.log_variable("_vast_ssh_port", self.ctx.variables["_vast_ssh_port"], "vast.wait")

                        return True, msg
                    else:
                        # SSH not ready yet, keep waiting
                        self.log(f"Instance {inst_id} running but SSH not accessible yet...")
                        if self.logger:
                            self.logger.log_detail("vast_wait", "SSH not accessible yet", {
                                "proxy_command": proxy_cmd,
                                "direct_command": direct_cmd,
                                "ssh_host": instance.ssh_host,
                                "ssh_port": instance.ssh_port,
                                "public_ipaddr": instance.public_ipaddr,
                                "direct_port_start": instance.direct_port_start,
                            })

                self.log(f"Waiting for instance {inst_id}... ({last_status})")
                time.sleep(poll_interval)

            msg = f"Instance {inst_id} not ready after {_format_duration(timeout)} (status: {last_status})"
            if self.logger:
                self.logger.log_vast("wait_timeout", inst_id, wait_config, {
                    "status": last_status,
                    "elapsed_sec": int(time.time() - start_time),
                    "poll_count": poll_count,
                }, False)

            if stop_on_fail:
                try:
                    client.stop_instance(inst_id)
                    msg += "; instance stopped"
                    if self.logger:
                        self.logger.log_vast("stop_instance", inst_id, {"reason": "wait_timeout"}, {"stopped": True}, True)
                except VastAPIError as e:
                    msg += f"; failed to stop instance: {e}"
            self.log(msg)
            return False, msg

        except (VastAPIError, RuntimeError) as e:
            msg = f"Vast wait failed: {e}"
            if self.logger:
                self.logger.log_vast("wait_error", inst_id, wait_config, {"error": str(e)}, False)
            self.log(msg)
            return False, msg

    def _verify_ssh_connection(self, ssh_spec: str, timeout: int = 10) -> bool:
        """Verify that SSH connection to a host is working."""
        try:
            ssh_args = _build_ssh_args(ssh_spec, command="echo ok", tty=False)
            # Add connection timeout and batch mode
            ssh_args.insert(1, "-o")
            ssh_args.insert(2, f"ConnectTimeout={timeout}")
            ssh_args.insert(3, "-o")
            ssh_args.insert(4, "BatchMode=yes")
            ssh_args.insert(5, "-o")
            ssh_args.insert(6, "StrictHostKeyChecking=no")

            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )

            if self.logger:
                self.logger.log_ssh(
                    ssh_spec, "echo ok",
                    result.returncode,
                    result.stdout,
                    result.stderr,
                    0
                )

            return result.returncode == 0 and "ok" in result.stdout
        except (subprocess.TimeoutExpired, Exception) as e:
            if self.logger:
                self.logger.log_detail("ssh_verify_failed", f"SSH verify failed: {e}", {"ssh_spec": ssh_spec})
            return False

    def _ensure_ssh_key_attached(self, client, ssh_key_path: str) -> None:
        """Ensure the local SSH public key is attached to Vast.ai account."""
        import os

        # Get public key path
        pub_key_path = os.path.expanduser(ssh_key_path)
        if not pub_key_path.endswith(".pub"):
            pub_key_path = pub_key_path + ".pub"

        if not os.path.exists(pub_key_path):
            self.log(f"SSH public key not found: {pub_key_path}")
            if self.logger:
                self.logger.log_detail("ssh_key", f"Public key not found: {pub_key_path}", {})
            return

        # Read public key content
        with open(pub_key_path, "r") as f:
            pub_key_content = f.read().strip()

        if not pub_key_content:
            self.log(f"SSH public key is empty: {pub_key_path}")
            return

        # Extract key fingerprint or key content for comparison
        # SSH public key format: type base64content comment
        key_parts = pub_key_content.split()
        if len(key_parts) < 2:
            self.log(f"Invalid SSH public key format: {pub_key_path}")
            return

        key_type = key_parts[0]
        key_data = key_parts[1]

        try:
            # List existing keys on Vast.ai
            existing_keys = client.list_ssh_keys()

            if self.logger:
                self.logger.log_detail("ssh_key", f"Found {len(existing_keys)} existing keys on Vast.ai", {
                    "existing_count": len(existing_keys)
                })

            # Check if our key is already registered
            key_exists = False
            for existing_key in existing_keys:
                # Compare the key data portion
                existing_content = existing_key.get("ssh_key", "")
                existing_parts = existing_content.split()
                if len(existing_parts) >= 2 and existing_parts[1] == key_data:
                    key_exists = True
                    if self.logger:
                        self.logger.log_detail("ssh_key", "SSH key already registered on Vast.ai", {
                            "key_id": existing_key.get("id"),
                            "label": existing_key.get("label"),
                        })
                    break

            if not key_exists:
                # Add the key
                self.log(f"Adding SSH key to Vast.ai account...")
                try:
                    client.add_ssh_key(pub_key_content, label="tmux-trainsh")
                    self.log(f"SSH key added successfully")
                    if self.logger:
                        self.logger.log_detail("ssh_key", "SSH key added to Vast.ai", {
                            "key_type": key_type,
                            "key_path": pub_key_path,
                        })
                except Exception as add_err:
                    # Ignore "already exists" errors - the key is registered, that's fine
                    err_str = str(add_err).lower()
                    if "already exists" in err_str or "duplicate" in err_str:
                        self.log(f"SSH key already exists on Vast.ai")
                        if self.logger:
                            self.logger.log_detail("ssh_key", "SSH key already exists (ignored)", {
                                "key_type": key_type,
                            })
                    else:
                        raise add_err

        except Exception as e:
            # Don't fail the wait operation for SSH key errors
            self.log(f"Warning: Failed to manage SSH keys: {e}")
            if self.logger:
                self.logger.log_detail("ssh_key_warning", f"Failed to manage SSH keys: {e}", {})

    def _cmd_vast_cost(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.cost <instance_id>"""
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

        # Get start time from job state
        vast_start_time = self.ctx.variables.get("_vast_start_time")
        if not vast_start_time:
            msg = "Vast cost skipped: no start time recorded in job state"
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

            # Calculate duration from saved start time
            saved_start = datetime.fromisoformat(vast_start_time)
            duration_secs = (datetime.now() - saved_start).total_seconds()
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
        """Handle: sleep duration"""
        if not args:
            return False, "Usage: sleep 10s/5m/1h"

        # Interpolate the duration argument
        duration_str = self._interpolate(args[0])
        duration = self._parse_duration(duration_str)
        time.sleep(duration)
        return True, f"Slept for {duration}s"

    def _exec_execute(self, step: DSLStep) -> tuple[bool, str]:
        """Execute command: @session > command

        Commands run in remote tmux sessions via SSH (survives SSH disconnect).
        For local hosts, commands run directly.
        """
        window_name = step.host
        commands = self._interpolate(step.commands)

        if self.logger:
            self.logger.log_detail("execute", f"Executing command on {window_name}", {
                "window_name": window_name,
                "commands": commands,
                "background": step.background,
            })

        window = self._resolve_window(window_name)
        if not window:
            return False, f"Unknown window: {window_name}"

        ok, msg = self._ensure_sudo_auth(window, commands)
        if not ok:
            return False, msg

        timeout = step.timeout or 600  # Default 10 min timeout
        start_time = time.time()
        host = window.host
        remote_session = window.remote_session

        if host == "local":
            # Local: use local tmux session if available, otherwise run directly
            if remote_session:
                if step.background:
                    # Background: just send the command, use wait idle to check completion
                    tmux_cmd = f"tmux send-keys -t {remote_session} {shlex.quote(commands)} Enter"
                    try:
                        result = subprocess.run(
                            tmux_cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        if self.logger:
                            self.logger.log_detail("send_keys", f"Sent to local tmux {window_name}", {
                                "commands": commands,
                                "remote_session": remote_session,
                                "background": True,
                                "success": result.returncode == 0,
                            })
                        return result.returncode == 0, "Command sent (background)"
                    except subprocess.TimeoutExpired:
                        return False, "Timeout sending command to local tmux"
                else:
                    # Foreground: use tmux wait-for for synchronization (or idle check on resume)
                    if self.is_resuming:
                        # On resume, use idle check since we may have missed the wait-for signal
                        tmux_cmd = f"tmux send-keys -t {remote_session} {shlex.quote(commands)} Enter"
                        try:
                            subprocess.run(tmux_cmd, shell=True, capture_output=True, timeout=30)
                            # Wait a moment for command to start
                            time.sleep(0.5)
                            # Poll until pane is idle with double-check
                            window = WindowInfo(name="local", host=host, remote_session=remote_session)
                            ok, msg = self._wait_for_idle(window, timeout)
                            duration_ms = int((time.time() - start_time) * 1000)
                            if self.logger:
                                self.logger.log_ssh("local_tmux", commands, 0 if ok else 1, "", "", duration_ms)
                            return ok, msg
                        except subprocess.TimeoutExpired:
                            return False, f"Command timed out after {timeout}s"
                    else:
                        # Fresh run: use tmux wait-for
                        import uuid
                        signal = f"train_{uuid.uuid4().hex[:8]}"
                        # Wrap command: run command, then signal completion
                        wrapped_cmd = f"( {commands} ); tmux wait-for -S {signal}"
                        tmux_cmd = f"tmux send-keys -t {remote_session} {shlex.quote(wrapped_cmd)} Enter"

                        try:
                            subprocess.run(tmux_cmd, shell=True, capture_output=True, timeout=30)
                            # Wait for the signal
                            wait_result = subprocess.run(
                                f"tmux wait-for {signal}",
                                shell=True,
                                capture_output=True,
                                timeout=timeout,
                            )
                            duration_ms = int((time.time() - start_time) * 1000)
                            if self.logger:
                                self.logger.log_ssh("local_tmux", commands, wait_result.returncode, "", "", duration_ms)
                            if wait_result.returncode == 0:
                                return True, "Command completed"
                            return False, f"Command failed or wait-for timed out"
                        except subprocess.TimeoutExpired:
                            return False, f"Command timed out after {timeout}s"
            else:
                # No tmux session, run directly
                try:
                    result = subprocess.run(
                        commands,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    duration_ms = int((time.time() - start_time) * 1000)
                    if self.logger:
                        self.logger.log_ssh("local", commands, result.returncode, result.stdout, result.stderr, duration_ms)
                    return result.returncode == 0, result.stdout or result.stderr
                except subprocess.TimeoutExpired:
                    return False, f"Command timed out after {timeout}s"

        # Remote: use SSH with remote tmux session for persistence
        if remote_session:
            if step.background:
                # Background: just send the command, use wait idle to check completion
                tmux_cmd = f"tmux send-keys -t {remote_session} {shlex.quote(commands)} Enter"
                ssh_args = _build_ssh_args(host, command=tmux_cmd, tty=False)

                try:
                    result = subprocess.run(
                        ssh_args,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if self.logger:
                        self.logger.log_detail("send_keys", f"Sent to {window_name}", {
                            "commands": commands,
                            "remote_session": remote_session,
                            "background": True,
                            "success": result.returncode == 0,
                        })
                    return result.returncode == 0, "Command sent (background)"
                except subprocess.TimeoutExpired:
                    return False, "SSH timeout sending command"
            else:
                # Foreground: use tmux wait-for for synchronization (or idle check on resume)
                if self.is_resuming:
                    # On resume, use idle check since we may have missed the wait-for signal
                    tmux_cmd = f"tmux send-keys -t {remote_session} {shlex.quote(commands)} Enter"
                    ssh_args = _build_ssh_args(host, command=tmux_cmd, tty=False)
                    try:
                        subprocess.run(ssh_args, capture_output=True, text=True, timeout=30)
                        # Wait a moment for command to start
                        time.sleep(0.5)
                        # Poll until pane is idle with double-check
                        window_info = WindowInfo(name=window_name, host=host, remote_session=remote_session)
                        ok, msg = self._wait_for_idle(window_info, timeout)
                        elapsed = int(time.time() - start_time)
                        if self.logger:
                            self.logger.log_detail("execute_complete", f"Command completed on {window_name}", {
                                "elapsed_sec": elapsed,
                                "remote_session": remote_session,
                            })
                        return ok, msg
                    except subprocess.TimeoutExpired:
                        return False, f"Command timed out after {timeout}s"
                else:
                    # Fresh run: use tmux wait-for
                    import uuid
                    signal = f"train_{uuid.uuid4().hex[:8]}"
                    # Wrap command: run command, then signal completion
                    wrapped_cmd = f"( {commands} ); tmux wait-for -S {signal}"
                    tmux_send_cmd = f"tmux send-keys -t {remote_session} {shlex.quote(wrapped_cmd)} Enter"
                    ssh_args = _build_ssh_args(host, command=tmux_send_cmd, tty=False)

                    try:
                        subprocess.run(ssh_args, capture_output=True, text=True, timeout=30)
                    except subprocess.TimeoutExpired:
                        return False, "SSH timeout sending command"

                    # Wait for the signal via SSH
                    wait_cmd = f"tmux wait-for {signal}"
                    ssh_wait_args = _build_ssh_args(host, command=wait_cmd, tty=False)
                    try:
                        wait_result = subprocess.run(
                            ssh_wait_args,
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                        )
                        elapsed = int(time.time() - start_time)
                        if self.logger:
                            self.logger.log_detail("execute_complete", f"Command completed on {window_name}", {
                                "elapsed_sec": elapsed,
                                "remote_session": remote_session,
                            })
                        if wait_result.returncode == 0:
                            return True, f"Command completed ({elapsed}s)"
                        return False, f"Command failed or wait-for timed out"
                    except subprocess.TimeoutExpired:
                        return False, f"Command timed out after {timeout}s"
        else:
            # No remote session: direct SSH execution (shouldn't happen for remote hosts)
            ssh_args = _build_ssh_args(host, command=commands, tty=False)
            try:
                result = subprocess.run(
                    ssh_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                if self.logger:
                    self.logger.log_ssh(host, commands, result.returncode, result.stdout, result.stderr, duration_ms)
                return result.returncode == 0, result.stdout or result.stderr
            except subprocess.TimeoutExpired:
                return False, f"Command timed out after {timeout}s"

    def _ensure_sudo_auth(self, window: WindowInfo, commands: str) -> tuple[bool, str]:
        """Ensure sudo auth is valid before running a sudo command."""
        if not re.search(r"\bsudo\b", commands):
            return True, ""

        if window.remote_session:
            return self._ensure_sudo_auth_tmux(window)

        # Non-tmux execution: best-effort pre-auth in the current terminal
        host = window.host
        host_label = "local" if host == "local" else host

        now = time.time()
        last_prompt = self._sudo_last_prompt.get(host_label, 0)
        prompt_log = now - last_prompt > 30

        if host == "local":
            check = subprocess.run(
                ["sudo", "-n", "-v"],
                capture_output=True,
                text=True,
            )
            if check.returncode == 0:
                return True, ""

            if prompt_log:
                self.log("Sudo auth required for local commands. Please enter your password.")
                self._sudo_last_prompt[host_label] = now

            try:
                auth = subprocess.run(["sudo", "-v"])
            except KeyboardInterrupt:
                return False, "Sudo authentication cancelled"

            if auth.returncode != 0:
                return False, "Sudo authentication failed"

            return True, ""

        # Remote without tmux: run sudo -v in an interactive SSH session
        if prompt_log:
            self.log(f"Sudo auth required on {host_label}. Please enter your password.")
            self._sudo_last_prompt[host_label] = now

        auth_args = _build_ssh_args(host, command="sudo -v", tty=True)
        try:
            auth = subprocess.run(auth_args)
        except KeyboardInterrupt:
            return False, f"Sudo authentication cancelled for {host_label}"

        if auth.returncode != 0:
            return False, f"Sudo authentication failed for {host_label}"

        return True, ""

    def _ensure_sudo_auth_tmux(self, window: WindowInfo) -> tuple[bool, str]:
        """Ensure sudo auth inside the tmux session (so it applies to that TTY).

        Uses sudo -S to read password from stdin, avoiding output parsing.
        Validates success via exit code marker, not output text matching.
        """
        import uuid

        host = window.host
        session = window.remote_session
        host_label = "local" if host == "local" else host

        max_attempts = 3

        for attempt in range(max_attempts):
            # Prompt for password locally first
            try:
                if attempt == 0:
                    prompt_msg = f"Sudo password for {host_label}: "
                else:
                    prompt_msg = f"Sudo password for {host_label} (attempt {attempt + 1}/{max_attempts}): "
                password = getpass.getpass(prompt_msg)
            except (EOFError, KeyboardInterrupt):
                return False, f"Sudo authentication cancelled for {host_label}"
            if not password:
                return False, f"Sudo authentication cancelled for {host_label}"

            # Use unique marker to detect success/failure via exit code
            marker = f"__sudo_ok_{uuid.uuid4().hex[:8]}__"

            # Command: echo password | sudo -S -v, then echo marker if successful
            # The -S flag makes sudo read password from stdin
            # We use printf to avoid newline issues and escape special chars
            escaped_pw = password.replace("\\", "\\\\").replace("'", "'\"'\"'")
            sudo_cmd = f"printf '%s\\n' '{escaped_pw}' | sudo -S -v 2>/dev/null && echo {marker}"

            self._tmux_send_keys(host, session, sudo_cmd)

            # Wait and check for success marker in output
            time.sleep(1.5)
            output = self._get_pane_recent_output(host, session, lines=5)

            if marker in output:
                self._sudo_last_prompt[host_label] = time.time()
                return True, ""

            # Failed, will retry if attempts remain

        return False, f"Sudo authentication failed after {max_attempts} attempts for {host_label}"

    def _tmux_send_keys(self, host: str, session: str, text: str) -> None:
        """Send literal text + Enter to a tmux session locally or via SSH."""
        tmux_cmd = f"tmux send-keys -t {session} {shlex.quote(text)} Enter"
        if host == "local":
            subprocess.run(tmux_cmd, shell=True, capture_output=True, text=True, timeout=10)
        else:
            ssh_args = _build_ssh_args(host, command=tmux_cmd, tty=False)
            subprocess.run(ssh_args, capture_output=True, text=True, timeout=20)

    def _tmux_wait_for_signal(self, host: str, signal: str, timeout: int = 1) -> bool:
        """Wait briefly for a tmux signal; returns True if received."""
        wait_cmd = f"tmux wait-for {signal}"
        try:
            if host == "local":
                result = subprocess.run(
                    wait_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            else:
                ssh_args = _build_ssh_args(host, command=wait_cmd, tty=False)
                result = subprocess.run(
                    ssh_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def _exec_transfer(self, step: DSLStep) -> tuple[bool, str]:
        """Execute file transfer: source -> dest"""
        from ..services.transfer_engine import TransferEngine
        from ..core.models import TransferEndpoint

        source = self._interpolate(step.source)
        dest = self._interpolate(step.dest)

        transfer_info = {
            "source": source,
            "dest": dest,
        }
        if self.logger:
            self.logger.log_detail("transfer", f"Transferring {source} -> {dest}", transfer_info)

        # Parse endpoints
        src_endpoint = self._parse_endpoint(source)
        dst_endpoint = self._parse_endpoint(dest)

        start_time = time.time()
        engine = TransferEngine()
        hosts = self._build_transfer_hosts()
        storages = self._build_transfer_storages()
        result = engine.transfer(
            source=src_endpoint,
            destination=dst_endpoint,
            hosts=hosts,
            storages=storages,
        )
        duration_ms = int((time.time() - start_time) * 1000)

        if self.logger:
            self.logger.log_transfer(
                source, dest, "rsync",
                result.bytes_transferred,
                duration_ms,
                result.success,
                result.message
            )

        if result.success:
            return True, f"Transferred {result.bytes_transferred} bytes"
        return False, result.message

    def _run_tmux_cmd(self, host: str, cmd: str, timeout: int = 10) -> subprocess.CompletedProcess:
        """Run a tmux command locally or via SSH."""
        if host == "local":
            return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            ssh_args = _build_ssh_args(host, command=cmd, tty=False)
            return subprocess.run(ssh_args, capture_output=True, text=True, timeout=timeout)

    def _get_pane_recent_output(self, host: str, session: str, lines: int = 5) -> str:
        """Get recent output from a tmux pane."""
        capture_cmd = f"tmux capture-pane -t {session} -p -S -{lines * 10}"
        result = self._run_tmux_cmd(host, capture_cmd)
        if result.returncode == 0:
            # Filter out empty lines and get last N non-empty lines
            output_lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
            return '\n'.join(output_lines[-lines:]) if output_lines else ""
        return ""

    def _is_pane_idle(self, host: str, session: str) -> bool:
        """Check if a tmux pane is idle using pane_current_command and child process count."""
        # Check 1: pane_current_command should be a shell
        cmd = f"tmux display-message -t {session} -p '#{{pane_current_command}}'"
        result = self._run_tmux_cmd(host, cmd)
        if result.returncode != 0:
            return False
        current_cmd = result.stdout.strip()
        if current_cmd not in {"bash", "zsh", "sh", "fish", "tcsh", "csh", "dash", "ksh"}:
            return False  # A command is running

        # Check 2: shell should have no child processes
        pane_pid_cmd = f"tmux list-panes -t {session} -F '#{{pane_pid}}'"
        result = self._run_tmux_cmd(host, pane_pid_cmd)
        if result.returncode != 0:
            return False
        pane_pid = result.stdout.strip().split('\n')[0]
        if not pane_pid:
            return False

        child_cmd = f"ps --ppid {pane_pid} --no-headers 2>/dev/null | wc -l"
        result = self._run_tmux_cmd(host, child_cmd)
        if result.returncode != 0:
            return False
        try:
            child_count = int(result.stdout.strip())
            return child_count == 0
        except ValueError:
            return False

    def _get_pane_process_info(self, host: str, session: str) -> tuple[str, str]:
        """Get current command and process tree for a tmux pane.

        Returns:
            Tuple of (current_command, process_tree_info)
        """
        # Get pane_current_command
        cmd = f"tmux display-message -t {session} -p '#{{pane_current_command}}'"
        result = self._run_tmux_cmd(host, cmd)
        current_cmd = result.stdout.strip() if result.returncode == 0 else "unknown"

        # Get pane PID and its process tree
        pane_pid_cmd = f"tmux list-panes -t {session} -F '#{{pane_pid}}'"
        result = self._run_tmux_cmd(host, pane_pid_cmd)
        if result.returncode != 0:
            return current_cmd, ""

        pane_pid = result.stdout.strip().split('\n')[0]
        if not pane_pid:
            return current_cmd, ""

        # Get process tree: show child processes with their commands
        # Use ps to get process tree rooted at pane_pid
        ps_cmd = f"ps --forest -o pid,stat,time,cmd --ppid {pane_pid} 2>/dev/null | head -10"
        result = self._run_tmux_cmd(host, ps_cmd)
        if result.returncode == 0 and result.stdout.strip():
            return current_cmd, result.stdout.strip()

        return current_cmd, ""

    def _wait_for_idle(self, window: 'WindowInfo', timeout: int) -> tuple[bool, str]:
        """Wait for a tmux pane to become idle using ps polling with double-check.

        Uses a double-check mechanism: when idle is detected, wait a longer interval
        and check multiple times. Only return True if all checks show idle. This prevents
        false positives when a background command just started.
        """
        host = window.host
        session = window.remote_session
        start = time.time()
        poll_interval = 30
        confirm_interval = 10  # Seconds between idle checks for confirmation
        confirm_count = 3  # Number of consecutive idle checks required

        if timeout > 3600:
            self.log(f"  Long wait ({_format_duration(timeout)})")
            self.log(f"  If you disconnect, run 'recipe resume' to continue later")

        # Wait for command to start before checking idle
        # This handles the case where we just sent a background command
        # Training scripts may take time to initialize (loading models, etc.)
        time.sleep(30)

        consecutive_idle = 0

        # Poll until pane is truly idle (no child processes, confirmed multiple times)
        while time.time() - start < timeout:
            remaining = int(timeout - (time.time() - start))

            try:
                if self._is_pane_idle(host, session):
                    consecutive_idle += 1
                    if consecutive_idle >= confirm_count:
                        return True, "Pane is idle (confirmed)"
                    # Wait and check again to confirm
                    self.log(f"  Idle detected, confirming... ({consecutive_idle}/{confirm_count})")
                    time.sleep(confirm_interval)
                    continue
                else:
                    # Reset counter if not idle
                    if consecutive_idle > 0:
                        self.log(f"  Not idle, resetting confirmation counter")
                    consecutive_idle = 0
            except Exception as e:
                self.log(f"  Idle check failed: {e}")
                consecutive_idle = 0

            # Show status with process info
            current_cmd, process_tree = self._get_pane_process_info(host, session)
            self.log(f"  Waiting for @{window.name}... ({_format_duration(remaining)} remaining)")
            self.log(f"    Current command: {current_cmd}")
            if process_tree:
                self.log(f"    Running processes:")
                for line in process_tree.split('\n')[:5]:  # Limit to 5 lines
                    self.log(f"      {line[:100]}")
            try:
                output = self._get_pane_recent_output(host, session, lines=2)
                if output:
                    self.log(f"    Recent output:")
                    for line in output.split('\n'):
                        self.log(f"      {line[:80]}")
            except Exception:
                pass

            time.sleep(poll_interval)

        return False, f"Timeout after {_format_duration(timeout)}"

    def _exec_wait(self, step: DSLStep) -> tuple[bool, str]:
        """Execute wait condition with SSH retry logic."""
        target = step.target
        pattern = step.pattern
        condition = step.condition
        timeout = step.timeout or 300

        wait_config = {
            "target": target,
            "pattern": pattern,
            "condition": condition,
            "timeout": timeout,
        }
        if self.logger:
            self.logger.log_detail("wait_start", f"Starting wait for {target}", wait_config)

        window = self._resolve_window(target)
        if not window:
            return False, f"Unknown window: {target}"

        start = time.time()
        poll_interval = 30  # Check every 30 seconds
        ssh_failures = 0
        poll_count = 0

        # For long waits, log a reminder
        if timeout > 3600:
            self.log(f"  Long wait ({_format_duration(timeout)})")
            self.log(f"  If you disconnect, run 'recipe resume' to continue later")

        while time.time() - start < timeout:
            poll_count += 1
            elapsed = int(time.time() - start)
            remaining = timeout - elapsed

            # Log each poll
            if self.logger:
                self.logger.log_wait(target or "", condition or pattern or "", elapsed, remaining, f"poll #{poll_count}")

            # Check file condition
            if condition and condition.startswith("file:"):
                filepath = condition[5:]
                filepath = self._interpolate(filepath)

                # Resolve host from target
                if window.host != "local":
                    # Remote file check with retry logic
                    try:
                        check_cmd = f"test -f {filepath} && echo exists"
                        ssh_args = _build_ssh_args(
                            window.host,
                            command=check_cmd,
                            tty=False,
                        )
                        ssh_start = time.time()
                        result = subprocess.run(
                            ssh_args,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        ssh_duration = int((time.time() - ssh_start) * 1000)

                        if self.logger:
                            self.logger.log_ssh(window.host, check_cmd, result.returncode, result.stdout, result.stderr, ssh_duration)

                        if "exists" in result.stdout:
                            if self.logger:
                                self.logger.log_detail("wait_file_found", f"File found: {filepath}", {"elapsed_sec": elapsed})
                            return True, f"File found: {filepath}"

                        # SSH succeeded, reset failure counter
                        ssh_failures = 0

                    except (subprocess.TimeoutExpired, OSError) as e:
                        ssh_failures += 1
                        self.log(f"  SSH check failed ({ssh_failures}/{self.ssh_max_retries}): {e}")

                        if self.logger:
                            self.logger.log_detail("wait_ssh_failure", f"SSH check failed", {
                                "failure_count": ssh_failures,
                                "max_retries": self.ssh_max_retries,
                                "error": str(e),
                            })

                        if ssh_failures >= self.ssh_max_retries:
                            return False, f"Too many SSH failures: {e}"

                        # Exponential backoff
                        backoff = min(
                            self.ssh_retry_base_interval * (2 ** (ssh_failures - 1)),
                            self.ssh_retry_max_interval
                        )
                        self.log(f"  Retrying in {backoff}s...")
                        time.sleep(backoff)
                        continue
                else:
                    # Local file check
                    if os.path.exists(os.path.expanduser(filepath)):
                        if self.logger:
                            self.logger.log_detail("wait_file_found", f"Local file found: {filepath}", {"elapsed_sec": elapsed})
                        return True, f"File found: {filepath}"

            # Check port condition
            if condition and condition.startswith("port:"):
                port = int(condition[5:])
                host = "localhost"
                if window.host != "local":
                    host = _host_from_ssh_spec(window.host).hostname
                try:
                    result = subprocess.run(
                        ["nc", "-z", host, str(port)],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        if self.logger:
                            self.logger.log_detail("wait_port_open", f"Port {port} is open on {host}", {"elapsed_sec": elapsed})
                        return True, f"Port {port} is open"
                except (subprocess.TimeoutExpired, OSError):
                    pass

            # Check idle condition - use dedicated method
            if condition == "idle":
                if not window.remote_session:
                    return False, f"Window {target} has no tmux session"
                return self._wait_for_idle(window, remaining)

            # Print status for non-idle waits
            remaining_str = _format_duration(remaining)
            timeout_str = _format_duration(timeout)
            self.log(f"  Waiting... ({remaining_str} remaining of {timeout_str})")

            time.sleep(poll_interval)

        return False, f"Timeout after {_format_duration(timeout)}"

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

    def _resolve_window(self, name: str) -> Optional[WindowInfo]:
        """Resolve a window name to an existing tmux session or host fallback."""
        window = self.ctx.windows.get(name)
        if window:
            return window
        if not self.allow_host_execute:
            return None
        host = self._resolve_host(f"@{name}")
        return WindowInfo(name=name, host=host, remote_session=None)

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
        """Parse transfer endpoint: @host:/path, @storage:/path, or /local/path"""
        from ..core.models import TransferEndpoint
        from ..commands.host import load_hosts

        if spec.startswith('@'):
            # Remote: @name:/path - could be host or storage
            if ':' in spec:
                name_part, path = spec.split(':', 1)
                name = name_part[1:]

                # Check if it's a storage reference
                if name in self.recipe.storages:
                    storage_spec = self.recipe.storages[name]
                    return TransferEndpoint(type="storage", path=path, storage_id=name)

                # Check recipe hosts first, then global hosts
                if name in self.recipe.hosts:
                    host = self.recipe.hosts[name]
                    return TransferEndpoint(type="host", path=path, host_id=host)

                # Check global hosts
                global_hosts = load_hosts()
                if name in global_hosts:
                    # Use the name directly - _build_transfer_hosts will include it
                    return TransferEndpoint(type="host", path=path, host_id=name)

                # Unknown host - use name and let caller handle error
                return TransferEndpoint(type="host", path=path, host_id=name)
            else:
                # Just @name without path - use as host with root path
                return TransferEndpoint(type="host", path="/", host_id=spec[1:])
        else:
            # Local path
            return TransferEndpoint(type="local", path=os.path.expanduser(spec))

    def _build_transfer_hosts(self) -> Dict[str, Host]:
        """Build host mapping for transfers from recipe host specs and global config."""
        from ..commands.host import load_hosts

        # Start with global hosts
        global_hosts = load_hosts()
        hosts: Dict[str, Host] = dict(global_hosts)

        # Add/override with recipe-defined hosts
        for name, spec in self.recipe.hosts.items():
            if spec == "local":
                continue
            resolved_spec = spec
            if spec.startswith("vast:"):
                resolved_spec = _resolve_vast_host(spec[5:])
            hosts[name] = _host_from_ssh_spec(resolved_spec)
            # Also store by spec for lookup
            hosts[spec] = hosts[name]
        return hosts

    def _build_transfer_storages(self) -> Dict[str, 'Storage']:
        """Build storage mapping for transfers from recipe storage specs."""
        from ..commands.storage import load_storages
        from ..core.models import Storage, StorageType

        # Load global storages from config
        global_storages = load_storages()

        # Build mapping for recipe storages
        storages: Dict[str, 'Storage'] = {}
        for name, spec in self.recipe.storages.items():
            # Check if it's a reference to a global storage
            if spec in global_storages:
                storages[name] = global_storages[spec]
            elif spec != "placeholder":
                # Parse inline storage spec like "r2:bucket-name"
                if ":" in spec:
                    provider, bucket = spec.split(":", 1)
                    storage_type = StorageType.R2
                    if provider == "b2":
                        storage_type = StorageType.B2
                    elif provider == "s3":
                        storage_type = StorageType.S3
                    elif provider == "gdrive":
                        storage_type = StorageType.GDRIVE

                    storages[name] = Storage(
                        id=name,
                        name=name,
                        type=storage_type,
                        bucket=bucket,
                    )
        return storages

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
    log_callback: Optional[Callable[[str], None]] = None,
    host_overrides: Optional[Dict[str, str]] = None,
    var_overrides: Optional[Dict[str, str]] = None,
    resume: bool = False,
) -> bool:
    """
    Load and execute a DSL recipe file.

    Args:
        path: Path to .recipe file
        log_callback: Optional log callback
        host_overrides: Override hosts (e.g., {"gpu": "vast:12345"})
        var_overrides: Override variables (e.g., {"MODEL": "mistral"})
        resume: If True, try to resume from saved checkpoint

    Returns:
        True if successful
    """
    path = os.path.abspath(os.path.expanduser(path))
    recipe = parse_recipe(path)

    # Check for resumable state
    resume_from = 0
    job_id = None
    state_manager = JobStateManager()

    if resume:
        saved_state = state_manager.find_resumable(path)
        if saved_state:
            job_id = saved_state.job_id
            resume_from = saved_state.current_step
            # Restore variables from saved state
            recipe.variables.update(saved_state.variables)
            # Restore host mappings
            for name, host_spec in saved_state.hosts.items():
                recipe.hosts[name] = host_spec
            if log_callback:
                log_callback(f"Found saved state: job {job_id}, step {resume_from + 1}/{saved_state.total_steps}")
        else:
            if log_callback:
                log_callback("No resumable state found, starting fresh")

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

    executor = DSLExecutor(
        recipe,
        log_callback=log_callback,
        job_id=job_id,
        recipe_path=path,
        is_resuming=resume and resume_from > 0,
    )

    # Restore windows info if resuming
    if resume and job_id:
        saved_state = state_manager.load(job_id)
        if saved_state:
            # Restore windows from saved hosts
            for name, host_spec in saved_state.hosts.items():
                # Reconstruct remote_session name from job_id and window name
                remote_session = f"train_{job_id[:8]}_{name}"
                executor.ctx.windows[name] = WindowInfo(
                    name=name,
                    host=host_spec,
                    remote_session=remote_session,
                )

            # If no windows were restored but we're past tmux.open steps,
            # try to find existing tmux sessions for this job
            if not executor.ctx.windows and resume_from > 0:
                # Check if any tmux sessions exist for this job
                import subprocess
                try:
                    result = subprocess.run(
                        f"tmux list-sessions -F '#{{session_name}}' 2>/dev/null | grep 'train_{job_id[:8]}_'",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        for session_name in result.stdout.strip().split('\n'):
                            if session_name:
                                # Extract window name from session name
                                window_name = session_name.replace(f"train_{job_id[:8]}_", "")
                                # Determine host from recipe or default to local
                                host_spec = "local"
                                for host_name, spec in recipe.hosts.items():
                                    if spec == "local":
                                        host_spec = "local"
                                        break
                                executor.ctx.windows[window_name] = WindowInfo(
                                    name=window_name,
                                    host=host_spec,
                                    remote_session=session_name,
                                )
                                if log_callback:
                                    log_callback(f"Restored window '{window_name}' from existing tmux session")
                except Exception:
                    pass

    return executor.execute(resume_from=resume_from)


def _test_ssh_connection(host: str, port: int, timeout: int = 5) -> bool:
    """Test if SSH connection works."""
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=no",
                "-p", str(port),
                f"root@{host}",
                "echo ok"
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def _resolve_vast_host(instance_id: str) -> str:
    """Resolve vast.ai instance ID to SSH host spec.

    Tests direct SSH first (usually faster), falls back to proxy SSH
    if direct connection fails.
    """
    from ..services.vast_api import get_vast_client

    try:
        client = get_vast_client()
        instance = client.get_instance(int(instance_id))

        # Try direct SSH first if available
        if instance.public_ipaddr and instance.direct_port_start:
            if _test_ssh_connection(instance.public_ipaddr, instance.direct_port_start):
                return f"root@{instance.public_ipaddr} -p {instance.direct_port_start}"

        # Fall back to proxy SSH
        if instance.ssh_host and instance.ssh_port:
            if _test_ssh_connection(instance.ssh_host, instance.ssh_port):
                return f"root@{instance.ssh_host} -p {instance.ssh_port}"

        # If both failed, still return proxy (let caller handle the error)
        if instance.ssh_host and instance.ssh_port:
            return f"root@{instance.ssh_host} -p {instance.ssh_port}"

        return f"vast-{instance_id}"

    except Exception:
        return f"vast-{instance_id}"
