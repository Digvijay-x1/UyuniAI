import asyncio

import pytest

from uyuni_ai_agent import main
from uyuni_ai_agent.incident_store import IncidentStore
from uyuni_ai_agent.investigation_queue import InvestigationQueue
from uyuni_ai_agent.observability import AgentObservability
from uyuni_ai_agent.resilience import (
    CircuitBreaker,
    CircuitState,
    DependencyManager,
    DependencyUnavailable,
    ExponentialBackoff,
)


def test_circuit_opens_rejects_and_recovers_with_one_probe():
    now = [10.0]
    circuit = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=5,
        clock=lambda: now[0],
    )

    circuit.record_failure()
    assert circuit.snapshot.state is CircuitState.CLOSED
    circuit.record_failure()
    assert circuit.snapshot.state is CircuitState.OPEN
    assert circuit.acquire().state is CircuitState.OPEN

    now[0] += 5
    assert circuit.acquire().state is CircuitState.HALF_OPEN
    assert circuit.acquire().state is CircuitState.OPEN
    circuit.record_success()
    assert circuit.snapshot.state is CircuitState.CLOSED
    assert circuit.snapshot.consecutive_failures == 0


def test_failed_half_open_probe_reopens_the_circuit():
    now = [0.0]
    circuit = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=10,
        clock=lambda: now[0],
    )
    circuit.record_failure()
    now[0] = 10
    assert circuit.acquire().state is CircuitState.HALF_OPEN
    circuit.record_failure()

    assert circuit.snapshot.state is CircuitState.OPEN
    assert circuit.snapshot.retry_after_seconds == 10


def test_exponential_backoff_is_jittered_and_bounded():
    low = ExponentialBackoff(
        initial_seconds=2,
        maximum_seconds=8,
        jitter_ratio=0.25,
        random_source=lambda: 0,
    )
    high = ExponentialBackoff(
        initial_seconds=2,
        maximum_seconds=8,
        jitter_ratio=0.25,
        random_source=lambda: 1,
    )

    assert [low.delay(n) for n in range(1, 5)] == [1.5, 3.0, 6.0, 6.0]
    assert [high.delay(n) for n in range(1, 5)] == [2.5, 5.0, 8.0, 8.0]


def test_dependency_manager_reports_success_failure_timeout_and_open():
    async def scenario():
        observations = []
        manager = DependencyManager(
            ["salt"],
            failure_threshold=2,
            recovery_timeout_seconds=30,
            observer=lambda *values: observations.append(values),
        )

        async def success():
            return "ok"

        async def failure():
            raise RuntimeError("offline")

        async def slow():
            await asyncio.Event().wait()

        assert await manager.execute("salt", success) == "ok"
        with pytest.raises(RuntimeError):
            await manager.execute("salt", failure)
        with pytest.raises(asyncio.TimeoutError):
            await manager.execute("salt", slow, timeout_seconds=0.001)
        with pytest.raises(DependencyUnavailable):
            await manager.execute("salt", success)
        return [entry[1] for entry in observations]

    assert asyncio.run(scenario()) == [
        "success",
        "error",
        "timeout",
        "circuit_open",
    ]


def test_dependency_manager_treats_unsuccessful_result_as_a_failure():
    async def scenario():
        observations = []
        manager = DependencyManager(
            ["alertmanager"],
            failure_threshold=1,
            recovery_timeout_seconds=30,
            observer=lambda *values: observations.append(values),
        )

        async def rejected():
            return "Error: 503"

        result = await manager.execute(
            "alertmanager",
            rejected,
            success_predicate=lambda value: value.startswith("Success:"),
        )
        return result, manager.snapshot("alertmanager"), observations

    result, snapshot, observations = asyncio.run(scenario())
    assert result == "Error: 503"
    assert snapshot.state is CircuitState.OPEN
    assert observations[0][1] == "error"


def test_readiness_requires_recent_poll_and_critical_dependencies():
    now = [100.0]
    metrics = AgentObservability(
        readiness_max_age_seconds=30,
        clock=lambda: now[0],
        include_runtime_collectors=False,
        required_dependencies={"salt", "prometheus"},
    )
    manager = DependencyManager(
        ["salt", "prometheus"],
        failure_threshold=2,
        recovery_timeout_seconds=10,
        observer=metrics.record_dependency,
    )

    metrics.record_poll(
        duration_seconds=1, total_minions=2, successful_minions=2
    )
    assert metrics.ready is False
    manager.record_external_success("prometheus")
    assert metrics.ready is False
    manager.record_external_success("salt")
    assert metrics.ready is True
    manager.record_external_failure("salt")
    assert metrics.ready is False


