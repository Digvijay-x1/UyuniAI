from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.incident_store import IncidentStore


def make_service_anomaly():
    return Anomaly(
        minion_id="client",
        metric_name="service_down",
        current_value=1,
        threshold=1,
        severity=AlertSeverity.CRITICAL,
        description="my-web.service failed",
        service_name="my-web.service",
    )


def mark_firing_delivered(store, firing, now):
    store.mark_emitted(
        firing.fingerprint,
        {
            "labels": {"incident_id": firing.fingerprint},
            "startsAt": firing.starts_at,
        },
        now=now,
    )


def test_persistent_anomaly_is_suppressed_until_cooldown():
    store = IncidentStore(":memory:", cooldown_seconds=60)
    anomaly = make_service_anomaly()

    first = store.reconcile("client", [anomaly], now=0)
    assert [item.anomaly for item in first.firing] == [anomaly]
    mark_firing_delivered(store, first.firing[0], now=0)
    assert store.reconcile("client", [anomaly], now=30).firing == []
    assert [
        item.anomaly
        for item in store.reconcile("client", [anomaly], now=60).firing
    ] == [anomaly]


def test_delivery_failure_is_retried_on_next_cycle():
    store = IncidentStore(":memory:", cooldown_seconds=900)
    anomaly = make_service_anomaly()

    assert len(store.reconcile("client", [anomaly], now=0).firing) == 1
    assert len(store.reconcile("client", [anomaly], now=10).firing) == 1


def test_resolved_anomaly_is_emitted_immediately_if_it_recurs():
    store = IncidentStore(
        ":memory:", cooldown_seconds=60, resolve_after_healthy_cycles=1
    )
    anomaly = make_service_anomaly()

    first = store.reconcile("client", [anomaly], now=0).firing[0]
    mark_firing_delivered(store, first, now=0)
    resolved = store.reconcile("client", [], now=10).resolved
    assert len(resolved) == 1
    store.mark_resolved(resolved[0].fingerprint, now=10)
    assert len(store.reconcile("client", [anomaly], now=20).firing) == 1


def test_resolution_requires_consecutive_healthy_cycles():
    store = IncidentStore(
        ":memory:", cooldown_seconds=60, resolve_after_healthy_cycles=2
    )
    anomaly = make_service_anomaly()
    first = store.reconcile("client", [anomaly], now=0).firing[0]
    mark_firing_delivered(store, first, now=0)

    assert store.reconcile("client", [], now=10).resolved == []
    assert len(store.reconcile("client", [], now=20).resolved) == 1
    assert store.reconcile("client", [anomaly], now=25).resolved == []


def test_severity_escalation_bypasses_cooldown():
    store = IncidentStore(":memory:", cooldown_seconds=900)
    warning = make_service_anomaly()
    warning.severity = AlertSeverity.WARNING
    critical = make_service_anomaly()

    first = store.reconcile("client", [warning], now=0).firing[0]
    mark_firing_delivered(store, first, now=0)
    assert store.reconcile("client", [warning], now=10).firing == []
    escalated = store.reconcile("client", [critical], now=20).firing
    assert [item.anomaly for item in escalated] == [critical]
    assert escalated[0].previous_payload is not None


def test_severity_downgrade_is_not_emitted():
    store = IncidentStore(":memory:", cooldown_seconds=900)
    critical = make_service_anomaly()
    warning = make_service_anomaly()
    warning.severity = AlertSeverity.WARNING

    first = store.reconcile("client", [critical], now=0).firing[0]
    mark_firing_delivered(store, first, now=0)
    assert store.reconcile("client", [warning], now=10).firing == []


def test_state_survives_store_restart(tmp_path):
    path = tmp_path / "incidents.db"
    anomaly = make_service_anomaly()
    first_store = IncidentStore(str(path), cooldown_seconds=60)
    first = first_store.reconcile("client", [anomaly], now=0).firing[0]
    mark_firing_delivered(first_store, first, now=0)
    first_store.close()

    restarted_store = IncidentStore(str(path), cooldown_seconds=60)
    assert restarted_store.reconcile("client", [anomaly], now=30).firing == []
    assert len(
        restarted_store.reconcile("client", [anomaly], now=60).firing
    ) == 1
    restarted_store.close()


def test_in_flight_warning_does_not_hide_new_critical_severity():
    store = IncidentStore(":memory:", cooldown_seconds=900)
    warning = make_service_anomaly()
    warning.severity = AlertSeverity.WARNING
    critical = make_service_anomaly()

    firing = store.reconcile("client", [warning], now=0).firing[0]
    store.reconcile("client", [critical], now=1)
    store.mark_emitted(
        firing.fingerprint,
        {
            "labels": {
                "incident_id": firing.fingerprint,
                "severity": "warning",
            },
            "startsAt": firing.starts_at,
        },
        now=2,
        starts_at=firing.starts_at,
    )

    escalated = store.reconcile("client", [critical], now=3).firing
    assert len(escalated) == 1
    assert escalated[0].anomaly.severity is AlertSeverity.CRITICAL


def test_old_generation_cannot_mark_recurrent_incident_emitted():
    store = IncidentStore(
        ":memory:", cooldown_seconds=900, resolve_after_healthy_cycles=1
    )
    current = make_service_anomaly()
    old = store.reconcile("client", [current], now=0).firing[0]
    resolved = store.reconcile("client", [], now=1).resolved[0]
    store.mark_resolved(resolved.fingerprint, now=1)
    recurrent = store.reconcile("client", [current], now=2).firing[0]

    store.mark_emitted(
        old.fingerprint,
        {
            "labels": {"severity": "critical"},
            "startsAt": old.starts_at,
        },
        now=3,
        starts_at=old.starts_at,
    )

    assert recurrent.starts_at != old.starts_at
    assert len(store.reconcile("client", [current], now=4).firing) == 1
