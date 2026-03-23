# tmux-trainsh DSL executor
# Executes parsed DSL recipes using remote tmux sessions for persistence

import subprocess
import json
import time
import re
import os
import shutil
import urllib.request
import urllib.error
import concurrent.futures
import threading
import shlex
import socket
import queue
from collections import defaultdict
from typing import Optional, Dict, List, Callable, Sequence, Any, Tuple
from datetime import datetime

from .executor_dependencies import _DeferredEvent
from .executor_runtime import _StepNode, ExecutionContext, WindowInfo
from .executor_scheduler import ExecutorSchedulingMixin
from .executor_support import ExecutorSupportMixin
from .provider_mixin import ExecutorProviderMixin

from ..config import load_config
from ..constants import RECIPE_FILE_EXTENSION
from ..constants import CONFIG_DIR, RUNTIME_STATE_DIR
from .recipe_models import RecipeModel, RecipeStepModel, StepType
from .bridge_exec import BridgeExecutionHelper
from .executor_execute import ExecuteHelper
from .executor_tmux import TmuxControlHelper
from .executor_transfer import TransferHelper
from .executor_runpod import RunpodControlHelper
from .executor_vast import VastControlHelper
from .executor_wait import WaitHelper
from .execution_log import ExecutionLogger
from .local_tmux import LocalTmuxClient
from .remote_tmux import RemoteTmuxClient
from .secrets import get_secrets_manager
from .models import Host, Storage, StorageType
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
    _resolve_runpod_host,
    _resolve_vast_host,
)
from ..utils.notifier import Notifier, normalize_channels, parse_bool
from ..runtime import CallbackManager, CallbackEvent
from ..pyrecipe.models import ProviderStep
from .task_state import TaskInstanceState, FINISHED_STATES
from .ti_dependencies import TIDependencyEvaluator, DependencyContext
from .pool_manager import RuntimeStatePoolManager
from .runtime_store import to_jsonable
from .triggerer import Triggerer


