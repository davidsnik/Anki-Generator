"""Shared fair admission of physical API attempts and bounded local subprocesses.

No database transaction or capacity slot is held while waiting. Queued requests
are FIFO within each job and admitted round-robin across eligible jobs. A model
at its limit cannot block another model. Lower live limits drain existing work.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from anki_generator.services.task_options import TaskOptions

Checkpoint = Callable[[], None]
EventCallback = Callable[[dict[str, Any]], None]


@dataclass(eq=False)
class _Request:
    job_id: str
    model: str


@dataclass
class _Pool:
    active: int = 0
    by_job: Counter = field(default_factory=Counter)
    by_model: Counter = field(default_factory=Counter)
    waiting: dict[str, deque[_Request]] = field(default_factory=dict)
    order: deque[str] = field(default_factory=deque)


class GlobalResources:
    def __init__(self, options: TaskOptions | None = None):
        self._options = (options or TaskOptions()).model_copy(deep=True)
        self._condition = threading.Condition()
        self._api = _Pool()
        self._local = _Pool()

    @property
    def max_concurrent_jobs(self) -> int:
        with self._condition:
            return self._options.max_concurrent_jobs

    def configure(self, options: TaskOptions) -> None:
        validated = TaskOptions.model_validate(options).model_copy(deep=True)
        with self._condition:
            self._options = validated
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                **self._options.model_dump(),
                "api_active": self._api.active,
                "api_active_by_job": dict(self._api.by_job),
                "api_active_by_model": dict(self._api.by_model),
                "api_waiting": sum(map(len, self._api.waiting.values())),
                "api_waiting_by_job": {key: len(value) for key, value in self._api.waiting.items()},
                "local_active": self._local.active,
                "local_active_by_job": dict(self._local.by_job),
                "local_waiting": sum(map(len, self._local.waiting.values())),
                "local_waiting_by_job": {
                    key: len(value) for key, value in self._local.waiting.items()
                },
            }

    def _eligible(self, pool: _Pool, request: _Request, *, local: bool) -> bool:
        if local:
            return pool.active < self._options.local_concurrency
        return (
            pool.active < self._options.api_concurrency
            and pool.by_job[request.job_id] < self._options.per_job_api_concurrency
            and pool.by_model[request.model]
            < self._options.per_model_concurrency.get(request.model, self._options.api_concurrency)
        )

    def _next(self, pool: _Pool, *, local: bool) -> _Request | None:
        return next(
            (
                pool.waiting[job_id][0]
                for job_id in pool.order
                if self._eligible(pool, pool.waiting[job_id][0], local=local)
            ),
            None,
        )

    @staticmethod
    def _remove(pool: _Pool, request: _Request) -> None:
        pending = pool.waiting.get(request.job_id)
        if pending and request in pending:
            pending.remove(request)
            pool.order.remove(request.job_id)
            if pending:
                pool.order.append(request.job_id)
            else:
                del pool.waiting[request.job_id]

    @contextmanager
    def _slot(
        self,
        job_id: str,
        model: str,
        *,
        local: bool,
        checkpoint: Checkpoint | None,
        on_event: EventCallback | None,
    ) -> Iterator[None]:
        pool = self._local if local else self._api
        request = _Request(job_id, model)
        started = monotonic()
        admitted = False
        waited = False
        resource = "local" if local else "api"
        if checkpoint:
            checkpoint()
        with self._condition:
            if job_id not in pool.waiting:
                pool.waiting[job_id] = deque()
                pool.order.append(job_id)
            pool.waiting[job_id].append(request)
        try:
            while not admitted:
                if checkpoint:
                    checkpoint()
                emit_wait = False
                with self._condition:
                    if self._next(pool, local=local) is request:
                        self._remove(pool, request)
                        pool.active += 1
                        pool.by_job[job_id] += 1
                        pool.by_model[model] += 1
                        admitted = True
                        self._condition.notify_all()
                    elif not waited:
                        waited = emit_wait = True
                    else:
                        self._condition.wait(timeout=0.2)
                if on_event and emit_wait:
                    on_event({"kind": "resource_wait", "resource": resource, "model": model})
            if on_event and waited:
                on_event(
                    {
                        "kind": "resource_acquired",
                        "resource": resource,
                        "model": model,
                        "wait_seconds": round(monotonic() - started, 4),
                    }
                )
            if checkpoint:
                checkpoint()
            yield
        finally:
            with self._condition:
                if admitted:
                    pool.active -= 1
                    for counts, key in ((pool.by_job, job_id), (pool.by_model, model)):
                        counts[key] -= 1
                        if not counts[key]:
                            del counts[key]
                else:
                    self._remove(pool, request)
                self._condition.notify_all()

    def api(
        self,
        job_id: str,
        model: str,
        *,
        checkpoint: Checkpoint | None = None,
        on_event: EventCallback | None = None,
    ):
        return self._slot(job_id, model, local=False, checkpoint=checkpoint, on_event=on_event)

    def local(
        self,
        job_id: str,
        *,
        checkpoint: Checkpoint | None = None,
        on_event: EventCallback | None = None,
    ):
        return self._slot(job_id, "", local=True, checkpoint=checkpoint, on_event=on_event)
