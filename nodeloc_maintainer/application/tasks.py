from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskOptions:
    mode: str = "dry_run"
    force_reading: bool = False
    max_accounts: int | None = None
    reading_minutes: float | None = None
    topics_per_account: int | None = None
    rounds: int = 1


@dataclass(frozen=True)
class TaskEvent:
    id: int
    ts: float
    level: str
    type: str
    account_name: str | None
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskRun:
    id: str
    status: str
    options: TaskOptions
    started_at: float
    finished_at: float | None = None
    events: list[TaskEvent] = field(default_factory=list)
    report_path: str | None = None
    error: str | None = None


class TaskBusyError(RuntimeError):
    pass


class TaskSupervisor:
    """Keeps one background maintainer task visible to Web clients."""

    def __init__(self):
        self._lock = threading.RLock()
        self._current: TaskRun | None = None
        self._history: list[TaskRun] = []
        self._next_event_id = 1

    def start(self, options: TaskOptions, runner: Callable[[TaskRun, Callable], str | None]) -> TaskRun:
        with self._lock:
            if self._current and self._current.status == "running":
                raise TaskBusyError("a task is already running")

            task = TaskRun(
                id=uuid.uuid4().hex[:12],
                status="running",
                options=options,
                started_at=time.time(),
            )
            self._current = task
            self._history.insert(0, task)
            self._history = self._history[:20]
            self.add_event(task, "info", "job_started", None, "task started", {"mode": options.mode, "rounds": options.rounds})

        thread = threading.Thread(target=self._run_task, args=(task, runner), daemon=True)
        thread.start()
        return task

    def _run_task(self, task: TaskRun, runner: Callable[[TaskRun, Callable], str | None]) -> None:
        try:
            report_path = runner(task, lambda *args, **kwargs: self.add_event(task, *args, **kwargs))
            with self._lock:
                task.report_path = report_path
                task.status = "succeeded"
                task.finished_at = time.time()
            self.add_event(task, "info", "job_finished", None, "task finished", {"report_path": report_path})
        except Exception as exc:
            with self._lock:
                task.status = "failed"
                task.error = str(exc)
                task.finished_at = time.time()
            self.add_event(task, "error", "job_failed", None, str(exc))

    def add_event(
        self,
        task: TaskRun,
        level: str,
        event_type: str,
        account_name: str | None,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> TaskEvent:
        with self._lock:
            event = TaskEvent(
                id=self._next_event_id,
                ts=time.time(),
                level=level,
                type=event_type,
                account_name=account_name,
                message=message,
                data=data or {},
            )
            self._next_event_id += 1
            task.events.append(event)
            return event

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = self._current
            return {
                "current": serialize_task(current) if current else None,
                "history": [serialize_task(task) for task in self._history[:10]],
            }

    def events_since(self, last_event_id: int = 0) -> list[TaskEvent]:
        with self._lock:
            events: list[TaskEvent] = []
            for task in reversed(self._history):
                events.extend(event for event in task.events if event.id > last_event_id)
            return sorted(events, key=lambda item: item.id)


def serialize_task(task: TaskRun | None) -> dict[str, Any] | None:
    if task is None:
        return None
    return {
        "id": task.id,
        "status": task.status,
        "options": {
            "mode": task.options.mode,
            "force_reading": task.options.force_reading,
            "max_accounts": task.options.max_accounts,
            "reading_minutes": task.options.reading_minutes,
            "topics_per_account": task.options.topics_per_account,
            "rounds": task.options.rounds,
        },
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "report_path": task.report_path,
        "error": task.error,
        "events": [serialize_event(event) for event in task.events[-100:]],
    }


def serialize_event(event: TaskEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "ts": event.ts,
        "level": event.level,
        "type": event.type,
        "account_name": event.account_name,
        "message": event.message,
        "data": event.data,
    }