class DSLExecutor(ExecutorSchedulingMixin, ExecutorProviderMixin, ExecutorSupportMixin):
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
    _ALLOWED_TRIGGER_RULES = {
        "all_success",
        "all_done",
        "all_failed",
        "one_success",
        "one_failed",
        "none_failed",
        "none_failed_or_skipped",
    }

    def __init__(
        self,
        recipe: RecipeModel,
        log_callback: Optional[Callable[[str], None]] = None,
        job_id: Optional[str] = None,
        recipe_path: Optional[str] = None,
        is_resuming: bool = False,
        allow_host_execute: bool = False,
        bridge_session: Optional[str] = None,
        callback_sinks: Optional[Sequence] = None,
        executor_name: str = "sequential",
        executor_kwargs: Optional[Dict[str, Any]] = None,
        run_type: str = "manual",
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
        self.state_manager = JobStateManager(str(RUNTIME_STATE_DIR))
        self.job_state: Optional[JobState] = None
        from ..runtime import _coerce_max_workers, normalize_executor_name

        self.executor_name = normalize_executor_name(executor_name or "sequential")
        self.executor_kwargs = dict(executor_kwargs or {})
        self.max_workers = _coerce_max_workers(self.executor_kwargs, default=4)
        self._pool_limits = self._parse_pool_limits(self.executor_kwargs.get("pools", self.executor_kwargs.get("pool_slots")))
        self.run_type = str(run_type or "manual").strip().lower() or "manual"
        self._thread_lock = threading.RLock()
        self._ti_dependency_evaluator = TIDependencyEvaluator()
        self._triggerer = Triggerer()
        self._pool_manager = RuntimeStatePoolManager(
            str(RUNTIME_STATE_DIR),
            default_slots=self._pool_limits,
        )
        self._pool_manager.sync_slots(self._pool_limits)
        self._deferred_events: Dict[str, _DeferredEvent] = {}
        self._step_runtime_ctx = threading.local()

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
        self.transfer_helper = TransferHelper(self, _resolve_vast_host, _resolve_runpod_host, _host_from_ssh_spec)
        self.wait_helper = WaitHelper(self, _build_ssh_args, _host_from_ssh_spec, _format_duration)
        self.local_tmux = LocalTmuxClient()
        self._remote_tmux_clients: Dict[str, RemoteTmuxClient] = {}
        self.execute_helper = ExecuteHelper(self, _build_ssh_args, WindowInfo)
        self.vast_control = VastControlHelper(self, _build_ssh_args, _format_duration)
        self.runpod_control = RunpodControlHelper(self, _build_ssh_args, _format_duration)

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
        self.callback_manager = CallbackManager(callback_sinks or [])
        self._closed = False

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
        runpod_pod_id = self.ctx.variables.get("RUNPOD_ID") or self.ctx.variables.get("_runpod_pod_id")
        runpod_start_time = self.ctx.variables.get("_runpod_start_time")

        self.job_state = JobState(
            job_id=self.ctx.job_id,
            recipe_path=os.path.abspath(os.path.expanduser(self.recipe_path)),
            recipe_name=self.recipe.name,
            current_step=step_num,
            total_steps=len(self.recipe.steps),
            status=status,
            variables=dict(self.ctx.variables),
            hosts=hosts,
            storages=self._storage_snapshot(),
            window_sessions=window_sessions,
            next_window_index=self.ctx.next_window_index,
            bridge_session=self.tmux_bridge.get_state_session(),
            vast_instance_id=vast_instance_id,
            vast_start_time=vast_start_time,
            runpod_pod_id=runpod_pod_id,
            runpod_start_time=runpod_start_time,
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
        with self._thread_lock:
            self.log_callback(f"[{timestamp}] {msg}")

    def _emit_event(self, event: str, *, step_num: Optional[int] = None, **payload: object) -> None:
        """Emit execution lifecycle events."""
        try_number_raw = payload.get("try_number", 1)
        try:
            try_number = int(try_number_raw)
        except Exception:
            try_number = 1
        with self._thread_lock:
            self.callback_manager.emit(
                CallbackEvent(
                    event=event,
                    run_id=self.ctx.job_id,
                    recipe_name=self.recipe.name,
                    recipe_path=self.recipe_path or "",
                    step_num=step_num,
                    try_number=max(1, try_number),
                    payload=dict(payload),
                )
            )

    def _set_active_step_context(self, *, step_id: str, step_num: int, try_number: int) -> None:
        """Attach current step metadata to thread-local context."""
        self._step_runtime_ctx.step_id = str(step_id or "")
        self._step_runtime_ctx.step_num = int(step_num or 0)
        self._step_runtime_ctx.try_number = max(1, int(try_number or 1))

    def _clear_active_step_context(self) -> None:
        """Clear thread-local step metadata."""
        self._step_runtime_ctx.step_id = ""
        self._step_runtime_ctx.step_num = 0
        self._step_runtime_ctx.try_number = 1

    def _current_step_id(self) -> str:
        value = getattr(self._step_runtime_ctx, "step_id", "")
        return str(value or "")

    def _current_step_num(self) -> int:
        value = getattr(self._step_runtime_ctx, "step_num", 0)
        try:
            return int(value)
        except Exception:
            return 0

    def _current_try_number(self) -> int:
        value = getattr(self._step_runtime_ctx, "try_number", 1)
        try:
            parsed = int(value)
        except Exception:
            return 1
        return max(1, parsed)

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
            db_path=str(RUNTIME_STATE_DIR),
        )
        self.logger.start(
            self.recipe.name,
            self.ctx.variables,
            dict(self.recipe.hosts.items()),
            self.recipe_path or "",
        )
        self._emit_event(
            "execution_start",
            run_type=self.run_type,
            variables=dict(self.ctx.variables),
            hosts=dict(self.recipe.hosts),
            storages=self._storage_snapshot(),
        )

        from ..runtime import PARALLEL_EXECUTOR_ALIASES

        parallel_executors = PARALLEL_EXECUTOR_ALIASES
        try:
            if self.executor_name in parallel_executors:
                success = self._execute_with_dependencies(resume_from=resume_from)
            else:
                success = self._execute_sequential(resume_from=resume_from)
        finally:
            self._pool_manager.close()

        # Finalize
        total_ms = int((datetime.now() - self.ctx.start_time).total_seconds() * 1000)
        if self.logger:
            self.logger.end(success, total_ms, dict(self.ctx.variables))
        self._emit_event(
            "execution_end",
            success=success,
            total_ms=total_ms,
            total_steps=len(self.recipe.steps),
            final_variables=dict(self.ctx.variables),
        )

        if success:
            self._clear_checkpoint()
            status = "completed"
        else:
            status = "failed"

        self.log(f"Recipe {status} in {total_ms}ms")

        return success

    def close(self) -> None:
        """Release executor-owned resources."""
        if self._closed:
            return
        self._closed = True
        logger = getattr(self, "logger", None)
        if logger is not None:
            close = getattr(logger, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        callback_manager = getattr(self, "callback_manager", None)
        if callback_manager is not None:
            close = getattr(callback_manager, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        pool_manager = getattr(self, "_pool_manager", None)
        if pool_manager is not None:
            close = getattr(pool_manager, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def __enter__(self) -> "DSLExecutor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def __del__(self):
        self.close()

    def _execute_step(self, step) -> tuple[bool, str]:
        """Execute a single step."""
        step = self._coerce_step(step)

        if isinstance(step, ProviderStep):
            return self._exec_provider(step)

        if getattr(step, "command", "") == "provider":
            return self._exec_provider(step)

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

    def _exec_control(self, step: RecipeStepModel) -> tuple[bool, str]:
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
        elif cmd == "runpod.start":
            return self._cmd_runpod_start(args)
        elif cmd == "runpod.stop":
            return self._cmd_runpod_stop(args)
        elif cmd == "runpod.pick":
            return self._cmd_runpod_pick(args)
        elif cmd == "runpod.wait":
            return self._cmd_runpod_wait(args)
        elif cmd == "runpod.cost":
            return self._cmd_runpod_cost(args)
        elif cmd == "sleep":
            return self._cmd_sleep(args)
        else:
            return False, f"Unknown control command: {cmd}"


def run_recipe(
    path: str,
    log_callback: Optional[Callable[[str], None]] = None,
    host_overrides: Optional[Dict[str, str]] = None,
    var_overrides: Optional[Dict[str, str]] = None,
    resume: bool = False,
    job_id: Optional[str] = None,
    initial_session_index: int = 0,
    executor_name: Optional[str] = None,
    executor_kwargs: Optional[Dict[str, object]] = None,
    callbacks: Optional[Sequence[str]] = None,
    callback_sinks: Optional[Sequence] = None,
    run_type: str = "manual",
) -> bool:
    """
    Load and execute a recipe file.

    Args:
        path: Path to a Python recipe source file
        log_callback: Optional log callback
        host_overrides: Override hosts for fresh runs (not supported with resume)
        var_overrides: Override variables (e.g., {"MODEL": "mistral"})
        resume: If True, try to resume from saved checkpoint
        executor_name: Optional execution strategy override (`sequential`, `thread_pool`)
        executor_kwargs: Executor-specific options (e.g., {"max_workers": 4})
        callbacks: Callback sink names (`console`, `jsonl`)
        run_type: Execution type (`manual`/`scheduled`)

    Returns:
        True if successful
    """
    from ..runtime import build_sinks, get_executor
    from ..runtime import JsonlCallbackSink

    path = os.path.abspath(os.path.expanduser(path))
    if not path.endswith(RECIPE_FILE_EXTENSION):
        raise ValueError(f"run_recipe only supports Python recipe source files ({RECIPE_FILE_EXTENSION})")
    if resume and host_overrides:
        raise ValueError("Host overrides are not supported when resuming a Python recipe")

    from ..pyrecipe import load_python_recipe

    recipe = load_python_recipe(path)
    merged_kwargs = dict(recipe.executor_kwargs or {})
    merged_kwargs.update(executor_kwargs or {})
    executor_kwargs = merged_kwargs
    if callbacks is None and recipe.callbacks:
        callbacks = recipe.callbacks
    if executor_name is None and recipe.executor:
        executor_name = recipe.executor
    if not executor_name:
        executor_name = "sequential"
    if not callbacks:
        callbacks = ["console"]

    resume_from = 0
    requested_job_id = job_id
    job_id = None
    saved_state: Optional[JobState] = None
    state_manager = JobStateManager(str(RUNTIME_STATE_DIR))

    if resume:
        saved_state = state_manager.find_resumable(path)
        if saved_state:
            job_id = saved_state.job_id
            resume_from = saved_state.current_step
            recipe.variables.update(saved_state.variables)
            for name, host_spec in saved_state.hosts.items():
                recipe.hosts[name] = host_spec
            if log_callback:
                log_callback(
                    f"Found saved state: job {job_id}, step {resume_from + 1}/{saved_state.total_steps}"
                )
        else:
            if log_callback:
                log_callback("No resumable state found, starting fresh")

    if var_overrides:
        recipe.variables.update(var_overrides)

    if host_overrides:
        for name, value in host_overrides.items():
            if value.startswith("vast:"):
                instance_id = value[5:]
                recipe.hosts[name] = f"vast:{instance_id}"
                if not var_overrides or "VAST_ID" not in var_overrides:
                    recipe.variables["VAST_ID"] = instance_id
            elif value.startswith("runpod:"):
                pod_id = value[7:]
                recipe.hosts[name] = f"runpod:{pod_id}"
                if not var_overrides or "RUNPOD_ID" not in var_overrides:
                    recipe.variables["RUNPOD_ID"] = pod_id
            else:
                recipe.hosts[name] = value

    sinks: List = [JsonlCallbackSink(str(RUNTIME_STATE_DIR))]
    sinks.extend(list(callback_sinks or []))
    public_callbacks = []
    for raw_name in callbacks or []:
        if not raw_name:
            continue
        parts = [part.strip() for part in str(raw_name).split(",") if part.strip()]
        filtered = [part for part in parts if part.lower() == "jsonl"]
        if filtered:
            public_callbacks.append(",".join(filtered))
    if public_callbacks:
        sinks.extend(
            build_sinks(
                public_callbacks,
                log_callback=log_callback or print,
                runtime_state=str(RUNTIME_STATE_DIR),
            )
        )

    bridge_session = saved_state.bridge_session if saved_state else None
    executor = DSLExecutor(
        recipe,
        log_callback=log_callback,
        job_id=job_id or requested_job_id,
        recipe_path=path,
        is_resuming=resume and resume_from > 0,
        bridge_session=bridge_session,
        callback_sinks=sinks,
        executor_name=executor_name,
        executor_kwargs=executor_kwargs,
        run_type=run_type,
    )
    executor.ctx.next_window_index = max(0, int(initial_session_index))

    if resume and job_id and saved_state:
        resume_state = state_manager.load(job_id)
        if resume_state:
            for name, host_spec in resume_state.hosts.items():
                remote_session = resume_state.window_sessions.get(name, "")
                if not remote_session:
                    idx = len(executor.ctx.windows)
                    remote_session = get_window_session_name(recipe.name, job_id, idx)
                executor.ctx.windows[name] = WindowInfo(
                    name=name,
                    host=host_spec,
                    remote_session=remote_session,
                )

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

    try:
        return get_executor(executor_name, **executor_kwargs).execute(
            lambda: executor.execute(resume_from=resume_from)
        )
    finally:
        close = getattr(executor, "close", None)
        if callable(close):
            close()
