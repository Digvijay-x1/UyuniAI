"""Bounded, priority-aware work queue for anomaly investigations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import heapq
import itertools
import logging
from typing import Any, Awaitable, Callable


logger = logging.getLogger(__name__)


_SEVERITY_PRIORITY = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}


class EnqueueStatus(str, Enum):
    ENQUEUED = "enqueued"
    COALESCED = "coalesced"
    IN_FLIGHT = "in_flight"
    REJECTED_FULL = "rejected_full"
    REJECTED_CLOSED = "rejected_closed"


class CancelStatus(str, Enum):
    CANCELLED = "cancelled"
    IN_FLIGHT = "in_flight"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class EnqueueResult:
    status: EnqueueStatus
    pending: int
    in_flight: int
    evicted_fingerprint: str | None = None


@dataclass(frozen=True)
class QueueStats:
    pending: int
    in_flight: int
    enqueued: int
    coalesced: int
    completed: int
    failed: int
    rejected: int
    evicted: int
    cancelled: int


@dataclass(frozen=True)
class ShutdownResult:
    drained: bool
    abandoned: int


@dataclass(order=True)
class _QueueItem:
    priority: int
    sequence: int
    fingerprint: str = field(compare=False)
    payload: Any = field(compare=False)


Handler = Callable[[Any], Awaitable[None]]
Observer = Callable[[QueueStats], None]


def priority_for_severity(severity: Any) -> int:
    value = str(getattr(severity, "value", severity)).lower()
    return _SEVERITY_PRIORITY.get(value, 3)


class InvestigationQueue:
    """Bound pending investigations and protect workers from alert storms.

    Duplicate pending incidents are coalesced with the newest snapshot. If a
    critical incident arrives while the queue is full of lower-priority work,
    the least important pending item is evicted. Rejected and evicted jobs are
    deliberately not acknowledged in the incident store, so polling retries
    them later.
    """

    def __init__(
        self,
        *,
        max_pending: int,
        workers: int,
        observer: Observer | None = None,
    ):
        if max_pending < 1:
            raise ValueError("max_pending must be at least 1")
        if workers < 1:
            raise ValueError("workers must be at least 1")
        self.max_pending = int(max_pending)
        self.worker_count = int(workers)
        self._condition = asyncio.Condition()
        self._heap: list[_QueueItem] = []
        self._pending: dict[str, _QueueItem] = {}
        self._in_flight: set[str] = set()
        self._sequence = itertools.count()
        self._handler: Handler | None = None
        self._observer = observer
        self._worker_tasks: list[asyncio.Task] = []
        self._accepting = True
        self._closing = False
        self._enqueued = 0
        self._coalesced = 0
        self._completed = 0
        self._failed = 0
        self._rejected = 0
        self._evicted = 0
        self._cancelled = 0
        self._notify_observer()

    @property
    def stats(self) -> QueueStats:
        return QueueStats(
            pending=len(self._heap),
            in_flight=len(self._in_flight),
            enqueued=self._enqueued,
            coalesced=self._coalesced,
            completed=self._completed,
            failed=self._failed,
            rejected=self._rejected,
            evicted=self._evicted,
            cancelled=self._cancelled,
        )

    async def start(self, handler: Handler) -> None:
        if self._worker_tasks:
            raise RuntimeError("investigation queue is already started")
        if self._closing:
            raise RuntimeError("investigation queue is closed")
        self._handler = handler
        self._worker_tasks = [
            asyncio.create_task(
                self._worker(index + 1),
                name=f"investigation-worker-{index + 1}",
            )
            for index in range(self.worker_count)
        ]

    async def enqueue(
        self,
        fingerprint: str,
        severity: Any,
        payload: Any,
    ) -> EnqueueResult:
        priority = priority_for_severity(severity)
        async with self._condition:
            if not self._accepting:
                self._rejected += 1
                result = self._result(EnqueueStatus.REJECTED_CLOSED)
                self._notify_observer()
                return result
            if fingerprint in self._in_flight:
                return self._result(EnqueueStatus.IN_FLIGHT)

            existing = self._pending.get(fingerprint)
            if existing is not None:
                self._heap.remove(existing)
                replacement = _QueueItem(
                    priority=min(priority, existing.priority),
                    sequence=existing.sequence,
                    fingerprint=fingerprint,
                    payload=payload,
                )
                heapq.heapify(self._heap)
                heapq.heappush(self._heap, replacement)
                self._pending[fingerprint] = replacement
                self._coalesced += 1
                self._condition.notify()
                result = self._result(EnqueueStatus.COALESCED)
                self._notify_observer()
                return result

            evicted_fingerprint = None
            if len(self._heap) >= self.max_pending:
                worst = max(
                    self._heap,
                    key=lambda item: (item.priority, item.sequence),
                )
                if priority >= worst.priority:
                    self._rejected += 1
                    result = self._result(EnqueueStatus.REJECTED_FULL)
                    self._notify_observer()
                    return result
                self._heap.remove(worst)
                heapq.heapify(self._heap)
                self._pending.pop(worst.fingerprint, None)
                self._evicted += 1
                evicted_fingerprint = worst.fingerprint

            item = _QueueItem(
                priority=priority,
                sequence=next(self._sequence),
                fingerprint=fingerprint,
                payload=payload,
            )
            heapq.heappush(self._heap, item)
            self._pending[fingerprint] = item
            self._enqueued += 1
            self._condition.notify()
            result = self._result(
                EnqueueStatus.ENQUEUED,
                evicted_fingerprint=evicted_fingerprint,
            )
            self._notify_observer()
            return result

    async def cancel(self, fingerprint: str) -> CancelStatus:
        async with self._condition:
            item = self._pending.pop(fingerprint, None)
            if item is not None:
                self._heap.remove(item)
                heapq.heapify(self._heap)
                self._cancelled += 1
                self._condition.notify_all()
                self._notify_observer()
                return CancelStatus.CANCELLED
            if fingerprint in self._in_flight:
                return CancelStatus.IN_FLIGHT
            return CancelStatus.NOT_FOUND

    async def wait_idle(self, timeout: float = 30) -> None:
        async def _wait():
            async with self._condition:
                await self._condition.wait_for(
                    lambda: not self._heap and not self._in_flight
                )

        await asyncio.wait_for(_wait(), timeout=max(0.01, float(timeout)))

    async def close(self, grace_seconds: float = 30) -> ShutdownResult:
        if not self._worker_tasks:
            self._accepting = False
            self._closing = True
            return ShutdownResult(drained=not self._heap, abandoned=len(self._heap))

        async with self._condition:
            self._accepting = False
            self._closing = True
            self._condition.notify_all()

        tasks = list(self._worker_tasks)
        gathered = asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(
                asyncio.shield(gathered),
                timeout=max(0.01, float(grace_seconds)),
            )
            result = ShutdownResult(drained=True, abandoned=0)
        except asyncio.TimeoutError:
            abandoned = len(self._heap) + len(self._in_flight)
            for task in tasks:
                task.cancel()
            await gathered
            result = ShutdownResult(drained=False, abandoned=abandoned)
        finally:
            self._worker_tasks = []
        return result

    def _result(
        self,
        status: EnqueueStatus,
        *,
        evicted_fingerprint: str | None = None,
    ) -> EnqueueResult:
        return EnqueueResult(
            status=status,
            pending=len(self._heap),
            in_flight=len(self._in_flight),
            evicted_fingerprint=evicted_fingerprint,
        )

    async def _next(self) -> _QueueItem | None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: bool(self._heap) or self._closing
            )
            if not self._heap:
                return None
            item = heapq.heappop(self._heap)
            self._pending.pop(item.fingerprint, None)
            self._in_flight.add(item.fingerprint)
            self._notify_observer()
            return item

    async def _worker(self, worker_number: int) -> None:
        while True:
            item = await self._next()
            if item is None:
                return
            try:
                if self._handler is None:
                    raise RuntimeError("investigation queue has no handler")
                await self._handler(item.payload)
                self._completed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self._failed += 1
                logger.exception(
                    "Investigation worker %d failed for incident %s",
                    worker_number,
                    item.fingerprint,
                )
            finally:
                async with self._condition:
                    self._in_flight.discard(item.fingerprint)
                    self._notify_observer()
                    self._condition.notify_all()

    def _notify_observer(self) -> None:
        if self._observer is None:
            return
        try:
            self._observer(self.stats)
        except Exception:
            logger.exception("Investigation queue observer failed")
