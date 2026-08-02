import asyncio
from types import SimpleNamespace

from uyuni_ai_agent.investigation_queue import InvestigationQueue, QueueStats
from uyuni_ai_agent.observability import AgentObservability, ObservabilityServer


def observability(now=None):
    if now is None:
        now = [1000.0]
    return AgentObservability(
        readiness_max_age_seconds=30,
        clock=lambda: now[0],
        include_runtime_collectors=False,
    )


def test_metrics_capture_runtime_state_without_unbounded_evidence():
    now = [1000.0]
    metrics = observability(now)

    outcome = metrics.record_poll(
        duration_seconds=2.5,
        total_minions=2,
        successful_minions=1,
    )
    metrics.record_anomaly_observations([
        SimpleNamespace(severity=SimpleNamespace(value="critical"))
    ])
    metrics.observe_queue(QueueStats(
        pending=2,
        in_flight=1,
        enqueued=3,
        coalesced=1,
        completed=0,
        failed=0,
        rejected=2,
        evicted=1,
        cancelled=0,
    ))
    metrics.record_investigation(
        severity="critical", outcome="delivered", duration_seconds=4.2
    )
    metrics.record_incident_counts({"active": 2, "resolved": 7})
    metrics.record_alert_delivery(
        state="firing",
        result="Success: delivered",
        duration_seconds=0.4,
    )
    metrics.record_timeout("investigation")
    rendered = metrics.render_metrics().decode("utf-8")

    assert outcome == "partial"
    assert metrics.ready is True
    assert 'uyuni_ai_agent_poll_cycles_total{outcome="partial"} 1.0' in rendered
    assert "uyuni_ai_agent_investigation_queue_pending 2.0" in rendered
    assert (
        'uyuni_ai_agent_investigation_queue_events_total{event="rejected"} 2.0'
        in rendered
    )
    assert 'uyuni_ai_agent_incidents{status="active"} 2.0' in rendered
    assert 'outcome="success",state="firing"' in rendered
    assert 'uyuni_ai_agent_timeouts_total{scope="investigation"} 1.0' in rendered
    assert "prompt" not in rendered.lower()
    assert "command" not in rendered.lower()

    now[0] += 31
    expired = metrics.render_metrics().decode("utf-8")
    assert metrics.ready is False
    assert "uyuni_ai_agent_ready 0.0" in expired


def test_queue_observer_tracks_worker_transitions():
    async def scenario():
        metrics = observability()
        queue = InvestigationQueue(
            max_pending=2,
            workers=1,
            observer=metrics.observe_queue,
        )
        await queue.enqueue("incident", "critical", "payload")
        await queue.start(lambda _payload: asyncio.sleep(0))
        await queue.wait_idle()
        await queue.close()
        return metrics.render_metrics().decode("utf-8")

    rendered = asyncio.run(scenario())
    assert "uyuni_ai_agent_investigation_queue_pending 0.0" in rendered
    assert "uyuni_ai_agent_investigations_in_flight 0.0" in rendered
    assert (
        'uyuni_ai_agent_investigation_queue_events_total{event="completed"} 1.0'
        in rendered
    )


def test_health_readiness_and_metrics_http_routes():
    async def request(port, path, method="GET"):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(
                "ascii"
            )
        )
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        head, _, body = response.partition(b"\r\n\r\n")
        status = int(head.split(b" ", 2)[1])
        return status, head, body

    async def scenario():
        metrics = observability()
        server = ObservabilityServer(metrics, "127.0.0.1", 0)
        await server.start()
        port = server.bound_port
        health = await request(port, "/healthz")
        not_ready = await request(port, "/readyz")
        metrics.record_poll(
            duration_seconds=1,
            total_minions=1,
            successful_minions=1,
        )
        ready = await request(port, "/readyz")
        exposition = await request(port, "/metrics?unused=1")
        rejected = await request(port, "/metrics", method="POST")
        missing = await request(port, "/does-not-exist")
        await server.close()
        return health, not_ready, ready, exposition, rejected, missing

    health, not_ready, ready, exposition, rejected, missing = asyncio.run(
        scenario()
    )
    assert health[0] == 200 and health[2] == b'{"status":"ok"}\n'
    assert not_ready[0] == 503
    assert ready[0] == 200 and ready[2] == b'{"status":"ready"}\n'
    assert exposition[0] == 200
    assert b"uyuni_ai_agent_up 1.0" in exposition[2]
    assert b"Cache-Control: no-store" in exposition[1]
    assert rejected[0] == 405
    assert missing[0] == 404