def test_detect_minion_keeps_prometheus_detection_when_salt_is_down(monkeypatch):
    async def scenario():
        async def fake_metrics(*_args, **_kwargs):
            return {
                "memory_percent": 10,
                "memory_pressure": {},
                "cpu_percent": 10,
                "disk_percent": 10,
            }

        async def fake_metric_anomalies(*_args, **_kwargs):
            return []

        class SaltMustNotRun:
            def __getattr__(self, name):
                raise AssertionError(f"Salt method {name} must not run")

        monkeypatch.setattr(main, "get_all_metrics", fake_metrics)
        monkeypatch.setattr(main, "check_all_metrics", fake_metric_anomalies)
        return await main.detect_minion(
            {"id": "client", "instance": "client:9100"},
            object(),
            {"service_monitoring": {"enabled": True}},
            asyncio.Semaphore(1),
            SaltMustNotRun(),
            salt_available=False,
        )

    snapshot = asyncio.run(scenario())
    assert snapshot is not None
    assert len(snapshot["anomalies"]) == 1
    anomaly = snapshot["anomalies"][0]
    assert anomaly.metric_name == "telemetry_unavailable"
    assert anomaly.context["source"] == "salt"
    assert snapshot["complete"] is False


def test_poll_cycle_cancels_a_minion_that_exceeds_its_budget(monkeypatch):
    async def scenario():
        cancelled = asyncio.Event()

        async def slow_detection(*_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        class Correlator:
            last_held_count = 0
            grace_seconds = 0

            @staticmethod
            def correlate(anomalies, _edges):
                return anomalies

        monkeypatch.setattr(main, "detect_minion", slow_detection)
        metrics = AgentObservability(
            readiness_max_age_seconds=30,
            include_runtime_collectors=False,
        )
        store = IncidentStore(":memory:")
        queue = InvestigationQueue(max_pending=2, workers=1)
        successful = await main.execute_poll_cycle(
            config={"minions": [{"id": "slow", "instance": "slow:9100"}]},
            http_client=object(),
            minion_sem=asyncio.Semaphore(1),
            salt=type("Salt", (), {"logged_in": True})(),
            dependency_manager=None,
            dependency_correlator=Correlator(),
            correlation_cfg={},
            incident_store=store,
            investigation_queue=queue,
            observability=metrics,
            dry_run=True,
            timeout_config={"minion_seconds": 0.001},
        )
        rendered = metrics.render_metrics().decode()
        store.close()
        return successful, cancelled.is_set(), rendered

    successful, cancelled, rendered = asyncio.run(scenario())
    assert successful == 0
    assert cancelled is True
    assert 'uyuni_ai_agent_timeouts_total{scope="minion"} 1.0' in rendered


def test_poll_cycle_does_not_count_a_degraded_snapshot_as_complete(monkeypatch):
    async def scenario():
        async def degraded_detection(*_args, **_kwargs):
            return {
                "minion": {"id": "client", "instance": "client:9100"},
                "metrics": {},
                "anomalies": [],
                "complete": False,
            }

        class Correlator:
            last_held_count = 0
            grace_seconds = 0

            @staticmethod
            def correlate(anomalies, _edges):
                return anomalies

        monkeypatch.setattr(main, "detect_minion", degraded_detection)
        metrics = AgentObservability(
            readiness_max_age_seconds=30,
            include_runtime_collectors=False,
        )
        store = IncidentStore(":memory:")
        queue = InvestigationQueue(max_pending=2, workers=1)
        successful = await main.execute_poll_cycle(
            config={"minions": [{"id": "client", "instance": "client:9100"}]},
            http_client=object(),
            minion_sem=asyncio.Semaphore(1),
            salt=type("Salt", (), {"logged_in": False})(),
            dependency_manager=None,
            dependency_correlator=Correlator(),
            correlation_cfg={},
            incident_store=store,
            investigation_queue=queue,
            observability=metrics,
            dry_run=True,
            timeout_config={},
        )
        store.close()
        return successful

    assert asyncio.run(scenario()) == 0
