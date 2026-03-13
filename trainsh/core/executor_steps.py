"""Step metadata and callback helpers for the DSL executor."""

from __future__ import annotations

import concurrent.futures
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..pyrecipe.models import ProviderStep
from .executor_runtime import _StepNode
from .recipe_models import RecipeStepModel
from .task_state import FINISHED_STATES, TaskInstanceState


class ExecutorStepRuntimeMixin:
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
