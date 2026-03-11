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
from dataclasses import dataclass, field
from datetime import datetime

from ..config import load_config
from ..constants import CONFIG_DIR
from .recipe_models import RecipeModel, RecipeStepModel, StepType
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
    _resolve_vast_host,
)
from ..utils.notifier import Notifier, normalize_channels, parse_bool
from ..runtime import CallbackManager, CallbackEvent
from ..pyrecipe.models import ProviderStep
from .task_state import TaskInstanceState, FINISHED_STATES
from .ti_dependencies import TIDependencyEvaluator, DependencyContext
from .pool_manager import SqlitePoolManager
from .triggerer import Triggerer


@dataclass
class WindowInfo:
    """Tracks a remote tmux session."""
    name: str
    host: str
    remote_session: Optional[str] = None  # Remote tmux session name (for nohup-like behavior)


@dataclass
class ExecutionContext:
    """Runtime context for recipe execution."""
    recipe: RecipeModel
    variables: Dict[str, str] = field(default_factory=dict)
    windows: Dict[str, WindowInfo] = field(default_factory=dict)
    exec_id: str = ""
    job_id: str = ""  # Persistent job ID for resume
    next_window_index: int = 0  # Monotonic tmux.open index for session naming
    start_time: Optional[datetime] = None
    log_callback: Optional[Callable[[str], None]] = None


@dataclass
class _StepNode:
    """Runtime step node used for dependency scheduling."""

    step_num: int
    step_id: str
    step: object
    depends_on: List[str]
    retries: int = 0
    retry_delay: int = 0
    continue_on_failure: bool = False
    trigger_rule: str = "all_success"
    pool: str = "default"
    priority: int = 0
    execution_timeout: int = 0
    retry_exponential_backoff: float = 0.0
    on_success: list = field(default_factory=list)
    on_failure: list = field(default_factory=list)
    max_active_tis_per_dagrun: Optional[int] = None
    deferrable: bool = False


