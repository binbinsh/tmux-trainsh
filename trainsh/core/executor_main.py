# tmux-trainsh DSL executor
# Executes parsed DSL recipes using remote tmux sessions for persistence

import subprocess
import time
import re
import os
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass, field
from datetime import datetime

from ..config import load_config
from .dsl_parser import DSLRecipe, DSLStep, StepType, parse_recipe
from .bridge_exec import BridgeExecutionHelper
from .executor_execute import ExecuteHelper
from .executor_tmux import TmuxControlHelper
from .executor_transfer import TransferHelper
from .executor_vast import VastControlHelper
from .executor_wait import WaitHelper
from .execution_log import ExecutionLogger
from .local_tmux import LocalTmuxClient
from .remote_tmux import RemoteTmuxClient
from .secrets import get_secrets_manager
from .models import Host
from .tmux_bridge import TmuxBridgeManager
from .job_state import (
    JobState,
    JobStateManager,
    generate_job_id,
)
from .tmux_naming import (
    parse_window_session_index,
    get_window_session_name,
)
from .executor_utils import (
    _build_ssh_args,
    _format_duration,
    _host_from_ssh_spec,
    _resolve_vast_host,
)
from ..utils.notifier import Notifier, normalize_channels, parse_bool


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
    next_window_index: int = 0  # Monotonic tmux.open index for session naming
    start_time: Optional[datetime] = None
    log_callback: Optional[Callable[[str], None]] = None


