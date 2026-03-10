# Minimal in-process triggerer for deferrable wait steps.

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


@dataclass
class TriggerEvent:
    step_id: str
    status: str
    message: str


@dataclass
class _WaitTask:
    task_id: str
    step_id: str
    check_fn: Callable[[], tuple[bool, str]]
    deadline: Optional[float]
    poll_interval: float
    created_at: float = field(default_factory=lambda: time.time())
    next_check_at: float = field(default_factory=lambda: time.time())


class Triggerer:
    """A tiny polling triggerer that re-checks wait conditions asynchronously."""

    def __init__(self, poll_interval: float = 1.0):
        self._poll_interval = max(1.0, float(poll_interval))
        self._tasks: Dict[str, _WaitTask] = {}
        self._tasks_lock = threading.Lock()
        self._events: "queue.Queue[TriggerEvent]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def events(self) -> "queue.Queue[TriggerEvent]":
        return self._events

    def start(self) -> None:
        if self._thread is not None:
            return
        if self._stop.is_set():
            self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="trainsh-triggerer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def submit(self, *, step_id: str, check_fn: Callable[[], tuple[bool, str]], timeout: Optional[float], poll_interval: float) -> str:
        timeout_secs = max(0.0, float(timeout or 0.0))
        deadline = (time.time() + timeout_secs) if timeout_secs > 0 else None
        task_id = str(uuid.uuid4())
        interval = max(1.0, float(poll_interval or self._poll_interval))
        item = _WaitTask(
            task_id=task_id,
            step_id=step_id,
            check_fn=check_fn,
            deadline=deadline,
            poll_interval=interval,
        )
        with self._tasks_lock:
            self._tasks[task_id] = item
        return task_id

    def cancel(self, task_id: str) -> None:
        with self._tasks_lock:
            self._tasks.pop(task_id, None)

    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            due_tasks = []
            with self._tasks_lock:
                for task_id, task in list(self._tasks.items()):
                    if task.next_check_at <= now:
                        due_tasks.append(task_id)
            for task_id in due_tasks:
                with self._tasks_lock:
                    task = self._tasks.get(task_id)
                    if task is None:
                        continue
                try:
                    done, message = task.check_fn()
                except Exception as exc:
                    done, message = False, f"triggerer check failed: {exc}"
                if done:
                    self._events.put(TriggerEvent(task.step_id, "success", message))
                    self.cancel(task_id)
                    continue
                if task.deadline is not None and now >= task.deadline:
                    self._events.put(TriggerEvent(task.step_id, "timeout", message))
                    self.cancel(task_id)
                    continue
                with self._tasks_lock:
                    current = self._tasks.get(task_id)
                    if current is not None:
                        current.next_check_at = now + current.poll_interval

            delay = self._poll_interval
            with self._tasks_lock:
                if self._tasks:
                    next_due = min(task.next_check_at for task in self._tasks.values())
                    delay = max(0.2, min(self._poll_interval, max(0.0, next_due - time.time())))
            if self._stop.wait(delay):
                break