@dataclass
class _DeferredEvent:
    task_id: str
    started_at: float


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
        self.state_manager = JobStateManager()
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
        self._pool_manager = SqlitePoolManager(
            str(CONFIG_DIR / "runtime.db"),
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
        self.callback_manager = CallbackManager(callback_sinks or [])

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

    def _coerce_step(self, step):
        """Normalize Python DSL step wrappers (keep wrappers so dependency metadata stays attached)."""
        if not isinstance(step, RecipeStepModel) and hasattr(step, "to_step_model"):
            return step
        return step

    def _extract_step_id(self, step, index: int) -> str:
        """Get stable step id for dependency resolution."""
        raw_id = getattr(step, "id", "")
        if raw_id:
            return str(raw_id)
        return f"step_{index + 1:03d}"

    def _extract_depends(self, step) -> List[str]:
        """Extract step dependencies from wrapper metadata."""
        raw = getattr(step, "depends_on", None)
        if not raw:
            return []
        if isinstance(raw, str):
            raw = [raw]
        depends: List[str] = []
        seen = set()
        for dep in raw:
            if not dep:
                continue
            dep_id = str(dep)
            if dep_id in seen:
                continue
            seen.add(dep_id)
            depends.append(dep_id)
        return depends

    def _normalize_bool(self, value: Any, *, default: bool = False) -> bool:
        """Normalize truthy values."""
        if isinstance(value, bool):
            return bool(value)
        text = str(value).strip().lower()
        if not text:
            return bool(default)
        return text in {"1", "true", "yes", "y", "on"}

    def _coerce_bool(self, value: Any, *, default: bool = False) -> bool:
        """Normalize bool-like values."""
        return self._normalize_bool(value, default=default)

    def _coerce_list(self, value: Any) -> List[str]:
        """Normalize list-like values (comma separated or list/tuple/set)."""
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _normalize_retry_delay(self, value: Any) -> int:
        """Normalize retry delay to seconds."""
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        try:
            return max(0, self._parse_duration(str(value).strip()))
        except Exception:
            try:
                return max(0, int(str(value).strip()))
            except Exception:
                return 0

    def _extract_step_retries(self, step) -> int:
        value = getattr(step, "retries", 0)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _extract_step_retry_delay(self, step) -> int:
        return self._normalize_retry_delay(getattr(step, "retry_delay", 0))

    def _extract_step_continue_on_failure(self, step) -> bool:
        return self._normalize_bool(getattr(step, "continue_on_failure", False), default=False)

    def _extract_step_trigger_rule(self, step) -> str:
        trigger_rule = str(getattr(step, "trigger_rule", "all_success")).strip().lower()
        if trigger_rule not in self._ALLOWED_TRIGGER_RULES:
            return "all_success"
        return trigger_rule

    def _extract_step_max_active_tis_per_dagrun(self, step) -> Optional[int]:
        value = getattr(step, "max_active_tis_per_dagrun", None)
        if value is None:
            return None
        if isinstance(value, bool):
            return None if value is False else 1
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return None

    def _extract_step_deferrable(self, step) -> bool:
        return self._normalize_bool(getattr(step, "deferrable", False), default=False)

    def _extract_step_pool(self, step) -> str:
        pool = str(getattr(step, "pool", "default")).strip() or "default"
        return pool

    def _extract_step_priority(self, step) -> int:
        value = getattr(step, "priority", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _extract_step_execution_timeout(self, step) -> int:
        value = getattr(step, "execution_timeout", 0)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        try:
            timeout = self._parse_duration(str(value).strip())
            return max(0, int(timeout))
        except Exception:
            try:
                return max(0, int(str(value).strip()))
            except Exception:
                return 0

    def _extract_step_retry_exponential_backoff(self, step) -> float:
        value = getattr(step, "retry_exponential_backoff", 0.0)
        if isinstance(value, bool):
            return 2.0 if value else 0.0
        try:
            parsed = float(value)
        except Exception:
            return 0.0
        if parsed < 0:
            return 0.0
        return parsed

    def _extract_step_callbacks(self, step, attr: str) -> List[Any]:
        value = getattr(step, attr, [])
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            callbacks: List[Any] = []
            for item in value:
                if item is None:
                    continue
                if callable(item) or isinstance(item, (str, bytes, dict, ProviderStep)):
                    callbacks.append(item)
            return callbacks
        if callable(value) or isinstance(value, (str, bytes, dict, ProviderStep)):
            return [value]
        return []

    def _step_is_terminal(self, state: str) -> bool:
        return state in FINISHED_STATES

    def _compute_backoff_delay(self, node: _StepNode, attempt: int) -> int:
        """Compute delay before next retry attempt."""
        delay = max(0, int(node.retry_delay or 0))
        backoff = float(node.retry_exponential_backoff or 0.0)
        if attempt <= 1 or backoff <= 0:
            return delay
        return int(delay * (backoff ** (attempt - 1)))

    def _emit_step_start(self, node: _StepNode, step_id: str, *, try_number: int = 1) -> None:
        step = node.step
        step_details = self._build_step_details(step)
        self._emit_event(
            "step_start",
            step_num=node.step_num,
            step_id=step_id,
            try_number=max(1, int(try_number)),
            raw=step.raw,
            step_type=getattr(step.type, "value", str(step.type)),
            details=step_details,
        )
        if self.logger:
            with self._thread_lock:
                self.logger.step_start(node.step_num, step.raw, str(getattr(step.type, "value", str(step.type))), step_details)

    def _emit_step_end(
        self,
        node: _StepNode,
        step_id: str,
        *,
        state: str,
        success: bool,
        duration_ms: int,
        output: str,
        error: str = "",
        try_number: int = 1,
    ) -> None:
        self._emit_event(
            "step_end",
            step_num=node.step_num,
            step_id=step_id,
            try_number=max(1, int(try_number)),
            raw=node.step.raw,
            step_type=getattr(node.step.type, "value", str(node.step.type)),
            state=state,
            success=success,
            duration_ms=duration_ms,
            output=output,
            error=error,
        )

    def _parse_pool_limits(self, value: Any) -> Dict[str, int]:
        """Parse airflow-style pool limits from executor kwargs."""
        parsed: Dict[str, int] = {}
        if value is None:
            return {"default": self.max_workers}

        if isinstance(value, str):
            try:
                import ast

                value = ast.literal_eval(value)
            except Exception:
                value = None

        if isinstance(value, int):
            cap = max(1, value)
            return {"default": cap}

        if isinstance(value, dict):
            for pool_name, pool_limit in value.items():
                try:
                    parsed[str(pool_name)] = max(1, int(pool_limit))
                except (TypeError, ValueError):
                    continue
            if not parsed:
                parsed["default"] = self.max_workers
            elif "default" not in parsed:
                parsed["default"] = self.max_workers
            return parsed

        if not parsed:
            parsed["default"] = self.max_workers
        return parsed

    def _pool_limit(self, pool_name: str) -> int:
        pool_name = str(pool_name or "default").strip() or "default"
        return int(self._pool_limits.get(pool_name, self._pool_limits.get("default", self.max_workers)))

    def _build_step_graph(self) -> Tuple[Dict[str, _StepNode], List[str], bool]:
        """Build the execution graph for dependency-aware runs."""
        nodes: Dict[str, _StepNode] = {}
        ordered_ids: List[str] = []
        has_dep = False

        for i, raw_step in enumerate(self.recipe.steps):
            step = self._coerce_step(raw_step)
            step_id = self._extract_step_id(step, i)
            depends_on = self._extract_depends(step)
            has_dep = has_dep or bool(depends_on)

            if step_id in nodes:
                raise ValueError(f"duplicate step id: {step_id}")

            nodes[step_id] = _StepNode(
                step_num=i + 1,
                step_id=step_id,
                step=step,
                depends_on=depends_on,
                retries=self._extract_step_retries(step),
                retry_delay=self._extract_step_retry_delay(step),
                continue_on_failure=self._extract_step_continue_on_failure(step),
                trigger_rule=self._extract_step_trigger_rule(step),
                pool=self._extract_step_pool(step),
                priority=self._extract_step_priority(step),
                execution_timeout=self._extract_step_execution_timeout(step),
                retry_exponential_backoff=self._extract_step_retry_exponential_backoff(step),
                on_success=self._extract_step_callbacks(step, "on_success"),
                on_failure=self._extract_step_callbacks(step, "on_failure"),
                max_active_tis_per_dagrun=self._extract_step_max_active_tis_per_dagrun(step),
                deferrable=self._extract_step_deferrable(step),
            )
            ordered_ids.append(step_id)

        for node in nodes.values():
            for dep_id in node.depends_on:
                if dep_id not in nodes:
                    raise ValueError(f"unknown dependency '{dep_id}' for step '{node.step_id}'")

        return nodes, ordered_ids, has_dep

    def _build_step_details(self, step: object) -> Dict[str, object]:
        """Build normalized detail payload for callbacks/logging."""
        return {
            "step_id": getattr(step, "id", ""),
            "host": getattr(step, "host", ""),
            "command": getattr(step, "command", ""),
            "commands": getattr(step, "commands", ""),
            "args": getattr(step, "args", []),
            "source": getattr(step, "source", ""),
            "dest": getattr(step, "dest", ""),
            "delete": getattr(step, "delete", False),
            "operation": getattr(step, "operation", ""),
            "exclude": getattr(step, "exclude", []),
            "target": getattr(step, "target", ""),
            "pattern": getattr(step, "pattern", ""),
            "condition": getattr(step, "condition", ""),
            "provider": getattr(step, "provider", ""),
            "params": getattr(step, "params", {}),
            "timeout": getattr(step, "timeout", 0),
            "background": getattr(step, "background", False),
            "execution_timeout": getattr(step, "execution_timeout", 0),
            "retry_delay": getattr(step, "retry_delay", 0),
            "retries": getattr(step, "retries", 0),
            "continue_on_failure": getattr(step, "continue_on_failure", False),
            "trigger_rule": getattr(step, "trigger_rule", "all_success"),
            "max_active_tis_per_dagrun": getattr(step, "max_active_tis_per_dagrun", None),
            "priority": getattr(step, "priority", 0),
            "pool": getattr(step, "pool", "default"),
            "retry_exponential_backoff": getattr(step, "retry_exponential_backoff", 0.0),
            "deferrable": getattr(step, "deferrable", False),
        }

    def _build_defer_check(
        self,
        node: _StepNode,
        *,
        step_id: str,
        attempt: int,
    ) -> Optional[tuple[Callable[[], tuple[bool, str]], Optional[float], float]]:
        """Build a triggerable condition check for Airflow-style deferrable wait steps.

        Returns:
            (check_fn, timeout_secs, poll_interval_secs)
            or None if the step is not deferrable-capable.
        """
        step = node.step
        provider, operation, params = self._extract_provider_metadata(step)
        if provider not in {"util", "utils"}:
            return None
        if operation not in {"wait_condition", "wait_for_condition"}:
            return None
        if not isinstance(params, dict):
            return None

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return None

        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            allow_zero=True,
        )
        if timeout is None:
            self.log(
                f"Step {node.step_num} ({step_id}) cannot start deferrable: invalid timeout value, fallback to normal run."
            )
            return None
        poll_interval = self._normalize_provider_timeout(
            params.get(
                "poll_interval",
                params.get("interval", params.get("poll_interval_secs", 5)),
            ),
            allow_zero=True,
        )
        if poll_interval is None or poll_interval <= 0:
            poll_interval = 5
        host = self._provider_host(params.get("host", "local"))
        capture_output = self._coerce_bool(params.get("capture", params.get("capture_output", False)), default=False)

        if attempt > 1:
            self.log(f"Step {node.step_num} ({step_id}) restarting deferrable wait (attempt {attempt}).")

        def _check() -> tuple[bool, str]:
            ok, message = self._eval_condition(condition, host=host)
            if ok:
                if capture_output:
                    return True, message
                return True, f"Condition met: {condition}"
            if capture_output:
                return False, message
            return False, f"Condition not met yet: {condition}"

        return _check, timeout, poll_interval

    def _run_single_step_with_state(
        self,
        step_num: int,
        step: object,
        *,
        step_id: Optional[str] = None,
        try_number: int = 1,
        track_checkpoint: bool = True,
        execution_timeout: int = 0,
        emit_events: bool = True,
    ) -> Tuple[str, str, int]:
        """Execute one step and return (state, output, duration_ms)."""
        step = self._coerce_step(step)
        step_id = step_id or ""
        step_num = int(step_num)
        step_details = self._build_step_details(step)

        if emit_events:
            self._emit_event(
                "step_start",
                step_num=step_num,
                step_id=step_id,
                try_number=max(1, int(try_number)),
                raw=step.raw,
                step_type=getattr(step.type, "value", ""),
                details=step_details,
            )
            if self.logger:
                with self._thread_lock:
                    self.logger.step_start(step_num, step.raw, step.type.value, step_details)

        if track_checkpoint:
            self._save_checkpoint(step_num - 1)

        start = datetime.now()
        try:
            timeout_secs = max(0, int(execution_timeout))
            ok, output = self._execute_step_with_timeout(
                step,
                timeout_secs=timeout_secs,
                step_id=step_id,
                step_num=step_num,
                try_number=try_number,
            )
            duration_ms = int((datetime.now() - start).total_seconds() * 1000)

            state = TaskInstanceState.SUCCESS if ok else TaskInstanceState.FAILED
            if emit_events:
                if self.logger:
                    with self._thread_lock:
                        if output:
                            self.logger.step_output(step_num, output, "result")
                        self.logger.step_end(
                            step_num,
                            ok,
                            duration_ms,
                            result=output if ok else "",
                            error="" if ok else output,
                        )

                self._emit_event(
                    "step_end",
                    step_num=step_num,
                    step_id=step_id,
                    try_number=max(1, int(try_number)),
                    raw=step.raw,
                    step_type=getattr(step.type, "value", ""),
                    state=state,
                    success=ok,
                    duration_ms=duration_ms,
                    output=output,
                    error="" if ok else output,
                )
            return state, output, duration_ms

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            if emit_events:
                if self.logger:
                    with self._thread_lock:
                        self.logger.step_output(step_num, error_detail, "exception")
                        self.logger.step_end(step_num, False, 0, error=str(e))
                self._emit_event(
                    "step_end",
                    step_num=step_num,
                    step_id=step_id,
                    try_number=max(1, int(try_number)),
                    raw=step.raw,
                    step_type=getattr(step.type, "value", ""),
                    state=TaskInstanceState.FAILED,
                    success=False,
                    duration_ms=0,
                    output=error_detail,
                    error=str(e),
                )
            return TaskInstanceState.FAILED, error_detail, 0

    def _run_single_step(
        self,
        step_num: int,
        step: object,
        *,
        step_id: Optional[str] = None,
        try_number: int = 1,
        track_checkpoint: bool = True,
        execution_timeout: int = 0,
    ) -> Tuple[bool, str, int]:
        """Execute one step and return (ok, output, duration_ms)."""
        state, output, duration_ms = self._run_single_step_with_state(
            step_num,
            step,
            step_id=step_id,
            try_number=try_number,
            track_checkpoint=track_checkpoint,
            execution_timeout=execution_timeout,
            emit_events=True,
        )
        return state == TaskInstanceState.SUCCESS, output, duration_ms

    def _execute_step_with_timeout(
        self,
        step: object,
        *,
        timeout_secs: int = 0,
        step_id: str = "",
        step_num: int = 0,
        try_number: int = 1,
    ) -> tuple[bool, str]:
        def _execute_with_context() -> tuple[bool, str]:
            self._set_active_step_context(
                step_id=step_id,
                step_num=step_num,
                try_number=try_number,
            )
            try:
                return self._execute_step(step)
            finally:
                self._clear_active_step_context()

        if timeout_secs <= 0:
            return _execute_with_context()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_execute_with_context)
            try:
                return future.result(timeout=timeout_secs)
            except concurrent.futures.TimeoutError:
                return False, f"Step timeout after {timeout_secs}s"

    def _run_single_step_with_retries(
        self,
        node: _StepNode,
        *,
        step_id: Optional[str] = None,
        track_checkpoint: bool = True,
    ) -> Tuple[bool, str, int]:
        """Run a step with configured retry count and delay."""
        retries = max(0, int(node.retries or 0))
        delay = max(0, int(node.retry_delay or 0))
        backoff_factor = float(node.retry_exponential_backoff or 0.0)
        last_output = ""
        last_duration_ms = 0

        for attempt in range(retries + 1):
            if attempt > 0:
                attempt_delay = delay
                if attempt > 1 and backoff_factor > 0:
                    attempt_delay = int(delay * (backoff_factor ** (attempt - 1)))
                if attempt_delay > 0:
                    self.log(
                        f"↺ Step {node.step_num}: retry {attempt}/{retries} after {attempt_delay}s"
                    )
                    time.sleep(attempt_delay)
                else:
                    self.log(f"↺ Step {node.step_num}: retry {attempt}/{retries}")
            ok, output, duration_ms = self._run_single_step(
                node.step_num,
                node.step,
                step_id=step_id,
                try_number=attempt + 1,
                track_checkpoint=track_checkpoint and attempt == 0,
                execution_timeout=node.execution_timeout,
            )
            last_output = output
            last_duration_ms = duration_ms
            if ok:
                self._run_step_callbacks(
                    node,
                    stage="run",
                    ok=True,
                    output=output,
                    duration_ms=duration_ms,
                    try_number=attempt + 1,
                )
                return True, output, duration_ms

            if attempt < retries:
                continue

        self._run_step_callbacks(
            node,
            stage="run",
            ok=False,
            output=last_output,
            duration_ms=last_duration_ms,
            try_number=retries + 1,
        )
        return False, last_output, last_duration_ms

    def _run_step_callbacks(
        self,
        node: _StepNode,
        *,
        stage: str,
        ok: bool,
        output: str,
        duration_ms: int,
        try_number: int = 1,
    ) -> None:
        callbacks = node.on_success if ok else node.on_failure
        if not callbacks:
            return

        context = {
            "step_id": node.step_id,
            "step_num": node.step_num,
            "step_raw": node.step.raw if hasattr(node.step, "raw") else "",
            "step_type": str(getattr(node.step, "type", "")),
            "host": getattr(node.step, "host", ""),
            "callback_host": getattr(node.step, "host", "local") or "local",
            "retries": node.retries,
            "retry_delay": node.retry_delay,
            "trigger_rule": node.trigger_rule,
            "pool": node.pool,
            "priority": node.priority,
            "ok": ok,
            "output": output,
            "duration_ms": duration_ms,
            "stage": stage,
            "try_number": max(1, int(try_number)),
        }
        for callback in list(callbacks):
            self._run_step_callback(callback, context=context)

    def _render_callback_value(self, value: Any, context: Dict[str, Any]) -> Any:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if not isinstance(value, str):
            return value
        mapping = defaultdict(lambda: "", {k: "" if v is None else str(v) for k, v in context.items()})
        try:
            return value.format_map(mapping)
        except Exception:
            return value

    def _normalize_callback_payload(self, value: Any, context: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._render_callback_value(value, context)
        if isinstance(value, dict):
            return {
                key: self._normalize_callback_payload(val, context)
                for key, val in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_callback_payload(item, context) for item in value]
        return value

    def _run_step_callback(self, callback: Any, context: Dict[str, Any]) -> None:
        try:
            if isinstance(callback, ProviderStep):
                rendered = ProviderStep(
                    provider=self._render_callback_value(callback.provider, context),
                    operation=self._render_callback_value(callback.operation, context),
                    params=self._normalize_callback_payload(dict(callback.params or {}), context),
                    id=str(getattr(callback, "id", "callback")),
                    depends_on=list(getattr(callback, "depends_on", []) or []),
                    retries=int(getattr(callback, "retries", 0) or 0),
                    retry_delay=getattr(callback, "retry_delay", 0),
                    continue_on_failure=bool(getattr(callback, "continue_on_failure", False)),
                    trigger_rule=str(getattr(callback, "trigger_rule", "all_success")),
                    pool=str(getattr(callback, "pool", "default")),
                    priority=int(getattr(callback, "priority", 0) or 0),
                    execution_timeout=int(getattr(callback, "execution_timeout", 0) or 0),
                    retry_exponential_backoff=float(getattr(callback, "retry_exponential_backoff", 0.0) or 0.0),
                    max_active_tis_per_dagrun=getattr(callback, "max_active_tis_per_dagrun", None),
                    deferrable=bool(getattr(callback, "deferrable", False)),
                    on_success=list(getattr(callback, "on_success", []) or []),
                    on_failure=list(getattr(callback, "on_failure", []) or []),
                )
                ok, output = self._exec_provider(rendered)
                if not ok:
                    self.log(
                        f"Callback provider step failed (step {context.get('step_num')}): {output}"
                    )
                return

            if callable(callback):
                try:
                    callback(context)
                except TypeError:
                    callback()
                return

            if isinstance(callback, str):
                self._run_provider_or_shell_callback(
                    {"command": callback, "host": context.get("callback_host", "local")},
                    context,
                )
                return

            if isinstance(callback, bytes):
                self._run_provider_or_shell_callback(
                    {
                        "command": callback.decode("utf-8", errors="ignore"),
                        "host": context.get("callback_host", "local"),
                    },
                    context,
                )
                return

            if isinstance(callback, dict):
                provider = callback.get("provider")
                operation = callback.get("operation")
                if provider and operation:
                    params = dict(callback.get("params", {}) or {})
                    if "host" in callback and "host" not in params:
                        params["host"] = callback.get("host")
                    params["provider"] = self._render_callback_value(str(provider), context)
                    params["operation"] = self._render_callback_value(
                        str(operation),
                        context,
                    )
                    ok, output = self._exec_provider(
                        type(
                            "RuntimeProviderCallback",
                            (),
                            {
                                "provider": params.pop("provider"),
                                "operation": params.pop("operation"),
                                "params": self._normalize_callback_payload(params, context),
                            },
                        )()
                    )
                    if not ok:
                        self.log(
                            f"Callback provider step failed (step {context.get('step_num')}): {output}"
                        )
                    return

                if "command" in callback:
                    normalized = dict(callback)
                    normalized["command"] = self._normalize_callback_payload(
                        callback.get("command"),
                        context,
                    )
                    normalized.setdefault("host", context.get("callback_host"))
                    self._run_provider_or_shell_callback(normalized, context)
                    return
                return

        except Exception as exc:  # noqa: BLE001
            self.log(f"Callback execution failed for step {context.get('step_num')}: {exc}")

    def _run_provider_or_shell_callback(self, spec: Dict[str, Any], context: Dict[str, Any]) -> None:
        command = self._render_callback_value(str(spec.get("command", "")).strip(), context)
        if not command:
            return
        raw_host = spec.get("host", context.get("callback_host", "local"))
        if raw_host is None:
            raw_host = "local"
        if isinstance(raw_host, bytes):
            raw_host = raw_host.decode("utf-8", errors="ignore")
        host = self._render_callback_value(str(raw_host), context)
        host = str(host or "local")
        timeout = self._normalize_provider_timeout(spec.get("timeout"), allow_zero=True)
        timeout_secs = 30 if timeout in (None, 0) else timeout
        cwd = self._normalize_callback_payload(spec.get("cwd"), context)
        env = self._normalize_callback_payload(spec.get("env"), context)

        params = {
            "command": command,
            "host": self._provider_host(host),
            "timeout": timeout_secs,
        }
        if cwd is not None:
            params["cwd"] = cwd
        if env is not None:
            params["env"] = env
        ok, output = self._exec_provider_shell(params)
        if not ok:
            self.log(
                f"Callback shell command failed (step {context.get('step_num')}): {output}"
            )

    def _execute_sequential(self, resume_from: int = 0) -> bool:
        """Execute recipe one step at a time while honoring dependency semantics."""
        return self._execute_with_dependencies(resume_from=resume_from, worker_limit=1)

    def _execute_with_dependencies(self, resume_from: int = 0, worker_limit: Optional[int] = None) -> bool:
        """Execute recipe by dependency graph with configurable concurrency."""
        try:
            nodes, ordered_ids, _ = self._build_step_graph()
        except ValueError as exc:
            self.log(f"Dependency error: {exc}")
            return False

        if not nodes:
            return True

        effective_workers = max(1, int(worker_limit or self.max_workers))

        states: Dict[str, str] = {}
        attempts: Dict[str, int] = {}
        retry_ready_at: Dict[str, float] = {}
        for sid, node in nodes.items():
            if node.step_num <= resume_from:
                states[sid] = TaskInstanceState.SUCCESS
            else:
                states[sid] = TaskInstanceState.SCHEDULED
                attempts[sid] = 0

        if all(self._step_is_terminal(state) for state in states.values()):
            return True

        running: Dict[concurrent.futures.Future, tuple[str, int]] = {}
        fatal = False
        self._deferred_events.clear()

        self._triggerer.start()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as thread_pool:
                while True:
                    now = time.time()
                    changed = False
                    scheduled_this_round = False

                    # Consume all triggerer events first.
                    while True:
                        try:
                            event = self._triggerer.events.get_nowait()
                        except queue.Empty:
                            break

                        sid = str(event.step_id)
                        deferred = self._deferred_events.pop(sid, None)
                        if deferred is None:
                            continue

                        node = nodes.get(sid)
                        if node is None:
                            continue

                        attempt = attempts.get(sid, 0)
                        duration_ms = int((time.time() - deferred.started_at) * 1000)
                        output = event.message or ""

                        if event.status == "success":
                            states[sid] = TaskInstanceState.SUCCESS
                            retry_ready_at.pop(sid, None)
                            self._emit_step_end(
                                node,
                                sid,
                                state=TaskInstanceState.SUCCESS,
                                success=True,
                                duration_ms=duration_ms,
                                output=output,
                                error="",
                                try_number=attempt,
                            )
                            self._run_step_callbacks(
                                node,
                                stage="run",
                                ok=True,
                                output=output,
                                duration_ms=duration_ms,
                                try_number=attempt,
                            )
                        else:
                            retries = max(0, int(node.retries or 0))
                            if attempt <= retries:
                                delay = self._compute_backoff_delay(node, attempt)
                                if delay > 0:
                                    retry_ready_at[sid] = now + delay
                                    retry_msg = f"retry after {delay}s"
                                else:
                                    retry_ready_at[sid] = now
                                    retry_msg = "retry immediately"

                                states[sid] = TaskInstanceState.UP_FOR_RETRY
                                self.log(
                                    f"↺ Step {node.step_num}: deferrable retry {attempt}/{retries} ({retry_msg})"
                                )
                            else:
                                states[sid] = TaskInstanceState.FAILED
                                retry_ready_at.pop(sid, None)
                                self._run_step_callbacks(
                                    node,
                                    stage="run",
                                    ok=False,
                                    output=output,
                                    duration_ms=duration_ms,
                                    try_number=attempt,
                                )
                                if not node.continue_on_failure:
                                    fatal = True
                                self._save_checkpoint(node.step_num - 1, status="failed")

                                self._emit_step_end(
                                    node,
                                    sid,
                                    state=TaskInstanceState.FAILED,
                                    success=False,
                                    duration_ms=duration_ms,
                                    output=output,
                                    error=output,
                                    try_number=attempt,
                                )
                        changed = True

                    # Process completed normal workers.
                    if running:
                        done, _ = concurrent.futures.wait(
                            running.keys(),
                            return_when=concurrent.futures.FIRST_COMPLETED,
                            timeout=0.2,
                        )
                        for fut in done:
                            sid, attempt = running.pop(fut)
                            node = nodes[sid]
                            self._pool_manager.release(node.pool)

                            state: str
                            output = ""
                            duration_ms = 0
                            try:
                                state, output, duration_ms = fut.result()
                            except Exception as exc:
                                output = str(exc)
                                state = TaskInstanceState.FAILED
                                duration_ms = 0

                            if state not in {TaskInstanceState.SUCCESS, TaskInstanceState.FAILED}:
                                state = TaskInstanceState.FAILED if output else TaskInstanceState.SUCCESS

                            attempts[sid] = max(attempts.get(sid, 0), attempt)

                            if state == TaskInstanceState.SUCCESS:
                                states[sid] = TaskInstanceState.SUCCESS
                                retry_ready_at.pop(sid, None)
                                self._emit_step_end(
                                    node,
                                    sid,
                                    state=TaskInstanceState.SUCCESS,
                                    success=True,
                                    duration_ms=duration_ms,
                                    output=output,
                                    error="",
                                    try_number=attempt,
                                )
                                self._run_step_callbacks(
                                    node,
                                    stage="run",
                                    ok=True,
                                    output=output,
                                    duration_ms=duration_ms,
                                    try_number=attempt,
                                )
                            else:
                                retries = max(0, int(node.retries or 0))
                                if attempt <= retries:
                                    delay = self._compute_backoff_delay(node, attempt)
                                    if delay > 0:
                                        retry_ready_at[sid] = time.time() + delay
                                        retry_msg = f"retry after {delay}s"
                                    else:
                                        retry_ready_at[sid] = time.time()
                                        retry_msg = "retry immediately"
                                    states[sid] = TaskInstanceState.UP_FOR_RETRY
                                    self.log(
                                        f"↺ Step {node.step_num}: failed, retry {attempt}/{retries} ({retry_msg})"
                                    )
                                else:
                                    states[sid] = TaskInstanceState.FAILED
                                    retry_ready_at.pop(sid, None)
                                    self._run_step_callbacks(
                                        node,
                                        stage="run",
                                        ok=False,
                                        output=output,
                                        duration_ms=duration_ms,
                                        try_number=attempt,
                                    )
                                    if not node.continue_on_failure:
                                        fatal = True
                                    self._save_checkpoint(node.step_num - 1, status="failed")
                                    self._emit_step_end(
                                        node,
                                        sid,
                                        state=TaskInstanceState.FAILED,
                                        success=False,
                                        duration_ms=duration_ms,
                                        output=output,
                                        error=output,
                                        try_number=attempt,
                                    )
                            changed = True

                    # Build dynamic context for dependency checks.
                    pool_stats = self._pool_manager.refresh()
                    pool_usage = {name: stats.occupied for name, stats in pool_stats.items()}
                    running_states = {
                        sid: state for sid, state in states.items()
                        if state == TaskInstanceState.RUNNING
                    }
                    running_step_ids = {sid for sid, _ in running.values()}
                    task_running_counts: Dict[str, int] = defaultdict(int)
                    for sid in running_states:
                        task_running_counts[sid] += 1

                    context = DependencyContext(
                        states=states,
                        running=running_states,
                        running_count=len(running),
                        max_active_tasks=effective_workers,
                        pool_limits=self._pool_limits,
                        pool_usage=pool_usage,
                        task_running_counts=task_running_counts,
                        retry_ready_at=retry_ready_at,
                        now=time.time(),
                    )

                    ready: List[str] = []
                    for sid in ordered_ids:
                        if states[sid] not in {TaskInstanceState.SCHEDULED, TaskInstanceState.UP_FOR_RETRY}:
                            continue
                        if sid in running_step_ids or sid in self._deferred_events:
                            continue

                        node = nodes[sid]
                        decision = self._ti_dependency_evaluator.evaluate(node, context)
                        if decision.met is False:
                            if decision.trigger_rule_failed:
                                states[sid] = TaskInstanceState.SKIPPED
                                changed = True
                                self._emit_step_end(
                                    node,
                                    sid,
                                    state=TaskInstanceState.SKIPPED,
                                    success=False,
                                    duration_ms=0,
                                    output="skipped by trigger_rule",
                                    error="skipped by trigger_rule",
                                    try_number=max(1, attempts.get(sid, 1)),
                                )
                                if self.logger:
                                    with self._thread_lock:
                                        self.logger.log_detail(
                                            "skip",
                                            f"Step {node.step_num} skipped by trigger_rule={node.trigger_rule}",
                                            {"step_num": node.step_num, "step_id": sid},
                                        )
                                self.log(
                                    f"⏭ Step {node.step_num} ({sid}) skipped by trigger rule"
                                )
                            continue
                        if decision.met is None:
                            continue

                        ready.append(sid)

                    if ready:
                        ready.sort(
                            key=lambda step_id: (-(nodes[step_id].priority or 0), nodes[step_id].step_num)
                        )

                    # Consume ready tasks by capacity constraints.
                    for sid in ready:
                        if states[sid] not in {TaskInstanceState.SCHEDULED, TaskInstanceState.UP_FOR_RETRY}:
                            continue

                        node = nodes[sid]
                        attempt = attempts.get(sid, 0) + 1
                        deferrable_check = (
                            self._build_defer_check(node, step_id=sid, attempt=attempt)
                            if node.deferrable
                            else None
                        )

                        if deferrable_check is not None:
                            check_fn, timeout_secs, poll_interval = deferrable_check
                            self._emit_step_start(node, sid, try_number=attempt)
                            task_id = self._triggerer.submit(
                                step_id=sid,
                                check_fn=check_fn,
                                timeout=timeout_secs,
                                poll_interval=poll_interval,
                            )
                            self._deferred_events[sid] = _DeferredEvent(task_id=task_id, started_at=time.time())
                            states[sid] = TaskInstanceState.DEFERRED
                            attempts[sid] = attempt
                            scheduled_this_round = True
                            changed = True
                            continue

                        if len(running) >= effective_workers:
                            continue

                        if not self._pool_manager.try_acquire(node.pool):
                            continue

                        self._emit_step_start(node, sid, try_number=attempt)
                        states[sid] = TaskInstanceState.RUNNING
                        attempts[sid] = attempt
                        running_future = thread_pool.submit(
                            self._run_single_step_with_state,
                            node.step_num,
                            node.step,
                            step_id=sid,
                            try_number=attempt,
                            track_checkpoint=False,
                            execution_timeout=node.execution_timeout,
                            emit_events=False,
                        )
                        running[running_future] = (sid, attempt)
                        scheduled_this_round = True
                        changed = True

                    if all(self._step_is_terminal(state) for state in states.values()):
                        break

                    if not running and not self._deferred_events and not scheduled_this_round and not changed:
                        unresolved = [
                            sid
                            for sid, state in states.items()
                            if state not in FINISHED_STATES
                        ]
                        if unresolved:
                            pending_retry = [
                                sid
                                for sid in unresolved
                                if states[sid] == TaskInstanceState.UP_FOR_RETRY
                            ]
                            if pending_retry:
                                next_retry = min(
                                    (retry_ready_at.get(sid, 0.0) for sid in pending_retry),
                                    default=0.0,
                                )
                                if next_retry > now:
                                    time.sleep(min(0.5, max(0.05, next_retry - now)))
                                    continue

                            if all(
                                states[sid] in {TaskInstanceState.SCHEDULED, TaskInstanceState.UP_FOR_RETRY}
                                for sid in unresolved
                            ):
                                self.log(
                                    f"Dependency cycle or unsatisfiable trigger rules: {', '.join(unresolved)}"
                                )
                                return False

                            if pending_retry:
                                time.sleep(0.1)

                return False if fatal else True
        finally:
            self._triggerer.stop()

    def _log_detail(self, event: str, message: str, data: Dict[str, object]) -> None:
        """Safe logger detail helper for composed helpers."""
        if self.logger:
            with self._thread_lock:
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
        self._emit_event(
            "execution_start",
            run_type=self.run_type,
            variables=dict(self.ctx.variables),
            hosts=dict(self.recipe.hosts),
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

    def _extract_provider_metadata(self, step: object) -> Tuple[str, str, Dict[str, Any]]:
        """Extract provider metadata from either ProviderStep or provider-control DSL fallback."""
        provider = str(getattr(step, "provider", "")).strip()
        operation = str(getattr(step, "operation", "")).strip()
        params = getattr(step, "params", None)

        if not provider and getattr(step, "command", "") == "provider":
            raw = str(getattr(step, "raw", "")).strip()
            if raw.startswith("provider "):
                remain = raw[len("provider "):].strip()
                op_text, _, json_text = remain.partition(" ")
                if "." in op_text:
                    provider, operation = [part.strip() for part in op_text.split(".", 1)]
                else:
                    if op_text:
                        provider = op_text
                if json_text:
                    try:
                        parsed_params = json.loads(json_text)
                        if isinstance(parsed_params, dict):
                            params = parsed_params
                    except Exception:
                        params = None

        provider = provider.lower()
        operation = operation.lower()
        if not isinstance(params, dict):
            params = {}
        return provider, operation, params

    def _normalize_provider_timeout(self, value: Any, *, allow_zero: bool = True) -> Optional[int]:
        """Normalize provider timeout values."""
        if value is None:
            return 0 if allow_zero else None

        if isinstance(value, bool):
            value = int(value)
        if isinstance(value, (int, float)):
            timeout = int(value)
            if timeout < 0:
                return None
            if timeout == 0:
                return 0 if allow_zero else None
            return timeout

        text = str(value).strip()
        if not text:
            return 0 if allow_zero else None

        try:
            timeout = self._parse_duration(text)
        except Exception:
            return None

        if timeout < 0:
            return None
        if timeout == 0:
            return 0 if allow_zero else None
        return timeout

    def _positive_provider_timeout(
        self,
        value: Any,
        *,
        default: int = 300,
    ) -> int:
        """Normalize timeout values and always return a positive integer."""
        timeout = self._normalize_provider_timeout(value, allow_zero=False)
        if timeout is None or timeout <= 0:
            return default
        return timeout

    def _provider_host(self, value: Any) -> str:
        """Resolve provider host shorthand."""
        host = str(value).strip() if value is not None else ""
        if not host:
            return "local"
        if host.startswith("@"):
            return self._resolve_host(host)
        return self._resolve_host(f"@{host}")

    def _exec_provider(self, step) -> tuple[bool, str]:
        """Execute provider style step."""
        provider, operation, params = self._extract_provider_metadata(step)
        if not provider:
            return False, "Provider step missing provider name"
        if not operation:
            return False, f"Provider {provider} missing operation"

        if provider == "shell" and operation in {"run", "execute", "exec", "command"}:
            return self._exec_provider_shell(params)
        if provider == "bash" and operation in {
            "run",
            "execute",
            "exec",
            "command",
            "bash",
        }:
            return self._exec_provider_shell(params)
        if provider == "python" and operation in {
            "run",
            "exec",
            "execute",
            "python",
        }:
            return self._exec_provider_python(params)
        if provider in {"bash", "python"} and operation in {
            "local",
            "local_run",
        }:
            return self._exec_provider_shell(params)
        if provider == "cloud":
            storage_params = dict(params)
            storage_name = str(
                storage_params.get("storage")
                or storage_params.get("cloud")
                or storage_params.get("bucket")
                or storage_params.get("name")
                or ""
            ).strip()
            if not storage_name:
                return False, "Provider cloud requires 'storage' (or 'cloud'/'bucket' alias)"
            storage_params["storage"] = storage_name.lstrip("@")

            if operation in {"upload", "put", "write", "publish", "send"}:
                return self._exec_provider_storage_upload(storage_params)
            if operation in {"download", "get", "fetch", "retrieve"}:
                return self._exec_provider_storage_download(storage_params)
            if operation in {"list", "ls", "list_files"}:
                return self._exec_provider_storage_list(storage_params)
            if operation in {"exists", "check", "test"}:
                return self._exec_provider_storage_exists(storage_params)
            if operation in {"read", "read_text", "cat"}:
                return self._exec_provider_storage_read_text(storage_params)
            if operation in {"info", "stat"}:
                return self._exec_provider_storage_info(storage_params)
            if operation in {"wait", "wait_for", "wait_for_key"}:
                return self._exec_provider_storage_wait(storage_params)
            if operation == "mkdir":
                return self._exec_provider_storage_mkdir(storage_params)
            if operation in {"delete", "remove", "rm"}:
                return self._exec_provider_storage_delete(storage_params)
            if operation in {"rename", "move", "mv"}:
                return self._exec_provider_storage_rename(storage_params)
            if operation == "transfer":
                return self._exec_provider_transfer(storage_params)
            return False, f"Unsupported cloud operation: {provider}.{operation}"
        if provider == "http" and operation in {
            "request",
            "get",
            "post",
            "put",
            "delete",
            "head",
            "patch",
            "options",
            "request_json",
            "json_request",
            "json",
        }:
            mapped = dict(params)
            if operation in {"request_json", "json_request", "json"}:
                if "body" not in mapped and "json_body" in mapped:
                    mapped["body"] = mapped["json_body"]
                if "method" not in mapped:
                    mapped["method"] = "POST"
            elif operation != "request" and "method" not in mapped:
                mapped["method"] = operation.upper()
            return self._exec_provider_http_request(mapped)
        if provider == "http" and operation in {
            "wait_for_status",
            "wait_status",
            "wait_for_response",
            "http_sensor",
            "sensor",
            "wait",
        }:
            return self._exec_provider_http_wait(params)
        if provider == "http" and operation in {"http"}:
            mapped = dict(params)
            if "method" not in mapped:
                mapped["method"] = "GET"
            return self._exec_provider_http_request(mapped)
        if provider in {"util", "utils"} and operation == "hf_download":
            return self._exec_provider_hf_download(params)
        if provider in {"util", "utils"} and operation == "fetch_exchange_rates":
            return self._exec_provider_fetch_exchange_rates(params)
        if provider in {"util", "utils"} and operation == "calculate_cost":
            return self._exec_provider_calculate_cost(params)
        if provider == "util" and operation == "wait_condition":
            return self._exec_provider_wait_condition(params)
        if provider == "sqlite" and operation in {
            "query",
            "select",
            "read",
        }:
            return self._exec_provider_sqlite_query(params)
        if provider == "sqlite" and operation in {
            "exec",
            "execute",
            "run",
        }:
            return self._exec_provider_sqlite_exec(params)
        if provider == "sqlite" and operation in {
            "script",
        }:
            return self._exec_provider_sqlite_script(params)
        if provider == "util" and operation == "ssh_command":
            return self._exec_provider_ssh_command(params)
        if provider == "util" and operation == "uv_run":
            return self._exec_provider_uv_run(params)
        if provider == "storage" and operation == "test":
            return self._exec_provider_storage_test(params)
        if provider == "storage" and operation in {"list", "ls"}:
            return self._exec_provider_storage_list(params)
        if provider == "storage" and operation in {"exists", "check", "test"}:
            return self._exec_provider_storage_exists(params)
        if provider == "storage" and operation in {"info", "stat"}:
            return self._exec_provider_storage_info(params)
        if provider == "storage" and operation in {"read_text", "read", "cat"}:
            return self._exec_provider_storage_read_text(params)
        if provider == "storage" and operation == "wait":
            return self._exec_provider_storage_wait(params)
        if provider == "storage" and operation == "mkdir":
            return self._exec_provider_storage_mkdir(params)
        if provider == "storage" and operation == "delete":
            return self._exec_provider_storage_delete(params)
        if provider == "storage" and operation == "rename":
            return self._exec_provider_storage_rename(params)
        if provider == "storage" and operation in {"copy", "sync", "move"}:
            return self._exec_provider_transfer(params)
        if provider == "storage" and operation == "upload":
            return self._exec_provider_storage_upload(params)
        if provider == "storage" and operation == "download":
            return self._exec_provider_storage_download(params)
        if provider in {"transfer", "storage"} and operation in {"copy", "cp", "sync", "move", "mirror"}:
            return self._exec_provider_transfer(params)
        if provider == "util" and operation == "set_var":
            return self._exec_provider_set_var(params)
        step_task_id = str(getattr(step, "id", "")).strip()
        if provider == "util" and operation == "xcom_push":
            mapped = dict(params)
            if step_task_id and "task_id" not in mapped:
                mapped["task_id"] = step_task_id
            return self._exec_provider_xcom_push(mapped)
        if provider == "util" and operation == "xcom_pull":
            mapped = dict(params)
            if step_task_id and "task_id" not in mapped:
                mapped["task_id"] = step_task_id
            return self._exec_provider_xcom_pull(mapped)
        if provider in {
            "util",
            "email",
            "webhook",
            "slack",
            "telegram",
            "discord",
        } and operation in {"notice", "notify", "send", "send_notice", "send_notification"}:
            return self._exec_provider_notice(params)
        if provider == "util" and operation == "branch":
            return self._exec_provider_branch(params)
        if provider == "util" and operation in {"short_circuit", "skip_if", "skip_if_not"}:
            return self._exec_provider_short_circuit(params)
        if provider == "util" and operation == "fail":
            return self._exec_provider_fail(params)
        if provider == "util" and operation == "latest_only":
            return self._exec_provider_latest_only(params)
        if provider == "util" and operation == "sleep":
            return self._cmd_sleep([str(params.get("duration", params.get("duration_secs", "0")))])
        if provider in {"shell", "bash"} and operation in {
            "local",
            "local_run",
        }:
            return self._exec_provider_shell(params)
        if provider == "util" and operation in {"empty", "noop"}:
            return self._exec_provider_empty(params)
        if provider in {"vast", "vasts"} and operation in {"start", "stop", "pick", "wait", "cost"}:
            return self._exec_provider_vast(operation, params)
        if provider == "git" and operation == "clone":
            return self._exec_provider_git_clone(params)
        if provider == "git" and operation == "pull":
            return self._exec_provider_git_pull(params)
        if provider == "host" and operation in {"test", "connect", "verify"}:
            return self._exec_provider_host_test(params)
        if provider == "util" and operation == "assert":
            return self._exec_provider_assert(params)
        if provider == "util" and operation == "get_value":
            return self._exec_provider_get_value(params)
        if provider == "util" and operation == "set_env":
            return self._exec_provider_set_env(params)
        if provider == "util" and operation == "wait_file":
            return self._exec_provider_wait_for_file(params)
        if provider == "util" and operation == "wait_port":
            return self._exec_provider_wait_for_port(params)
        if provider in {
            "email",
            "webhook",
            "slack",
            "telegram",
            "discord",
        } and operation in {
            "send",
            "notice",
        }:
            return self._exec_provider_notice(params)

        return False, f"Unsupported provider step: {provider}.{operation}"

    def _coerce_http_headers(self, headers: Any) -> tuple[bool, str, Dict[str, str]]:
        if headers is None:
            return True, "", {}
        if not isinstance(headers, dict):
            return False, "Provider http headers must be an object", {}
        parsed: Dict[str, str] = {}
        for key, value in headers.items():
            if key is None:
                continue
            parsed[str(key)] = "" if value is None else str(value)
        return True, "", parsed

    def _coerce_http_statuses(self, value: Any) -> tuple[bool, str, List[int]]:
        if value is None:
            return True, "", [200]
        if isinstance(value, bool):
            return False, f"Invalid expected_status: {value!r}", []
        if isinstance(value, int):
            return True, "", [int(value)]
        if isinstance(value, (list, tuple, set)):
            parsed: List[int] = []
            for item in value:
                if isinstance(item, bool):
                    continue
                try:
                    parsed.append(int(item))
                except Exception:
                    return False, f"Invalid expected_status value: {item!r}", []
            if not parsed:
                return False, "expected_status cannot be empty", []
            return True, "", parsed
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return False, "expected_status cannot be empty", []
            parsed = []
            for part in text.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    parsed.append(int(part))
                except Exception:
                    return False, f"Invalid expected_status value: {part!r}", []
            if not parsed:
                return False, f"Invalid expected_status value: {value!r}", []
            return True, "", parsed
        try:
            return True, "", [int(value)]
        except Exception:
            return False, f"Invalid expected_status: {value!r}", []

    def _decode_http_payload(self, payload: Any, *, headers: Optional[Any] = None) -> str:
        if not payload:
            return ""
        if not isinstance(payload, (bytes, bytearray)):
            try:
                return str(payload)
            except Exception:
                return ""
        encoding = "utf-8"
        if headers is not None:
            try:
                content_type = headers.get_content_charset()
                if content_type:
                    encoding = content_type
            except Exception:
                pass
        try:
            return bytes(payload).decode(encoding, errors="replace")
        except Exception:
            return bytes(payload).decode("utf-8", errors="replace")

    def _http_request_once(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes],
        timeout: Optional[int],
    ) -> tuple[bool, Optional[int], str, str]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                payload = response.read()
                return True, status, self._decode_http_payload(payload, headers=response.headers), ""
        except urllib.error.HTTPError as exc:
            status = exc.code if isinstance(exc.code, int) else None
            payload = exc.read() if hasattr(exc, "read") else b""
            error_text = self._decode_http_payload(payload, headers=getattr(exc, "headers", None))
            return False, status, error_text, str(exc)
        except urllib.error.URLError as exc:
            return False, None, "", str(exc)
        except Exception as exc:
            return False, None, "", str(exc)

    def _exec_provider_http_request(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute HTTP request via provider."""
        if not isinstance(params, dict):
            return False, "Provider http.params must be an object"

        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", "")).strip()
        if not url:
            return False, "Provider http.request requires 'url'"

        timeout = self._normalize_provider_timeout(params.get("timeout"), allow_zero=True)
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        run_timeout = None if timeout in (None, 0) else timeout

        header_ok, header_error, headers = self._coerce_http_headers(params.get("headers"))
        if not header_ok:
            return False, header_error

        body = params.get("body")
        data: Optional[bytes] = None
        if body is not None:
            if isinstance(body, (dict, list)):
                try:
                    data = json.dumps(body).encode("utf-8")
                    headers.setdefault("Content-Type", "application/json")
                except Exception:
                    data = str(body).encode("utf-8")
            elif isinstance(body, bytes):
                data = body
            else:
                data = str(body).encode("utf-8")

        ok, status, body_text, error_text = self._http_request_once(
            method=method,
            url=url,
            headers=headers,
            body=data,
            timeout=run_timeout,
        )
        if ok:
            capture_var = params.get("capture_var")
            if capture_var and isinstance(capture_var, str):
                self.ctx.variables[capture_var] = body_text

            if self.logger:
                self.logger.log_detail("http_request", f"{method} {url}", {
                    "method": method,
                    "url": url,
                    "status": status,
                    "response_len": len(body_text),
                })
            return True, body_text[:500]
        if status is not None:
            message = (
                f"HTTP request failed (status {status}): {body_text[:500] or error_text}"
            )
        else:
            message = f"HTTP request failed: {error_text}"
        return False, message

    def _exec_provider_http_wait(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for an HTTP endpoint condition."""
        if not isinstance(params, dict):
            return False, "Provider http.params must be an object"

        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", "")).strip()
        if not url:
            return False, "Provider http.wait_for_status requires 'url'"

        header_ok, header_error, headers = self._coerce_http_headers(params.get("headers"))
        if not header_ok:
            return False, header_error

        status_ok, status_error, expected_statuses = self._coerce_http_statuses(params.get("expected_status", 200))
        if not status_ok:
            return False, status_error
        expected_set = set(expected_statuses)

        expected_text_raw = params.get("expected_text")
        expected_text = None if expected_text_raw is None else str(expected_text_raw)

        request_timeout = self._positive_provider_timeout(
            params.get("request_timeout", params.get("timeout_secs", 10)),
            default=10,
        )
        timeout = self._normalize_provider_timeout(params.get("timeout"), allow_zero=True)
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        poll_interval = self._normalize_provider_timeout(
            params.get("poll_interval", params.get("interval", 5)),
            allow_zero=True,
        )
        if poll_interval is None:
            return False, f"Invalid poll_interval value: {params.get('poll_interval')!r}"
        if poll_interval <= 0:
            poll_interval = 5

        deadline = time.time() + timeout if timeout else 0
        body = params.get("body")
        body_data: Optional[bytes] = None
        if body is not None:
            if isinstance(body, (dict, list)):
                try:
                    body_data = json.dumps(body).encode("utf-8")
                    headers.setdefault("Content-Type", "application/json")
                except Exception:
                    body_data = str(body).encode("utf-8")
            elif isinstance(body, bytes):
                body_data = body
            else:
                body_data = str(body).encode("utf-8")

        last_status: Optional[int] = None
        last_error = "initial"
        while True:
            ok, status, response_text, error_text = self._http_request_once(
                method=method,
                url=url,
                headers=headers,
                body=body_data,
                timeout=request_timeout,
            )
            last_status = status
            if status is None:
                if error_text:
                    last_error = error_text
            elif status in expected_set and (
                expected_text is None or expected_text in response_text
            ):
                capture_var = params.get("capture_var")
                if capture_var and isinstance(capture_var, str):
                    self.ctx.variables[capture_var] = response_text

                if self.logger:
                    self.logger.log_detail("http_wait", f"{method} {url}", {
                        "method": method,
                        "url": url,
                        "status": status,
                        "expected": sorted(expected_set),
                        "response_len": len(response_text),
                    })
                return True, f"HTTP endpoint matched: status={status}"

            if expected_text is not None and expected_text not in response_text:
                if response_text:
                    last_error = f"status={status}, body={response_text[:500]}"

            if timeout and time.time() >= deadline:
                if timeout == 0:
                    return False, f"Timeout waiting for HTTP endpoint: {url}"
                if last_error:
                    return False, f"Timeout waiting for HTTP condition: {last_error}"
                return False, f"Timeout waiting for HTTP condition: status={last_status}"
            if poll_interval > 0:
                time.sleep(poll_interval)

    def _exec_provider_transfer(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute transfer via provider."""

    def _coerce_float(self, value: Any, *, default: float = 0.0) -> float:
        """Normalize float-like values."""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except Exception:
            return default

    def _coerce_int(self, value: Any, *, default: int = 0) -> int:
        """Normalize int-like values."""
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return int(value)
        try:
            return int(str(value).strip())
        except Exception:
            return default

    def _resolve_storage(self, storage_name: Any) -> Optional[Storage]:
        """Resolve storage name to Storage object."""
        from .storage_specs import resolve_storage_reference

        return resolve_storage_reference(
            storage_name,
            named_storages=self._build_transfer_storages(),
        )

    def _storage_local_path(self, storage: Storage, path: str) -> str:
        """Resolve a path within local storage."""
        base_path = str(storage.config.get("path", "")).strip()
        relative = str(path or "").strip().lstrip("/")
        if base_path:
            if not relative:
                return os.path.expanduser(base_path)
            return os.path.join(os.path.expanduser(base_path), relative)
        return os.path.expanduser(relative or ".")

    def _storage_rclone_path(self, storage: Storage, path: str) -> str:
        """Resolve a path for rclone operations."""
        from ..services.transfer_engine import get_rclone_remote_name

        path_text = str(path or "").strip().lstrip("/")
        remote_name = get_rclone_remote_name(storage)

        if storage.type in {StorageType.R2, StorageType.B2}:
            bucket = str(storage.config.get("bucket", "")).strip().strip("/")
            if bucket:
                if not path_text:
                    path_text = bucket
                elif not path_text.startswith(f"{bucket}/") and path_text != bucket:
                    path_text = f"{bucket}/{path_text}"

        return f"{remote_name}:{path_text}"

    def _exec_storage_rclone(
        self,
        storage: Storage,
        args: List[str],
        *,
        timeout: int = 300,
    ) -> tuple[bool, str]:
        """Execute a storage command through rclone."""
        from ..services.transfer_engine import build_rclone_env, check_rclone_available

        if not check_rclone_available():
            return False, "rclone is required. Install with: brew install rclone"
        if storage.type == StorageType.S3:
            return False, "Amazon S3 support has been removed. Please migrate to R2 or B2."

        env = os.environ.copy()
        env.update(build_rclone_env(storage))
        try:
            result = subprocess.run(
                ["rclone", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except FileNotFoundError:
            return False, "rclone command not found. Install with: brew install rclone"
        except subprocess.TimeoutExpired:
            return False, f"rclone command timed out after {timeout}s"
        except Exception as exc:
            return False, str(exc)

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        message = output or error
        if result.returncode == 0:
            return True, message or "storage operation completed"
        return False, message or "storage operation failed"

    def _exec_provider_hf_download(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Download model files from HuggingFace."""
        if not isinstance(params, dict):
            return False, "Provider util.hf_download params must be an object"

        repo_id = self._interpolate(str(params.get("repo_id", ""))).strip()
        if not repo_id:
            return False, "Provider util.hf_download requires 'repo_id'"

        local_dir = self._interpolate(str(params.get("local_dir", ""))).strip()
        revision = self._interpolate(str(params.get("revision", ""))).strip()
        token = self._interpolate(str(params.get("token", ""))).strip()
        filename = self._interpolate(str(params.get("filename", ""))).strip()
        filenames = params.get("filenames")

        command = f"huggingface-cli download {shlex.quote(repo_id)}"
        if revision:
            command += f" --revision {shlex.quote(revision)}"
        if local_dir:
            command += f" --local-dir {shlex.quote(local_dir)}"
        if token:
            command += f" --token {shlex.quote(token)}"
        if filename:
            command += f" --filename {shlex.quote(filename)}"
        elif isinstance(filenames, (list, tuple, set)):
            for item in filenames:
                file_name = self._interpolate(str(item)).strip()
                if file_name:
                    command += f" --filename {shlex.quote(file_name)}"

        return self._exec_provider_shell(
            {
                "command": command,
                "host": self._provider_host(params.get("host", "local")),
            }
        )

    def _exec_provider_fetch_exchange_rates(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Fetch exchange rates from provider."""
        if not isinstance(params, dict):
            return False, "Provider util.fetch_exchange_rates params must be an object"

        from ..services.pricing import fetch_exchange_rates, load_pricing_settings, save_pricing_settings

        try:
            rates = fetch_exchange_rates()
            settings = load_pricing_settings()
            settings.exchange_rates = rates
            save_pricing_settings(settings)
            for currency, rate in rates.rates.items():
                self.ctx.variables[f"rate_{str(currency).lower()}"] = str(rate)
            self.ctx.variables["exchange_rate_base"] = rates.base
            self.ctx.variables["exchange_rate_updated_at"] = rates.updated_at
            return True, f"Fetched {len(rates.rates)} exchange rates"
        except Exception as exc:
            return False, str(exc)

    def _exec_provider_calculate_cost(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Estimate cost from provider config."""
        if not isinstance(params, dict):
            return False, "Provider util.calculate_cost params must be an object"

        from ..services.pricing import load_pricing_settings, calculate_host_cost, format_currency
        try:
            from ..services.vast_api import get_vast_client
        except Exception:
            get_vast_client = None

        settings = load_pricing_settings()
        currency = str(params.get("currency", settings.display_currency)).upper() or settings.display_currency
        rates = settings.exchange_rates
        is_vast = self._coerce_bool(params.get("vast", False), default=False)
        host_id = self._interpolate(str(params.get("host_id", ""))).strip()
        gpu_hourly_usd = self._coerce_float(params.get("gpu_hourly_usd", 0), default=0.0)
        storage_gb = self._coerce_float(params.get("storage_gb", 0), default=0.0)

        if is_vast:
            if get_vast_client is None:
                return False, "Vast client unavailable"
            try:
                client = get_vast_client()
                instances = client.list_instances()
            except Exception as exc:
                return False, f"Failed to list Vast instances: {exc}"

            total_per_hour = 0.0
            matched = 0
            for inst in instances:
                hourly = getattr(inst, "dph_total", 0.0)
                if not hourly:
                    continue
                cost = calculate_host_cost(
                    host_id=str(inst.id),
                    gpu_hourly_usd=float(hourly),
                    host_name=getattr(inst, "gpu_name", ""),
                    source="vast_api",
                )
                total_per_hour += cost.total_per_hour_usd
                matched += 1
                self.ctx.variables[f"vast_{inst.id}_cost_per_hour_usd"] = str(cost.total_per_hour_usd)

            if not matched:
                return False, "No active Vast instance found for calculate_cost"

            self.ctx.variables["total_cost_per_hour_usd"] = str(total_per_hour)
            self.ctx.variables["total_cost_per_day_usd"] = str(total_per_hour * 24)
            self.ctx.variables["total_cost_per_month_usd"] = str(total_per_hour * 24 * 30)
            converted = rates.convert(total_per_hour, "USD", currency)
            self.ctx.variables[f"total_cost_per_hour_{currency.lower()}"] = str(converted)
            return True, f"{format_currency(converted, currency)}/hr"

        if not host_id and gpu_hourly_usd <= 0:
            return False, "Provider util.calculate_cost requires 'host_id' or 'gpu_hourly_usd' when vast=False"

        cost = calculate_host_cost(
            host_id=host_id or "manual",
            gpu_hourly_usd=gpu_hourly_usd,
            storage_gb=storage_gb,
            host_name=host_id or "",
            source="manual",
        )
        converted = rates.convert(cost.total_per_hour_usd, "USD", currency)
        self.ctx.variables["host_cost_per_hour_usd"] = str(cost.total_per_hour_usd)
        self.ctx.variables["host_cost_per_day_usd"] = str(cost.total_per_day_usd)
        self.ctx.variables["host_cost_per_month_usd"] = str(cost.total_per_month_usd)
        self.ctx.variables[f"host_cost_per_hour_{currency.lower()}"] = str(converted)
        return True, f"{format_currency(converted, currency)}/hr"

    def _sqlite_db_path(self, database: Any) -> str:
        """Resolve SQLite database path used by sqlite provider."""
        raw_db = str(database).strip() if database is not None else ""
        if raw_db:
            return os.path.expanduser(raw_db)
        return str(CONFIG_DIR / "runtime.db")

    def _normalize_sqlite_bindings(self, bindings: Any) -> Any:
        """Normalize SQL bind parameters."""
        if bindings is None:
            return ()

        if isinstance(bindings, (list, tuple, dict)):
            return bindings

        if isinstance(bindings, str):
            text = bindings.strip()
            if not text:
                return ()
            try:
                parsed = json.loads(text)
            except Exception:
                return (text,)
            return self._normalize_sqlite_bindings(parsed)

        return (bindings,)

    def _runtime_dag_id(self) -> str:
        """Resolve dag_id used by runtime metadata tables."""
        path = str(self.recipe_path or "").strip()
        if path:
            return path
        name = str(getattr(self.recipe, "name", "")).strip()
        if name:
            return name
        return "unknown_dag"

    def _ensure_xcom_schema(self, conn: Any) -> None:
        """Ensure XCom sqlite schema exists."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS xcom (
                dag_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                map_index INTEGER NOT NULL DEFAULT 0,
                key TEXT NOT NULL,
                value TEXT,
                created_at TEXT NOT NULL,
                execution_date TEXT,
                PRIMARY KEY (dag_id, task_id, run_id, map_index, key)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_xcom_run_task_key ON xcom (run_id, dag_id, task_id, key)"
        )

    def _exec_provider_xcom_push(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Push one value into runtime sqlite xcom table."""
        if not isinstance(params, dict):
            return False, "Provider util.xcom_push params must be an object"

        key = str(params.get("key", "")).strip()
        if not key:
            return False, "Provider util.xcom_push requires 'key'"

        source_var = str(params.get("from_var", params.get("var", ""))).strip()
        raw_value = params.get("value")
        if raw_value is None and source_var:
            raw_value = self.ctx.variables.get(source_var, params.get("default", ""))
        if raw_value is None:
            raw_value = params.get("default", "")

        if isinstance(raw_value, (dict, list)):
            value_text = json.dumps(raw_value, ensure_ascii=False)
        elif raw_value is None:
            value_text = ""
        else:
            value_text = str(raw_value)

        dag_id = str(params.get("dag_id", "")).strip() or self._runtime_dag_id()
        run_id = str(params.get("run_id", "")).strip() or self.ctx.job_id
        task_id = (
            str(params.get("task_id", "")).strip()
            or self._current_step_id()
            or "anonymous"
        )
        map_index = self._coerce_int(params.get("map_index", 0), default=0)
        db = self._sqlite_db_path(params.get("database", params.get("sqlite_db")))
        created_at = datetime.now().isoformat()
        execution_date = str(params.get("execution_date", created_at)).strip() or created_at

        import sqlite3

        try:
            with sqlite3.connect(os.path.expanduser(db)) as conn:
                self._ensure_xcom_schema(conn)
                conn.execute(
                    """
                    INSERT INTO xcom (
                        dag_id, task_id, run_id, map_index, key, value, created_at, execution_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dag_id, task_id, run_id, map_index, key) DO UPDATE SET
                        value=excluded.value,
                        created_at=excluded.created_at,
                        execution_date=excluded.execution_date
                    """,
                    (
                        dag_id,
                        task_id,
                        run_id,
                        map_index,
                        key,
                        value_text,
                        created_at,
                        execution_date,
                    ),
                )
                conn.commit()
        except Exception as exc:
            return False, f"xcom push failed: {exc}"

        output_var = params.get("output_var")
        if output_var:
            self.ctx.variables[str(output_var)] = value_text

        self._emit_event(
            "xcom_push",
            step_num=self._current_step_num() or None,
            step_id=task_id,
            task_id=task_id,
            dag_id=dag_id,
            run_id=run_id,
            key=key,
            value=value_text,
            map_index=map_index,
            execution_date=execution_date,
            try_number=self._current_try_number(),
        )
        return True, f"xcom pushed: key={key}, task_id={task_id}, run_id={run_id}"

    def _exec_provider_xcom_pull(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Pull one value from runtime sqlite xcom table."""
        if not isinstance(params, dict):
            return False, "Provider util.xcom_pull params must be an object"

        key = str(params.get("key", "")).strip()
        if not key:
            return False, "Provider util.xcom_pull requires 'key'"

        dag_id = str(params.get("dag_id", "")).strip() or self._runtime_dag_id()
        run_id = str(params.get("run_id", "")).strip() or self.ctx.job_id
        include_prior_dates = self._coerce_bool(
            params.get("include_prior_dates", False),
            default=False,
        )
        db = self._sqlite_db_path(params.get("database", params.get("sqlite_db")))

        task_ids_raw = params.get("task_ids", params.get("task_id"))
        task_ids: List[str] = []
        if task_ids_raw is not None:
            if isinstance(task_ids_raw, (list, tuple, set)):
                task_ids = [str(item).strip() for item in task_ids_raw if str(item).strip()]
            elif isinstance(task_ids_raw, str):
                task_ids = [item.strip() for item in task_ids_raw.split(",") if item.strip()]
            else:
                task_ids = [str(task_ids_raw).strip()]

        map_index_raw = params.get("map_index", None)
        use_map_index = map_index_raw is not None and str(map_index_raw).strip() != ""
        map_index = self._coerce_int(map_index_raw, default=0)

        import sqlite3

        row: Optional[Any] = None
        try:
            with sqlite3.connect(os.path.expanduser(db)) as conn:
                self._ensure_xcom_schema(conn)
                conn.row_factory = sqlite3.Row
                query = "SELECT value, task_id, run_id FROM xcom WHERE dag_id = ? AND key = ?"
                query_params: List[Any] = [dag_id, key]
                if task_ids:
                    placeholders = ",".join(["?"] * len(task_ids))
                    query += f" AND task_id IN ({placeholders})"
                    query_params.extend(task_ids)
                if not include_prior_dates:
                    query += " AND run_id = ?"
                    query_params.append(run_id)
                if use_map_index:
                    query += " AND map_index = ?"
                    query_params.append(map_index)
                query += " ORDER BY created_at DESC LIMIT 1"
                row = conn.execute(query, query_params).fetchone()
        except Exception as exc:
            return False, f"xcom pull failed: {exc}"

        output_var = params.get("output_var")
        if row is None:
            default_value = params.get("default", None)
            if default_value is None:
                if output_var:
                    self.ctx.variables[str(output_var)] = ""
                return True, f"xcom not found for key={key}"
            if isinstance(default_value, (dict, list)):
                value_text = json.dumps(default_value, ensure_ascii=False)
            else:
                value_text = str(default_value)
            if output_var:
                self.ctx.variables[str(output_var)] = value_text
            return True, value_text

        value_text = str(row["value"] or "")
        decode_json = self._coerce_bool(
            params.get("decode_json", params.get("as_json", False)),
            default=False,
        )
        result_text = value_text
        if decode_json and value_text:
            try:
                parsed = json.loads(value_text)
                if isinstance(parsed, (dict, list)):
                    result_text = json.dumps(parsed, ensure_ascii=False)
                elif parsed is None:
                    result_text = ""
                else:
                    result_text = str(parsed)
            except Exception:
                result_text = value_text

        if output_var:
            self.ctx.variables[str(output_var)] = result_text
        return True, result_text

    def _exec_provider_sqlite_query(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Run a SQLite query and serialize results."""
        if not isinstance(params, dict):
            return False, "Provider sqlite.query params must be an object"

        query = str(params.get("sql", params.get("query", ""))).strip()
        if not query:
            return False, "Provider sqlite.query requires 'sql' or 'query'"

        db = self._sqlite_db_path(params.get("database"))
        mode = str(params.get("mode", "all")).strip().lower()
        bindings = self._normalize_sqlite_bindings(params.get("params"))
        output_var = params.get("output_var")

        import sqlite3

        try:
            with sqlite3.connect(os.path.expanduser(db)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, bindings) if bindings else conn.execute(query)
                rows = cursor.fetchall()
        except Exception as exc:
            return False, f"sqlite query failed: {exc}"

        if mode in {"first", "one", "fetchone"}:
            if not rows:
                payload = None
            else:
                payload = dict(rows[0])
        elif mode in {"scalar", "value"}:
            if not rows or len(rows[0].keys()) == 0:
                payload = None
            else:
                payload = rows[0][0]
        else:
            payload = [dict(row) for row in rows]

        if output_var:
            if isinstance(payload, (dict, list)):
                self.ctx.variables[str(output_var)] = json.dumps(payload, ensure_ascii=False)
            else:
                self.ctx.variables[str(output_var)] = "" if payload is None else str(payload)

        if payload is None:
            return True, "sqlite query returned no rows"
        if isinstance(payload, (dict, list)):
            return True, json.dumps(payload, ensure_ascii=False)
        return True, str(payload)

    def _exec_provider_sqlite_exec(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Run write-like SQLite SQL."""
        if not isinstance(params, dict):
            return False, "Provider sqlite.exec params must be an object"

        sql = str(params.get("sql", params.get("query", ""))).strip()
        if not sql:
            return False, "Provider sqlite.exec requires 'sql' (or 'query')"

        db = self._sqlite_db_path(params.get("database"))
        bindings = self._normalize_sqlite_bindings(params.get("params"))
        output_var = params.get("output_var")

        import sqlite3

        try:
            with sqlite3.connect(os.path.expanduser(db)) as conn:
                cursor = conn.execute(sql, bindings) if bindings else conn.execute(sql)
                conn.commit()
        except Exception as exc:
            return False, f"sqlite execute failed: {exc}"

        if output_var is not None:
            self.ctx.variables[str(output_var)] = str(getattr(cursor, "rowcount", 0))

        return True, f"sqlite execute ok: rowcount={getattr(cursor, 'rowcount', 0)}"

    def _exec_provider_sqlite_script(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute a multi-statement SQLite script."""
        if not isinstance(params, dict):
            return False, "Provider sqlite.script params must be an object"

        script = str(params.get("script", "")).strip()
        if not script:
            return False, "Provider sqlite.script requires 'script'"

        db = self._sqlite_db_path(params.get("database"))
        output_var = params.get("output_var")

        import sqlite3

        try:
            with sqlite3.connect(os.path.expanduser(db)) as conn:
                conn.executescript(script)
                conn.commit()
        except Exception as exc:
            return False, f"sqlite script failed: {exc}"

        if output_var is not None:
            self.ctx.variables[str(output_var)] = "ok"

        return True, "sqlite script executed"

    def _exec_provider_storage_test(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Test whether a storage path exists."""
        if not isinstance(params, dict):
            return False, "Provider storage.test params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.test requires storage id"
        path = str(params.get("path", "")).strip()

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            return (
                True,
                f"Storage path exists: {target}",
            ) if os.path.exists(target) else (False, f"Storage path not found: {target}")

        return self._exec_storage_rclone(storage, ["ls", self._storage_rclone_path(storage, path)])

    def _exec_provider_storage_exists(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Alias storage.exists."""
        return self._exec_provider_storage_test(params)

    def _exec_provider_storage_wait(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for storage path existence or non-existence."""
        if not isinstance(params, dict):
            return False, "Provider storage.wait params must be an object"

        storage_name = str(params.get("storage") or params.get("storage_id") or "").strip()
        if not storage_name:
            return False, "Provider storage.wait requires storage id"
        storage_name = storage_name[1:] if storage_name.startswith("@") else storage_name

        path = self._interpolate(str(params.get("path", params.get("destination", "")))).strip()
        if not path:
            return False, "Provider storage.wait requires path"

        should_exist = self._coerce_bool(params.get("exists", True), default=True)
        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            allow_zero=True,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        poll_interval = self._normalize_provider_timeout(
            params.get("poll_interval", params.get("interval", params.get("poll_interval_secs", 5))),
            allow_zero=True,
        )
        if poll_interval is None or poll_interval <= 0:
            poll_interval = 5

        deadline = time.time() + timeout if timeout else 0
        while True:
            ok, _ = self._exec_provider_storage_exists(
                {"storage": storage_name, "path": path}
            )
            if should_exist and ok:
                return True, f"Storage path exists: {storage_name}:{path}"
            if not should_exist and not ok:
                return True, f"Storage path not found as expected: {storage_name}:{path}"

            if timeout and time.time() >= deadline:
                return False, f"Timeout waiting storage path: {storage_name}:{path}"

            time.sleep(poll_interval)

    def _exec_provider_storage_info(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Show storage object metadata."""
        if not isinstance(params, dict):
            return False, "Provider storage.info params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.info requires storage id"
        path = str(params.get("path", "")).strip()

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.exists(target):
                return False, f"Storage path not found: {target}"
            try:
                stat = os.stat(target)
                info = {
                    "path": target,
                    "size": int(stat.st_size),
                    "is_dir": os.path.isdir(target),
                    "mtime": int(stat.st_mtime),
                    "mode": oct(stat.st_mode & 0o777),
                }
                return True, json.dumps(info, ensure_ascii=False)
            except Exception as exc:
                return False, str(exc)

        return self._exec_storage_rclone(
            storage,
            ["lsjson", self._storage_rclone_path(storage, path)],
        )

    def _exec_provider_storage_read_text(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Read text content from storage."""
        if not isinstance(params, dict):
            return False, "Provider storage.read_text params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.read_text requires storage id"
        path = str(params.get("path", "")).strip()
        if not path:
            return False, "Provider storage.read_text requires non-empty path"
        max_chars = self._coerce_float(params.get("max_chars", params.get("max_bytes", 8192)))
        if max_chars <= 0:
            max_chars = 8192
        max_chars = int(max_chars)

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.isfile(target):
                return False, f"Storage file not found: {target}"
            try:
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    return True, f.read(max_chars)
            except Exception as exc:
                return False, str(exc)

        ok, output = self._exec_storage_rclone(
            storage,
            ["cat", self._storage_rclone_path(storage, path)],
        )
        if not ok:
            return False, output
        return True, output[:max_chars]

    def _exec_provider_wait_condition(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait until a condition is satisfied."""
        if not isinstance(params, dict):
            return False, "Provider util.wait_condition params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.wait_condition requires 'condition'"

        host = self._provider_host(params.get("host", "local"))
        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            allow_zero=True,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"
        poll_interval = self._normalize_provider_timeout(
            params.get("poll_interval", params.get("interval", params.get("poll_interval_secs", 5))),
            allow_zero=True,
        )
        if poll_interval is None:
            return False, f"Invalid poll_interval value: {params.get('poll_interval')!r}"
        if poll_interval <= 0:
            poll_interval = 5
        capture_output = self._coerce_bool(params.get("capture", False), default=False)

        deadline = time.time() + timeout if timeout else 0
        while True:
            ok, message = self._eval_condition(condition, host=host)
            if ok:
                if capture_output:
                    return True, message
                return True, f"Condition met: {condition}"

            if timeout and time.time() >= deadline:
                return False, f"Timeout waiting for condition: {condition}"

            time.sleep(poll_interval)

    def _exec_provider_branch(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Evaluate a condition and store branch result variable."""
        if not isinstance(params, dict):
            return False, "Provider util.branch params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.branch requires 'condition'"

        true_value = str(params.get("true_value", "true"))
        false_value = str(params.get("false_value", "false"))
        variable = str(params.get("variable", "branch")).strip()
        host = self._provider_host(params.get("host", "local"))

        ok, message = self._eval_condition(condition, host=host)
        branch_value = true_value if ok else false_value
        if variable:
            self.ctx.variables[variable] = branch_value

        return True, f"branch={branch_value}; {message}"

    def _exec_provider_short_circuit(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Fail step when condition check does not pass."""
        if not isinstance(params, dict):
            return False, "Provider util.short_circuit params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.short_circuit requires 'condition'"

        host = self._provider_host(params.get("host", "local"))
        invert = self._coerce_bool(params.get("invert", params.get("not", False)), default=False)
        message = str(params.get("message", "condition not met"))

        ok, detail = self._eval_condition(condition, host=host)
        if invert:
            ok = not ok
        if ok:
            return True, f"Condition passed: {detail}"
        return False, f"Condition blocked: {message}"

    def _exec_provider_latest_only(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Keep only the newest run for this recipe when sqlite state is available."""
        if not isinstance(params, dict):
            return False, "Provider util.latest_only params must be an object"

        enabled = self._coerce_bool(params.get("enabled", True), default=True)
        if not enabled:
            return True, "latest_only disabled"

        message = str(params.get("message", "Skipped by latest_only"))
        fail_if_unknown = self._coerce_bool(params.get("fail_if_unknown", False), default=False)

        from ..constants import CONFIG_DIR
        from pathlib import Path
        import sqlite3

        sqlite_db = str(params.get("sqlite_db", "")).strip()
        if not sqlite_db:
            sqlite_db = str(Path(CONFIG_DIR) / "runtime.db")

        db_path = Path(sqlite_db)
        if not db_path.exists():
            if fail_if_unknown:
                return False, "latest_only cannot determine state: runtime sqlite DB not found"
            return (
                True,
                "latest_only passed (runtime sqlite DB not found; install sqlite callback or set fail_if_unknown=False)",
            )

        current_run_id = self.ctx.job_id
        recipe_name = self.recipe.name
        dag_id = self.recipe_path or self.recipe.name
        current_started_at = self.ctx.start_time.isoformat() if self.ctx.start_time else ""
        if not current_started_at:
            if fail_if_unknown:
                return False, "latest_only cannot determine current run start time"
            return True, "latest_only passed (current run start time unavailable)"

        try:
            conn = sqlite3.connect(str(db_path))
            try:
                row = None

                has_recipe_runs = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recipe_runs'"
                ).fetchone()
                if has_recipe_runs:
                    row = conn.execute(
                        """
                        SELECT started_at
                        FROM recipe_runs
                        WHERE recipe_name = ?
                          AND run_id != ?
                          AND started_at > ?
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        (recipe_name, current_run_id, current_started_at),
                    ).fetchone()

                if row is None:
                    has_dag_run = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dag_run'"
                    ).fetchone()
                    if has_dag_run:
                        row = conn.execute(
                            """
                            SELECT start_date
                            FROM dag_run
                            WHERE dag_id = ?
                              AND run_id != ?
                              AND start_date > ?
                            ORDER BY start_date DESC
                            LIMIT 1
                            """,
                            (dag_id, current_run_id, current_started_at),
                        ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            if fail_if_unknown:
                return False, f"latest_only sqlite check failed: {exc}"
            return True, f"latest_only passed (sqlite check failed: {exc})"

        if row:
            return False, message
        return True, "latest_only check passed"

    def _exec_provider_fail(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Explicitly fail this step."""
        if not isinstance(params, dict):
            return False, "Provider util.fail params must be an object"

        message = str(params.get("message", "Failed by recipe.")).strip()
        if not message:
            message = "Failed by recipe."

        exit_code = params.get("exit_code", 1)
        try:
            exit_code = int(exit_code)
        except Exception:
            exit_code = 1
        if exit_code == 0:
            exit_code = 1

        return False, f"{message} (exit_code={exit_code})"

    def _exec_provider_ssh_command(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute SSH-style command from provider."""
        if not isinstance(params, dict):
            return False, "Provider util.ssh_command params must be an object"

        command = str(params.get("command", "")).strip()
        if not command:
            return False, "Provider util.ssh_command requires 'command'"

        return self._exec_provider_shell(
            {
                "command": command,
                "host": self._provider_host(params.get("host", "local")),
                "timeout": self._normalize_provider_timeout(
                    params.get("timeout", params.get("timeout_secs", 0)),
                    allow_zero=True,
                ),
            }
        )

    def _exec_provider_uv_run(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Run commands using uv."""
        if not isinstance(params, dict):
            return False, "Provider util.uv_run params must be an object"

        command = self._interpolate(str(params.get("command", ""))).strip()
        if not command:
            return False, "Provider util.uv_run requires 'command'"

        packages = params.get("packages", params.get("with", []))
        if isinstance(packages, str):
            packages = [packages]

        uv_parts = ["uv", "run"]
        for pkg in packages or []:
            if not str(pkg).strip():
                continue
            uv_parts.append("--with")
            uv_parts.append(str(pkg))
        uv_parts.append(command)

        timeout = self._normalize_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 0)),
            allow_zero=False,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"

        return self._exec_provider_shell(
            {
                "command": " ".join(shlex.quote(part) for part in uv_parts),
                "host": self._provider_host(params.get("host", "local")),
                "timeout": timeout,
            }
        )

    def _exec_provider_storage_list(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """List storage path entries."""
        if not isinstance(params, dict):
            return False, "Provider storage.list params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.list requires storage id"
        path = str(params.get("path", "")).strip()
        recursive = self._coerce_bool(params.get("recursive", False), default=False)

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.exists(target):
                return False, f"Storage path not found: {target}"
            if not os.path.isdir(target):
                return False, f"Storage path is not a directory: {target}"

            if recursive:
                output_lines = []
                for root, dirs, files in os.walk(target):
                    rel = os.path.relpath(root, target)
                    for name in sorted(dirs + files):
                        output_lines.append(os.path.join(rel, name) if rel != "." else name)
                return True, "\n".join(output_lines)

            return True, "\n".join(sorted(os.listdir(target)))

        args = ["lsf"]
        if recursive:
            args.append("-R")
        args.append(self._storage_rclone_path(storage, path))
        return self._exec_storage_rclone(storage, args)

    def _exec_provider_storage_mkdir(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Create storage directory."""
        if not isinstance(params, dict):
            return False, "Provider storage.mkdir params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.mkdir requires storage id"
        path = str(params.get("path", "")).strip()
        if not path:
            return False, "Provider storage.mkdir requires non-empty path"

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            try:
                os.makedirs(target, exist_ok=True)
                return True, f"Directory created: {target}"
            except Exception as exc:
                return False, str(exc)

        return self._exec_storage_rclone(storage, ["mkdir", self._storage_rclone_path(storage, path)])

    def _exec_provider_storage_delete(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Delete storage object."""
        if not isinstance(params, dict):
            return False, "Provider storage.delete params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.delete requires storage id"
        path = str(params.get("path", "")).strip()
        if not path:
            return False, "Provider storage.delete requires non-empty path"

        recursive = self._coerce_bool(params.get("recursive", False), default=False)

        if storage.type == StorageType.LOCAL:
            target = self._storage_local_path(storage, path)
            if not os.path.exists(target):
                return False, f"Storage path not found: {target}"
            try:
                if os.path.isdir(target):
                    if not recursive:
                        return False, f"Storage path is directory: {target} (set recursive=True to remove)"
                    shutil.rmtree(target)
                    return True, f"Directory deleted: {target}"
                os.remove(target)
                return True, f"File deleted: {target}"
            except Exception as exc:
                return False, str(exc)

        op = "purge" if recursive else "delete"
        return self._exec_storage_rclone(storage, [op, self._storage_rclone_path(storage, path)])

    def _exec_provider_storage_rename(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Rename within storage."""
        if not isinstance(params, dict):
            return False, "Provider storage.rename params must be an object"

        storage = self._resolve_storage(params.get("storage"))
        if storage is None:
            return False, "Provider storage.rename requires storage id"
        source = str(params.get("source", "")).strip()
        destination = str(params.get("destination", "")).strip()
        if not source or not destination:
            return False, "Provider storage.rename requires source and destination"

        if storage.type == StorageType.LOCAL:
            source_path = self._storage_local_path(storage, source)
            destination_path = self._storage_local_path(storage, destination)
            try:
                os.rename(source_path, destination_path)
                return True, f"Renamed {source_path} -> {destination_path}"
            except Exception as exc:
                return False, str(exc)

        return self._exec_storage_rclone(
            storage,
            [
                "moveto",
                self._storage_rclone_path(storage, source),
                self._storage_rclone_path(storage, destination),
            ],
        )

    def _exec_provider_storage_upload(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Upload local path to storage path."""
        if not isinstance(params, dict):
            return False, "Provider storage.upload params must be an object"

        storage_name = str(params.get("storage") or params.get("storage_id") or "").strip()
        if not storage_name:
            return False, "Provider storage.upload requires 'storage'"
        storage_name = storage_name[1:] if storage_name.startswith("@") else storage_name

        source = self._interpolate(str(params.get("source", "")).strip())
        if not source:
            return False, "Provider storage.upload requires 'source'"

        destination = self._interpolate(str(
            params.get("destination", params.get("path", ""))
        )).strip()
        if not destination:
            # Default to storage root if not provided.
            destination = "/"

        return self._exec_provider_transfer(
            {
                "source": source,
                "destination": f"@{storage_name}:{destination}",
                "operation": str(params.get("operation", "copy")).strip().lower(),
                "delete": False,
            }
        )

    def _exec_provider_storage_download(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Download storage path to local path."""
        if not isinstance(params, dict):
            return False, "Provider storage.download params must be an object"

        storage_name = str(params.get("storage") or params.get("storage_id") or "").strip()
        if not storage_name:
            return False, "Provider storage.download requires 'storage'"
        storage_name = storage_name[1:] if storage_name.startswith("@") else storage_name

        source = self._interpolate(str(params.get("source", params.get("path", ""))).strip())
        if not source:
            return False, "Provider storage.download requires 'source'"

        destination = self._interpolate(str(params.get("destination", "")).strip())
        if not destination:
            return False, "Provider storage.download requires 'destination'"

        return self._exec_provider_transfer(
            {
                "source": f"@{storage_name}:{source}",
                "destination": destination,
                "operation": str(params.get("operation", "copy")).strip().lower(),
                "delete": False,
            }
        )

    def _exec_provider_shell(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute shell command in provider mode."""
        if not isinstance(params, dict):
            return False, "Provider shell params must be an object"

        command = str(params.get("command", "")).strip()
        if not command:
            return False, "Provider shell requires 'command'"
        command = self._interpolate(command)

        timeout = self._normalize_provider_timeout(params.get("timeout"), allow_zero=True)
        run_timeout = None if timeout in (None, 0) else timeout
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout')!r}"

        cwd = params.get("cwd")
        if cwd is not None:
            cwd = os.path.expanduser(str(cwd))

        shell_env = dict(os.environ)
        env = params.get("env")
        if env is not None:
            if not isinstance(env, dict):
                return False, "Provider shell env must be an object"
            for key, value in env.items():
                shell_env[str(key)] = str(value)

        host = self._provider_host(params.get("host", "local"))
        run_command = command
        if host != "local" and cwd is not None:
            run_command = f"cd {shlex.quote(str(cwd))} && ({command})"

        start = datetime.now()
        try:
            if host == "local":
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    env=shell_env,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                )
            else:
                ssh_args = _build_ssh_args(host, command=run_command, tty=False)
                result = subprocess.run(
                    ssh_args,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                )

            duration_ms = int((datetime.now() - start).total_seconds() * 1000)
            output = result.stdout or result.stderr

            if self.logger:
                self.logger.log_ssh(
                    host,
                    command,
                    result.returncode,
                    result.stdout,
                    result.stderr,
                    duration_ms,
                )
        except subprocess.TimeoutExpired:
            return False, f"Shell command timed out after {timeout}s"
        except Exception as exc:
            return False, str(exc)

        capture_var = params.get("capture_var")
        if capture_var:
            if isinstance(capture_var, str):
                self.ctx.variables[capture_var] = output

        return result.returncode == 0, output or (f"Shell command completed ({duration_ms}ms)" if result.returncode == 0 else "")

    def _eval_condition(self, condition: str, *, host: str = "local") -> tuple[bool, str]:
        """Evaluate simple condition expression."""
        condition = str(condition).strip()
        if not condition:
            return False, "Condition is empty"

        if condition.startswith("var:"):
            body = condition[4:]
            if "==" in body:
                name, expected = [item.strip() for item in body.split("==", 1)]
                actual = str(self.ctx.variables.get(name, ""))
                return actual == expected, f"{name} == {expected}"
            return bool(self.ctx.variables.get(body, "")), f"var:{body} is set"

        if condition.startswith("env:"):
            body = condition[4:]
            if "==" in body:
                name, expected = [item.strip() for item in body.split("==", 1)]
                actual = os.environ.get(name, "")
                return str(actual) == expected, f"{name} == {expected}"
            return bool(os.environ.get(body, "")), f"env:{body} is set"

        if condition.startswith("file_exists:"):
            path = self._interpolate(condition[11:].strip())
            if host == "local":
                return os.path.exists(os.path.expanduser(path)), f"file_exists:{path}"
            ok, output = self._exec_provider_shell(
                {
                    "command": f"test -e {shlex.quote(path)} && echo exists",
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok and "exists" in output, f"file_exists:{path}"

        if condition.startswith("file_contains:"):
            remain = condition[len("file_contains:") :].strip()
            path, sep, expected = remain.partition(":")
            path = self._interpolate(path.strip())
            expected = expected.strip()
            if not path:
                return False, "Condition file path is empty"
            if not sep or not expected:
                return False, "Condition file_contains requires pattern"

            if host == "local":
                target = os.path.expanduser(path)
                if not os.path.isfile(target):
                    return False, f"File not found: {target}"
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    return expected in f.read(), f"file_contains:{path} has expected text"

            ok, output = self._exec_provider_shell(
                {
                    "command": (
                        f"test -f {shlex.quote(path)} && "
                        f"grep -qF {shlex.quote(expected)} {shlex.quote(path)} && echo found"
                    ),
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok and "found" in output, f"file_contains:{path} has expected text"

        if condition.startswith("storage_exists:"):
            raw_spec = condition[len("storage_exists:") :].strip()
            if not raw_spec:
                return False, "Condition storage_exists is empty"
            storage_ref, _, path = raw_spec.partition(":")
            storage_ref = storage_ref.strip()
            if not storage_ref:
                return False, "Condition storage_exists missing storage id"
            storage_ref = storage_ref[1:] if storage_ref.startswith("@") else storage_ref
            path = self._interpolate(path.strip())
            if path is None:
                path = ""
            ok, _ = self._exec_provider_storage_exists({"storage": storage_ref, "path": path})
            return ok, f"storage_exists:{storage_ref}:{path}"

        if condition.startswith("command:"):
            command = self._interpolate(condition[8:].strip())
            if not command:
                return False, "Condition command is empty"
            ok, _ = self._exec_provider_shell(
                {
                    "command": command,
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok, f"command:{command}"

        if condition.startswith("command_output:"):
            remain = condition[len("command_output:") :].strip()
            command, sep, expected = remain.partition(":")
            command = self._interpolate(command.strip())
            expected = expected.strip()
            if not command:
                return False, "Condition command_output command is empty"
            if not sep or not expected:
                return False, "Condition command_output requires expected text"
            ok, output = self._exec_provider_shell(
                {
                    "command": command,
                    "host": host,
                    "timeout": 30,
                }
            )
            return ok and (expected in output), f"command_output:{command} contains text"

        if condition.startswith("host_online:"):
            host_ref = condition[11:].strip()
            if not host_ref:
                return False, "Condition host_online requires host"
            target = self._provider_host(host_ref)
            if target == "local":
                return True, "local is online"
            return self._verify_ssh_connection(target, timeout=10), f"host_online:{target}"

        return False, f"Unsupported condition: {condition!r}"

    def _exec_provider_git_clone(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Clone a git repository via provider."""
        if not isinstance(params, dict):
            return False, "Provider git.clone params must be an object"

        repo_url = self._interpolate(str(params.get("repo_url", params.get("repo", "")))).strip()
        destination = self._interpolate(str(params.get("destination", params.get("path", "")))).strip()
        if not repo_url:
            return False, "Provider git.clone requires 'repo_url' (or 'repo')"

        command = "git clone"
        branch = str(params.get("branch", "")).strip()
        if branch:
            command += f" -b {shlex.quote(branch)}"
        depth = params.get("depth")
        if depth is not None and str(depth).strip():
            command += f" --depth {shlex.quote(str(depth).strip())}"
        command += f" {shlex.quote(repo_url)}"
        if destination:
            command += f" {shlex.quote(destination)}"

        host = self._provider_host(params.get("host", "local"))
        return self._exec_provider_shell(
            {
                "command": command,
                "host": host,
                "timeout": self._positive_provider_timeout(params.get("timeout", params.get("timeout_secs", 0)), default=300),
            }
        )

    def _exec_provider_git_pull(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Pull git repository changes via provider."""
        if not isinstance(params, dict):
            return False, "Provider git.pull params must be an object"

        directory = self._interpolate(str(params.get("directory", "."))).strip() or "."
        remote = self._interpolate(str(params.get("remote", "origin"))).strip() or "origin"
        branch = self._interpolate(str(params.get("branch", ""))).strip()
        command = "git -C " + shlex.quote(directory) + f" pull {shlex.quote(remote)}"
        if branch:
            command += f" {shlex.quote(branch)}"

        host = self._provider_host(params.get("host", "local"))
        return self._exec_provider_shell(
            {
                "command": command,
                "host": host,
                "timeout": self._positive_provider_timeout(params.get("timeout", params.get("timeout_secs", 0)), default=300),
            }
        )

    def _exec_provider_host_test(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Test SSH connectivity for a host."""
        if not isinstance(params, dict):
            return False, "Provider host.test params must be an object"

        host = self._provider_host(params.get("host"))
        if host == "local":
            return True, "Host local is local"

        timeout = self._positive_provider_timeout(params.get("timeout", params.get("timeout_secs", 10)), default=10)
        ok = self._verify_ssh_connection(host, timeout=timeout)
        if not ok:
            return False, f"Failed to connect to host {host}"

        capture_var = params.get("capture_var")
        if capture_var:
            self.ctx.variables[str(capture_var)] = "1"
        return True, f"Host {host} is reachable"

    def _exec_provider_assert(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Assert a condition via provider."""
        if not isinstance(params, dict):
            return False, "Provider util.assert params must be an object"

        condition = self._interpolate(str(params.get("condition", ""))).strip()
        if not condition:
            return False, "Provider util.assert requires 'condition'"
        message = str(params.get("message", "Assertion failed"))

        host = self._provider_host(params.get("host", "local"))

        if condition.startswith("var:"):
            expr = condition[4:].strip()
            if "==" in expr:
                var_name, expected = [item.strip() for item in expr.split("==", 1)]
                actual = self.ctx.variables.get(var_name, "")
                if actual == expected:
                    return True, f"Assertion passed: {var_name} == {expected}"
                return False, f"{message}: {var_name} expected {expected}, got {actual}"

            if self.ctx.variables.get(expr, ""):
                return True, f"Assertion passed: {expr} is set"
            return False, f"{message}: {expr} is not set"

        if condition.startswith("file:") or condition.startswith("file_exists:"):
            filepath = self._interpolate(condition.split(":", 1)[1]).strip()
            if host == "local":
                if os.path.exists(os.path.expanduser(filepath)):
                    return True, f"Assertion passed: file exists {filepath}"
                return False, f"{message}: file not found {filepath}"

            ok, output = self._exec_provider_shell(
                {
                    "command": f"test -f {shlex.quote(filepath)} && echo exists",
                    "host": host,
                    "timeout": 30,
                }
            )
            if ok and "exists" in output:
                return True, f"Assertion passed: file exists {filepath}"
            return False, f"{message}: file not found {filepath}"

        if condition.startswith("command:"):
            cmd = self._interpolate(condition.split(":", 1)[1]).strip()
            ok, output = self._exec_provider_shell(
                {
                    "command": cmd,
                    "host": host,
                    "timeout": self._positive_provider_timeout(
                        params.get("timeout", params.get("timeout_secs", 0)),
                        default=120,
                    ),
                }
            )
            if ok:
                return True, f"Assertion passed: {output}".strip() or "Assertion passed"
            return False, f"{message}: command failed"

        return False, f"Unsupported assertion condition: {condition!r}"

    def _exec_provider_get_value(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Get value from env/secret/var/command and store in recipe variable."""
        if not isinstance(params, dict):
            return False, "Provider util.get_value params must be an object"

        target = str(params.get("target", params.get("name", ""))).strip()
        if not target:
            return False, "Provider util.get_value requires 'target' (or 'name')"
        source = self._interpolate(str(params.get("source", ""))).strip()
        if not source:
            return False, "Provider util.get_value requires 'source'"
        default_value = str(params.get("default", ""))

        if source.startswith("env:"):
            value = os.environ.get(source[4:], default_value)
        elif source.startswith("secret:"):
            value = self.secrets.get(source[7:]) or default_value
        elif source.startswith("var:"):
            value = self.ctx.variables.get(source[4:], default_value)
        elif source.startswith("command:"):
            host = self._provider_host(params.get("host", "local"))
            command = self._interpolate(source[8:]).strip()
            ok, output = self._exec_provider_shell(
                {
                    "command": command,
                    "host": host,
                    "timeout": self._positive_provider_timeout(params.get("timeout", params.get("timeout_secs", 0)), default=120),
                }
            )
            if not ok:
                return False, f"Failed to get command output: {command}"
            value = output.strip()
        else:
            return False, f"Unsupported source: {source!r}"

        self.ctx.variables[target] = "" if value is None else str(value)
        return True, f"Set {target} from {source}"

    def _exec_provider_set_env(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Set environment variable."""
        if not isinstance(params, dict):
            return False, "Provider util.set_env params must be an object"

        name = str(params.get("name", "")).strip()
        if not name:
            return False, "Provider util.set_env requires 'name'"
        value = self._interpolate(str(params.get("value", "")))
        os.environ[name] = value
        return True, f"Set environment variable {name}"

    def _exec_provider_wait_for_file(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for a file to exist."""
        if not isinstance(params, dict):
            return False, "Provider util.wait_for_file params must be an object"

        path = self._interpolate(str(params.get("path", ""))).strip()
        if not path:
            return False, "Provider util.wait_for_file requires 'path'"
        host = self._provider_host(params.get("host", "local"))
        timeout = self._positive_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            default=300,
        )
        poll_interval = self._positive_provider_timeout(
            params.get("poll_interval", params.get("interval", 5)),
            default=5,
        )

        end_time = time.time() + timeout
        check_cmd = f"test -f {shlex.quote(path)} && echo exists"
        while time.time() < end_time:
            if host == "local":
                if os.path.exists(os.path.expanduser(path)):
                    return True, f"File found: {path}"
            else:
                ok, output = self._exec_provider_shell(
                    {
                        "command": check_cmd,
                        "host": host,
                        "timeout": self._positive_provider_timeout(
                            poll_interval,
                            default=5,
                        ),
                    }
                )
                if ok and "exists" in output:
                    return True, f"File found: {path}"
            time.sleep(poll_interval)
        return False, f"Timeout waiting for file: {path}"

    def _exec_provider_wait_for_port(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Wait for a TCP port to open."""
        if not isinstance(params, dict):
            return False, "Provider util.wait_for_port params must be an object"

        port_raw = params.get("port")
        if str(port_raw).strip() == "":
            return False, "Provider util.wait_for_port requires 'port'"
        try:
            port = int(port_raw)
        except Exception:
            return False, "Provider util.wait_for_port port must be integer"
        if port <= 0:
            return False, "Provider util.wait_for_port port must be positive"

        host = self._provider_host(params.get("host", "local"))
        check_host = self._interpolate(str(params.get("host_name", "localhost"))).strip() or "localhost"
        timeout = self._positive_provider_timeout(
            params.get("timeout", params.get("timeout_secs", 300)),
            default=300,
        )
        poll_interval = self._positive_provider_timeout(
            params.get("poll_interval", params.get("interval", 5)),
            default=5,
        )

        end_time = time.time() + timeout
        while time.time() < end_time:
            if host == "local":
                try:
                    with socket.create_connection((check_host, port), timeout=2):
                        return True, f"Port {port} is open on {check_host}"
                except OSError:
                    pass
            else:
                # Check from remote host context using target's shell.
                remote_host = _host_from_ssh_spec(host)
                host_to_check = remote_host.hostname or check_host
                ok, output = self._exec_provider_shell(
                    {
                        "command": f"nc -z {shlex.quote(host_to_check)} {int(port)} 2>/dev/null && echo open || true",
                        "host": host,
                        "timeout": self._positive_provider_timeout(
                            poll_interval,
                            default=5,
                        ),
                    }
                )
                if ok and "open" in output:
                    return True, f"Port {port} is open on {host_to_check}"

            time.sleep(poll_interval)

        return False, f"Timeout waiting for port {port} on {check_host}"

    def _exec_provider_transfer(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute transfer via provider."""
        if not isinstance(params, dict):
            return False, "Provider transfer params must be an object"

        source = str(params.get("source", "")).strip()
        destination = str(params.get("destination", "")).strip()
        if not source or not destination:
            return False, "Provider transfer requires 'source' and 'destination'"

        operation = str(params.get("operation", "copy")).strip().lower()
        if operation in {"move", "mirror"}:
            operation = "sync"
            delete = self._coerce_bool(params.get("delete", True), default=True)
        else:
            delete = self._coerce_bool(params.get("delete", False), default=False)

        exclude = self._coerce_list(params.get("exclude", params.get("exclude_patterns", None)))

        return self.transfer_helper.transfer(
            source,
            destination,
            delete=delete,
            exclude=exclude,
            operation=operation,
        )

    def _exec_provider_set_var(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Set recipe variable via provider."""
        if not isinstance(params, dict):
            return False, "Provider util.set_var params must be an object"

        name = params.get("name")
        if not name:
            return False, "Provider util.set_var requires 'name'"
        value = params.get("value", "")
        value_text = "" if value is None else str(value)
        self.ctx.variables[str(name)] = value_text
        return True, f"Set {name}={value_text}"

    def _exec_provider_notice(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Send notification via provider."""
        if not self.notify_enabled:
            return True, "Notification skipped (notifications.enabled=false)"

        if not isinstance(params, dict):
            return False, "Provider util.notice params must be an object"

        message = str(params.get("message", "")).strip()
        if not message:
            message = str(params.get("body", params.get("text", ""))).strip()
        if not message and isinstance(params.get("content"), str):
            message = str(params.get("content", "")).strip()
        if not message:
            return False, "Provider util.notice requires 'message'"

        title = str(params.get("title", params.get("subject", self.notify_app_name))).strip()
        try:
            channels = normalize_channels(
                params.get("channels"),
                self.notify_default_channels,
            )
        except ValueError as exc:
            return False, str(exc)

        level = str(params.get("level", "info"))
        webhook_url = str(
            params.get("webhook") or params.get("webhook_url") or self.notify_default_webhook or ""
        ).strip() or None
        command = str(
            params.get("command") or params.get("cmd") or self.notify_default_command or ""
        ).strip() or None

        timeout = self._normalize_provider_timeout(
            params.get("timeout_secs", params.get("timeout", self.notify_default_timeout)),
            allow_zero=True,
        )
        if timeout is None:
            return False, f"Invalid timeout value: {params.get('timeout_secs')!r}"
        if timeout <= 0:
            timeout = self.notify_default_timeout

        try:
            fail_on_error = parse_bool(params.get("fail_on_error", self.notify_default_fail_on_error))
        except ValueError as exc:
            return False, str(exc)
        ok, summary = self.notifier.notify(
            title=title,
            message=message,
            level=level,
            channels=channels,
            webhook_url=webhook_url,
            command=command,
            timeout_secs=timeout,
            fail_on_error=fail_on_error,
        )
        return ok, summary

    def _exec_provider_empty(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """No-op provider operation."""
        return True, "noop"

    def _exec_provider_python(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute Python code as a provider operation."""
        if not isinstance(params, dict):
            return False, "Provider python params must be an object"

        command = self._interpolate(str(params.get("command", ""))).strip()
        code = self._interpolate(str(params.get("code", ""))).strip()
        script = self._interpolate(str(params.get("script", ""))).strip()

        if not any((command, code, script)):
            return False, "Provider python requires 'command', 'code', or 'script'"

        if code:
            shell_command = "python - <<'PY'\n" + code + "\nPY"
        elif script:
            shell_command = f"python {shlex.quote(script)}"
        else:
            shell_command = f"python -c {shlex.quote(command)}"

        shell_params = dict(params)
        shell_params["command"] = shell_command
        return self._exec_provider_shell(shell_params)

    def _exec_provider_vast(self, operation: str, params: Dict[str, Any]) -> tuple[bool, str]:
        """Execute vast provider operations."""
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return False, "Provider vast params must be an object"

        args: List[str] = []
        op = operation.strip().lower()

        if "args" in params and isinstance(params.get("args"), (list, tuple)):
            args.extend([str(item).strip() for item in params["args"] if str(item).strip()])
        else:
            direct_id = self._interpolate(str(params.get("instance_id", params.get("id", "")))).strip()
            if direct_id:
                args.append(direct_id)

        if op == "pick":
            host_name = self._interpolate(str(params.get("host", params.get("host_name", "")))).strip()
            if host_name.startswith("@"):
                host_name = host_name[1:]
            if host_name:
                args.append(host_name)

        if op == "wait":
            if direct_timeout := str(params.get("timeout", "")).strip():
                args.append(f"timeout={self._interpolate(direct_timeout)}")
            if direct_poll := str(params.get("poll", params.get("poll_interval", ""))).strip():
                args.append(f"poll={self._interpolate(direct_poll)}")
            if "stop_on_fail" in params:
                stop_on_fail = self._interpolate(str(params.get("stop_on_fail")))
                args.append(f"stop_on_fail={stop_on_fail}")

        if op == "pick":
            mapping = {
                "gpu_name": "gpu_name",
                "gpu": "gpu_name",
                "num_gpus": "num_gpus",
                "gpus": "num_gpus",
                "min_gpu_ram": "min_gpu_ram",
                "min_vram_gb": "min_gpu_ram",
                "max_dph": "max_dph",
                "max_price": "max_dph",
                "limit": "limit",
                "skip_if_set": "skip_if_set",
            }
            for key, param_key in mapping.items():
                value = params.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                args.append(f"{param_key}={self._interpolate(text)}")

        if op == "cost":
            # cost currently only uses positional instance id
            pass

        if op not in {"start", "stop", "pick", "wait", "cost"}:
            return False, f"Unsupported vast operation: {operation!r}"

        if op == "start":
            return self._cmd_vast_start(args)
        if op == "stop":
            return self._cmd_vast_stop(args)
        if op == "pick":
            return self._cmd_vast_pick(args)
        if op == "wait":
            return self._cmd_vast_wait(args)
        return self._cmd_vast_cost(args)

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

    def _exec_execute(self, step: RecipeStepModel) -> tuple[bool, str]:
        """Execute command via helper."""
        return self.execute_helper.exec_execute(step)

    def _tmux_send_keys(self, host: str, session: str, text: str) -> None:
        """Send tmux keys via helper."""
        self.execute_helper.tmux_send_keys(host, session, text)

    def _tmux_wait_for_signal(self, host: str, signal: str, timeout: int = 1) -> bool:
        """Wait for tmux signal via helper."""
        return self.execute_helper.tmux_wait_for_signal(host, signal, timeout=timeout)

    def _exec_transfer(self, step: RecipeStepModel) -> tuple[bool, str]:
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

    def _exec_wait(self, step: RecipeStepModel) -> tuple[bool, str]:
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
        """Interpolate variables and secrets.

        Runs multiple passes so chained references resolve correctly:
        e.g. var TOKEN = ${secret:GH}  →  var REPO = https://${TOKEN}@…
        """
        for _ in range(10):  # guard against infinite loops
            prev = text

            # Handle ${VAR} and ${secret:NAME}
            def replace_braced(match):
                ref = match.group(1)
                if ref.startswith('secret:'):
                    secret_name = ref[7:]
                    return self.secrets.get(secret_name) or ""
                return self.ctx.variables.get(ref, match.group(0))

            text = re.sub(r'\$\{([^}]+)\}', replace_braced, text)

            # Handle $VAR shorthand in control command arguments
            def replace_simple(match):
                name = match.group(1)
                return self.ctx.variables.get(name, match.group(0))

            text = re.sub(r'\$(\w+)', replace_simple, text)

            if text == prev:
                break  # nothing changed, fully resolved

        return text

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
    executor_name: str = "sequential",
    executor_kwargs: Optional[Dict[str, object]] = None,
    callbacks: Optional[Sequence[str]] = None,
    callback_sinks: Optional[Sequence] = None,
    run_type: str = "manual",
) -> bool:
    """
    Load and execute a recipe file.

    Args:
        path: Path to a Python recipe file
        log_callback: Optional log callback
        host_overrides: Override hosts for fresh runs (not supported with resume)
        var_overrides: Override variables (e.g., {"MODEL": "mistral"})
        resume: If True, try to resume from saved checkpoint
        executor_name: Execution strategy (`sequential`, `thread_pool`)
        executor_kwargs: Executor-specific options (e.g., {"max_workers": 4})
        callbacks: Callback sink names (`console`, `sqlite`)
        run_type: Execution type (`manual`/`scheduled`)

    Returns:
        True if successful
    """
    from ..runtime import build_sinks, get_executor

    path = os.path.abspath(os.path.expanduser(path))
    if not path.endswith(".py"):
        raise ValueError("run_recipe only supports Python recipe files (.py)")
    if resume and host_overrides:
        raise ValueError("Host overrides are not supported when resuming a Python recipe")

    from ..pyrecipe import load_python_recipe

    recipe = load_python_recipe(path)
    merged_kwargs = dict(recipe.executor_kwargs or {})
    merged_kwargs.update(executor_kwargs or {})
    executor_kwargs = merged_kwargs
    if callbacks is None and recipe.callbacks:
        callbacks = recipe.callbacks
    if recipe.executor:
        executor_name = recipe.executor
    if not callbacks:
        callbacks = ["console", "sqlite"]

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
            else:
                recipe.hosts[name] = value

    sinks: List = list(callback_sinks or [])
    if callbacks:
        sinks.extend(build_sinks(callbacks, log_callback=log_callback or print))

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

    return get_executor(executor_name, **executor_kwargs).execute(lambda: executor.execute(resume_from=resume_from))
