import asyncio

from uyuni_ai_agent.investigation_queue import (
    CancelStatus,
    EnqueueStatus,
    InvestigationQueue,
)


def test_critical_work_runs_before_older_lower_priority_work():
    async def scenario():
        handled = []
        queue = InvestigationQueue(max_pending=5, workers=1)
        await queue.enqueue("info", "info", "info")
        await queue.enqueue("critical", "critical", "critical")
        await queue.enqueue("warning", "warning", "warning")
        await queue.start(lambda payload: _append(handled, payload))
        await queue.wait_idle()
        await queue.close()
        return handled

    assert asyncio.run(scenario()) == ["critical", "warning", "info"]


def test_duplicate_pending_work_is_coalesced_with_newest_snapshot():
    async def scenario():
        handled = []
        queue = InvestigationQueue(max_pending=2, workers=1)
        first = await queue.enqueue("same", "warning", "old")
        second = await queue.enqueue("same", "critical", "new")
        await queue.start(lambda payload: _append(handled, payload))
        await queue.wait_idle()
        stats = queue.stats
        await queue.close()
        return first, second, handled, stats

    first, second, handled, stats = asyncio.run(scenario())
    assert first.status is EnqueueStatus.ENQUEUED
    assert second.status is EnqueueStatus.COALESCED
    assert handled == ["new"]
    assert stats.coalesced == 1


def test_full_queue_rejects_lower_priority_but_critical_evicts_warning():
    async def scenario():
        handled = []
        queue = InvestigationQueue(max_pending=1, workers=1)
        await queue.enqueue("warning", "warning", "warning")
        rejected = await queue.enqueue("info", "info", "info")
        critical = await queue.enqueue("critical", "critical", "critical")
        await queue.start(lambda payload: _append(handled, payload))
        await queue.wait_idle()
        stats = queue.stats
        await queue.close()
        return rejected, critical, handled, stats

    rejected, critical, handled, stats = asyncio.run(scenario())
    assert rejected.status is EnqueueStatus.REJECTED_FULL
    assert critical.status is EnqueueStatus.ENQUEUED
    assert critical.evicted_fingerprint == "warning"
    assert handled == ["critical"]
    assert stats.rejected == 1
    assert stats.evicted == 1


def test_in_flight_work_is_not_duplicated_or_cancelled():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def block(_payload):
            started.set()
            await release.wait()

        queue = InvestigationQueue(max_pending=2, workers=1)
        await queue.start(block)
        await queue.enqueue("incident", "critical", "payload")
        await started.wait()
        duplicate = await queue.enqueue("incident", "critical", "new")
        cancelled = await queue.cancel("incident")
        release.set()
        await queue.wait_idle()
        await queue.close()
        return duplicate, cancelled

    duplicate, cancelled = asyncio.run(scenario())
    assert duplicate.status is EnqueueStatus.IN_FLIGHT
    assert cancelled is CancelStatus.IN_FLIGHT


def test_pending_work_can_be_cancelled_before_investigation():
    async def scenario():
        handled = []
        queue = InvestigationQueue(max_pending=2, workers=1)
        await queue.enqueue("incident", "warning", "payload")
        cancelled = await queue.cancel("incident")
        await queue.start(lambda payload: _append(handled, payload))
        await queue.wait_idle()
        await queue.close()
        return cancelled, handled

    cancelled, handled = asyncio.run(scenario())
    assert cancelled is CancelStatus.CANCELLED
    assert handled == []


def test_shutdown_timeout_cancels_worker_and_reports_abandoned_work():
    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def never_finishes(_payload):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        queue = InvestigationQueue(max_pending=2, workers=1)
        await queue.start(never_finishes)
        await queue.enqueue("first", "critical", "first")
        await queue.enqueue("second", "warning", "second")
        await started.wait()
        result = await queue.close(grace_seconds=0)
        return result, cancelled.is_set()

    result, cancelled = asyncio.run(scenario())
    assert result.drained is False
    assert result.abandoned == 2
    assert cancelled is True


async def _append(collection, value):
    collection.append(value)