class DSLExecutor:
    """
    Executes DSL recipes step by step.

    Integrates with:
    - Remote tmux sessions for persistent command execution
    - TransferEngine for file transfers
    - VastAPI for GPU instance management

    Architecture:
    - Commands run in remote tmux sessions (survive SSH disconnect)
    - Local tmux bridge can auto-split and attach local/remote sessions
    - Resume can rebuild bridge splits from saved job state
    """

    def __init__(
        self,
        recipe: DSLRecipe,
        log_callback: Optional[Callable[[str], None]] = None,
        job_id: Optional[str] = None,
        recipe_path: Optional[str] = None,
        is_resuming: bool = False,
        allow_host_execute: bool = False,
        bridge_session: Optional[str] = None,
    ):
        """
        Initialize executor.

        Args:
            recipe: Parsed DSL recipe
            log_callback: Optional callback for log messages
            job_id: Optional job ID for resume (if None, generates new one)
            recipe_path: Optional path to recipe file (for state persistence)
            is_resuming: Whether this is a resume execution (affects sync strategy)
            bridge_session: Optional detached bridge session name to reuse on resume
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

        # Local tmux bridge for auto split/attach
        config = load_config()
        tmux_cfg = config.get("tmux", {})
        self.tmux_bridge = TmuxBridgeManager(
            job_id=self.ctx.job_id,
            recipe_name=self.recipe.name,
            enabled=bool(tmux_cfg.get("auto_bridge", True)),
            allow_outside_tmux=bool(tmux_cfg.get("bridge_outside_tmux", True)),
            session_name=bridge_session or None,
            allocate_session_name=self.allocate_window_session_name,
            log_callback=self.log_callback,
        )
        self.prefer_bridge_exec = bool(tmux_cfg.get("prefer_bridge_exec", True))
        bridge_remote_status = str(tmux_cfg.get("bridge_remote_status", "off")).lower()
        if bridge_remote_status not in {"keep", "off", "bottom"}:
            bridge_remote_status = "off"
        self.bridge_remote_status = bridge_remote_status
        self.bridge_exec = BridgeExecutionHelper(
            tmux_bridge=self.tmux_bridge,
            prefer_bridge_exec=self.prefer_bridge_exec,
            bridge_remote_status=self.bridge_remote_status,
            get_tmux_client=self.get_tmux_client,
            log=self.log,
            log_detail=self._log_detail,
            format_duration=_format_duration,
        )
        self.tmux_control = TmuxControlHelper(self, WindowInfo)
        self.transfer_helper = TransferHelper(self, _resolve_vast_host, _host_from_ssh_spec)
        self.wait_helper = WaitHelper(self, _build_ssh_args, _host_from_ssh_spec, _format_duration)
        self.local_tmux = LocalTmuxClient()
        self._remote_tmux_clients: Dict[str, RemoteTmuxClient] = {}
        self.execute_helper = ExecuteHelper(self, _build_ssh_args, WindowInfo)
        self.vast_control = VastControlHelper(self, _build_ssh_args, _format_duration)

        # Notifications
        notify_cfg = config.get("notifications", {})
        try:
            self.notify_enabled = parse_bool(notify_cfg.get("enabled", True))
        except ValueError:
            self.notify_enabled = True
        self.notify_app_name = str(notify_cfg.get("app_name", "train"))
        self.notify_default_webhook = str(notify_cfg.get("webhook_url", "")).strip() or None
        self.notify_default_command = str(notify_cfg.get("command", "")).strip() or None

        try:
            self.notify_default_channels = normalize_channels(
                notify_cfg.get("channels"),
                ["log", "system"],
            )
        except ValueError:
            self.notify_default_channels = ["log", "system"]

        try:
            self.notify_default_timeout = int(notify_cfg.get("timeout_secs", 5))
        except Exception:
            self.notify_default_timeout = 5
        if self.notify_default_timeout <= 0:
            self.notify_default_timeout = 5

        try:
            self.notify_default_fail_on_error = parse_bool(notify_cfg.get("fail_on_error", False))
        except ValueError:
            self.notify_default_fail_on_error = False

        self.notifier = Notifier(log_callback=self.log, app_name=self.notify_app_name)

    def get_tmux_client(self, host: str):
        """Get tmux client for local/remote host with caching."""
        if host == "local":
            return self.local_tmux

        client = self._remote_tmux_clients.get(host)
        if client is None:
            client = RemoteTmuxClient(host, _build_ssh_args)
            self._remote_tmux_clients[host] = client
        return client

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
        window_sessions = {}
        for name, window in self.ctx.windows.items():
            if window.host:
                hosts[name] = window.host
            if window.remote_session:
                window_sessions[name] = window.remote_session

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
            window_sessions=window_sessions,
            next_window_index=self.ctx.next_window_index,
            bridge_session=self.tmux_bridge.get_state_session(),
            vast_instance_id=vast_instance_id,
            vast_start_time=vast_start_time,
        )
        self.job_state.tmux_session = self.job_state.bridge_session or next(
            (w.remote_session for w in self.ctx.windows.values() if w.remote_session),
            "",
        )
        self.state_manager.save(self.job_state)

    def allocate_window_session_name(self) -> str:
        """Allocate next tmux session name for tmux.open in this job."""
        index = self.ctx.next_window_index
        self.ctx.next_window_index += 1
        return get_window_session_name(self.recipe.name, self.ctx.job_id, index)

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

    def _log_detail(self, event: str, message: str, data: Dict[str, object]) -> None:
        """Safe logger detail helper for composed helpers."""
        if self.logger:
            self.logger.log_detail(event, message, data)

    def _build_bridge_attach_command(self, window: WindowInfo) -> str:
        """Build attach command for a bridge pane."""
        return self.bridge_exec.build_bridge_attach_command(window)

    def _ensure_bridge_window(self, window: WindowInfo) -> None:
        """Ensure bridge pane exists for window."""
        self.bridge_exec.ensure_bridge_window(window)

    def restore_tmux_bridge(self) -> None:
        """Rebuild bridge panes for restored windows on resume."""
        self.bridge_exec.restore_tmux_bridge(self.ctx.windows.values())

    def _wait_for_bridge_idle(self, window_name: str, pane_id: str, timeout: int) -> tuple[bool, str]:
        """Delegate bridge idle wait to helper."""
        return self.bridge_exec.wait_for_bridge_idle(window_name, pane_id, timeout)

    def _exec_via_bridge(
        self,
        window: WindowInfo,
        commands: str,
        timeout: int,
        background: bool,
        start_time: float,
    ) -> Optional[tuple[bool, str]]:
        """Delegate bridge command execution to helper."""
        return self.bridge_exec.exec_via_bridge(window, commands, timeout, background, start_time)

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
        """Handle tmux.open via helper."""
        return self.tmux_control.cmd_tmux_open(args)

    def _cmd_tmux_close(self, args: List[str]) -> tuple[bool, str]:
        """Handle tmux.close via helper."""
        return self.tmux_control.cmd_tmux_close(args)

    def _cmd_tmux_config(self, args: List[str]) -> tuple[bool, str]:
        """Handle tmux.config via helper."""
        return self.tmux_control.cmd_tmux_config(args)

    def _cmd_notify(self, args: List[str]) -> tuple[bool, str]:
        """
        Handle notifications with simple syntax:
            notify "message"
            notify training complete
        """
        if not self.notify_enabled:
            return True, "Notification skipped (notifications.enabled=false)"

        message = self._interpolate(" ".join(args)).strip()
        if not message:
            return False, 'Usage: notify "message"'

        ok, summary = self.notifier.notify(
            title=self.notify_app_name,
            message=message,
            level="info",
            channels=self.notify_default_channels,
            webhook_url=self.notify_default_webhook,
            command=self.notify_default_command,
            timeout_secs=self.notify_default_timeout,
            fail_on_error=self.notify_default_fail_on_error,
        )
        return ok, summary

    def _cmd_vast_start(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.start via helper."""
        return self.vast_control.cmd_vast_start(args)

    def _cmd_vast_stop(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.stop via helper."""
        return self.vast_control.cmd_vast_stop(args)

    def _cmd_vast_pick(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.pick via helper."""
        return self.vast_control.cmd_vast_pick(args)

    def _cmd_vast_wait(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.wait via helper."""
        return self.vast_control.cmd_vast_wait(args)

    def _verify_ssh_connection(self, ssh_spec: str, timeout: int = 10) -> bool:
        """Verify SSH connectivity via helper."""
        return self.vast_control.verify_ssh_connection(ssh_spec, timeout=timeout)

    def _ensure_ssh_key_attached(self, client, ssh_key_path: str) -> None:
        """Ensure SSH key is attached via helper."""
        self.vast_control.ensure_ssh_key_attached(client, ssh_key_path)

    def _cmd_vast_cost(self, args: List[str]) -> tuple[bool, str]:
        """Handle vast.cost via helper."""
        return self.vast_control.cmd_vast_cost(args)

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
        """Execute command via helper."""
        return self.execute_helper.exec_execute(step)

    def _tmux_send_keys(self, host: str, session: str, text: str) -> None:
        """Send tmux keys via helper."""
        self.execute_helper.tmux_send_keys(host, session, text)

    def _tmux_wait_for_signal(self, host: str, signal: str, timeout: int = 1) -> bool:
        """Wait for tmux signal via helper."""
        return self.execute_helper.tmux_wait_for_signal(host, signal, timeout=timeout)

    def _exec_transfer(self, step: DSLStep) -> tuple[bool, str]:
        """Execute transfer via helper."""
        return self.transfer_helper.exec_transfer(step)

    def _run_tmux_cmd(self, host: str, cmd: str, timeout: int = 10) -> subprocess.CompletedProcess:
        """Run tmux command via helper."""
        return self.wait_helper.run_tmux_cmd(host, cmd, timeout=timeout)

    def _get_pane_recent_output(self, host: str, session: str, lines: int = 5) -> str:
        """Get pane output via helper."""
        return self.wait_helper.get_pane_recent_output(host, session, lines=lines)

    def _is_pane_idle(self, host: str, session: str) -> bool:
        """Check pane idle via helper."""
        return self.wait_helper.is_pane_idle(host, session)

    def _get_pane_process_info(self, host: str, session: str) -> tuple[str, str]:
        """Get pane process info via helper."""
        return self.wait_helper.get_pane_process_info(host, session)

    def _wait_for_idle(self, window: 'WindowInfo', timeout: int) -> tuple[bool, str]:
        """Wait for idle via helper."""
        return self.wait_helper.wait_for_idle(window, timeout)

    def _exec_wait(self, step: DSLStep) -> tuple[bool, str]:
        """Execute wait via helper."""
        return self.wait_helper.exec_wait(step)

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
        # First handle ${VAR} and ${secret:NAME}
        def replace_braced(match):
            ref = match.group(1)
            if ref.startswith('secret:'):
                secret_name = ref[7:]
                return self.secrets.get(secret_name) or ""
            return self.ctx.variables.get(ref, match.group(0))

        text = re.sub(r'\$\{([^}]+)\}', replace_braced, text)

        # Then handle $VAR shorthand in control command arguments
        def replace_simple(match):
            name = match.group(1)
            return self.ctx.variables.get(name, match.group(0))

        return re.sub(r'\$(\w+)', replace_simple, text)

    def _parse_endpoint(self, spec: str) -> 'TransferEndpoint':
        """Parse transfer endpoint via helper."""
        return self.transfer_helper.parse_endpoint(spec)

    def _build_transfer_hosts(self) -> Dict[str, Host]:
        """Build transfer hosts via helper."""
        return self.transfer_helper.build_transfer_hosts()

    def _build_transfer_storages(self) -> Dict[str, 'Storage']:
        """Build transfer storages via helper."""
        return self.transfer_helper.build_transfer_storages()

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
    job_id: Optional[str] = None,
    initial_session_index: int = 0,
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
    requested_job_id = job_id
    job_id = None
    saved_state: Optional[JobState] = None
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
        job_id=job_id or requested_job_id,
        recipe_path=path,
        is_resuming=resume and resume_from > 0,
        bridge_session=saved_state.bridge_session if saved_state else None,
    )
    executor.ctx.next_window_index = max(0, int(initial_session_index))

    # Restore windows info if resuming
    if resume and job_id:
        resume_state = state_manager.load(job_id)
        if resume_state:
            # Restore windows from checkpoint mapping.
            for name, host_spec in resume_state.hosts.items():
                remote_session = resume_state.window_sessions.get(name, "")
                if not remote_session:
                    # Fallback for older checkpoints without explicit mapping.
                    idx = len(executor.ctx.windows)
                    remote_session = get_window_session_name(recipe.name, job_id, idx)
                executor.ctx.windows[name] = WindowInfo(
                    name=name,
                    host=host_spec,
                    remote_session=remote_session,
                )

            # Restore monotonic open index so new tmux.open continues numbering.
            max_idx = -1
            for window in executor.ctx.windows.values():
                if not window.remote_session:
                    continue
                parsed = parse_window_session_index(window.remote_session, recipe.name, job_id)
                if parsed is not None and parsed > max_idx:
                    max_idx = parsed
            persisted_next = int(getattr(resume_state, "next_window_index", 0) or 0)
            executor.ctx.next_window_index = max(
                executor.ctx.next_window_index,
                persisted_next,
                max_idx + 1,
                len(executor.ctx.windows),
            )

            if executor.ctx.windows:
                executor.restore_tmux_bridge()

    return executor.execute(resume_from=resume_from)
