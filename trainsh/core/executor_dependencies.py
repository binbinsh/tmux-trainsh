"""Dependency-aware scheduling helpers for the DSL executor."""

from __future__ import annotations

import concurrent.futures
import queue
import time
from collections import defaultdict
from typing import Dict, List, Optional

from .executor_runtime import _DeferredEvent, _StepNode
from .task_state import FINISHED_STATES, TaskInstanceState
from .ti_dependencies import DependencyContext


class ExecutorDependencyMixin:
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
                            self._save_checkpoint(node.step_num - 1)
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

                        self._save_checkpoint(node.step_num - 1)
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
