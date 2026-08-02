import asyncio
import time

from uyuni_ai_agent import main
from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.incident_store import IncidentStore
from uyuni_ai_agent.investigation_queue import InvestigationQueue
from uyuni_ai_agent.models import (
    AnalysisConclusion,
    RootCauseAnalysis,
    Urgency,
)


def anomaly():
    return Anomaly(
        minion_id="client",
        metric_name="service_down",
        current_value=1,
        threshold=1,
        severity=AlertSeverity.CRITICAL,
        description="my-web.service failed",
        service_name="my-web.service",
    )


def analysis():
    return RootCauseAnalysis(
        summary="Port conflict",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component="my-web.service",
        root_cause="Another process owns the port [E1].",
        supporting_evidence_ids=["E1"],
        key_evidence=["[E1] port 9000 is occupied"],
        remediation=["Stop the conflicting process"],
        urgency=Urgency.HIGH,
        confidence=0.95,
    )


def snapshot():
    return {"minion": {"id": "client"}, "metrics": {}}


async def process(store, queue, cycle_anomalies):
    await main.process_minion_anomalies(
        snapshot(),
        cycle_anomalies,
        object(),
        {"alertmanager": {"url": "http://alertmanager"}},
        False,
        store,
        queue,
    )


def test_failed_delivery_is_retried_before_cooldown(monkeypatch):
    async def scenario():
        store = IncidentStore(":memory:", cooldown_seconds=900)
        queue = InvestigationQueue(max_pending=5, workers=1)
        deliveries = []
        results = ["Error: unavailable", "Success: delivered"]

        async def fake_investigate(*_args, **_kwargs):
            return analysis()

        async def fake_send(_client, _config, payload):
            deliveries.append(payload)
            return results.pop(0)

        monkeypatch.setattr(main, "investigate", fake_investigate)
        monkeypatch.setattr(main, "send_alert_payload", fake_send)
        await queue.start(lambda work: main.process_firing_investigation(
            work, object(), {}, False, asyncio.Semaphore(1), store, 300
        ))

        current = [anomaly()]
        await process(store, queue, current)
        await queue.wait_idle()
        await process(store, queue, current)
        await queue.wait_idle()
        await process(store, queue, current)
        await queue.wait_idle()
        await queue.close()
        store.close()
        return deliveries

    deliveries = asyncio.run(scenario())
    assert len(deliveries) == 2
    assert deliveries[0]["labels"] == deliveries[1]["labels"]


def test_recovery_sends_exact_alertmanager_resolution(monkeypatch):
    async def scenario():
        store = IncidentStore(
            ":memory:", cooldown_seconds=900, resolve_after_healthy_cycles=2
        )
        queue = InvestigationQueue(max_pending=5, workers=1)
        deliveries = []
        results = ["Success: firing", "Success: resolved"]

        async def fake_investigate(*_args, **_kwargs):
            return analysis()

        async def fake_send(_client, _config, payload):
            deliveries.append(payload)
            return results.pop(0)

        monkeypatch.setattr(main, "investigate", fake_investigate)
        monkeypatch.setattr(main, "send_alert_payload", fake_send)
        await queue.start(lambda work: main.process_firing_investigation(
            work, object(), {}, False, asyncio.Semaphore(1), store, 300
        ))

        await process(store, queue, [anomaly()])
        await queue.wait_idle()
        await process(store, queue, [])
        await process(store, queue, [])
        await queue.close()
        store.close()
        return deliveries

    firing, resolved = asyncio.run(scenario())
    assert resolved["labels"] == firing["labels"]
    assert resolved["startsAt"] == firing["startsAt"]
    assert "endsAt" in resolved


def test_recovery_during_investigation_discards_stale_result(monkeypatch):
    async def scenario():
        store = IncidentStore(
            ":memory:", cooldown_seconds=900, resolve_after_healthy_cycles=2
        )
        queue = InvestigationQueue(max_pending=5, workers=1)
        started = asyncio.Event()
        release = asyncio.Event()
        deliveries = []

        async def slow_investigate(*_args, **_kwargs):
            started.set()
            await release.wait()
            return analysis()

        async def fake_send(_client, _config, payload):
            deliveries.append(payload)
            return "Success: delivered"

        monkeypatch.setattr(main, "investigate", slow_investigate)
        monkeypatch.setattr(main, "send_alert_payload", fake_send)
        await queue.start(lambda work: main.process_firing_investigation(
            work, object(), {}, False, asyncio.Semaphore(1), store, 300
        ))

        await process(store, queue, [anomaly()])
        await started.wait()
        await process(store, queue, [])
        await process(store, queue, [])
        release.set()
        await queue.wait_idle()
        await process(store, queue, [])
        await queue.close()
        store.close()
        return deliveries

    assert asyncio.run(scenario()) == []


def test_stale_queued_snapshot_is_skipped_and_remains_retryable(monkeypatch):
    async def scenario():
        store = IncidentStore(":memory:", cooldown_seconds=900)
        firing = store.reconcile("client", [anomaly()]).firing[0]

        async def should_not_investigate(*_args, **_kwargs):
            raise AssertionError("stale work must not call the investigator")

        monkeypatch.setattr(main, "investigate", should_not_investigate)
        await main.process_firing_investigation(
            main.InvestigationWork(
                firing=firing,
                metrics={},
                detected_at=time.time() - 60,
            ),
            object(),
            {},
            False,
            asyncio.Semaphore(1),
            store,
            10,
        )
        retry = store.reconcile("client", [anomaly()]).firing
        store.close()
        return retry

    assert len(asyncio.run(scenario())) == 1


def test_detection_reconciliation_does_not_wait_for_slow_investigation():
    async def scenario():
        store = IncidentStore(":memory:", cooldown_seconds=900)
        queue = InvestigationQueue(max_pending=5, workers=1)
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_handler(_work):
            started.set()
            await release.wait()

        await queue.start(slow_handler)
        await asyncio.wait_for(
            process(store, queue, [anomaly()]), timeout=0.1
        )
        await started.wait()
        stats_while_blocked = queue.stats
        release.set()
        await queue.wait_idle()
        await queue.close()
        store.close()
        return stats_while_blocked

    stats = asyncio.run(scenario())
    assert stats.in_flight == 1
    assert stats.completed == 0
