from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.deduplication import AnomalyDeduplicator


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


def test_persistent_anomaly_is_suppressed_until_cooldown():
    deduplicator = AnomalyDeduplicator(cooldown_seconds=60)
    anomaly = make_service_anomaly()

    assert deduplicator.filter("client", [anomaly], now=0) == [anomaly]
    assert deduplicator.filter("client", [anomaly], now=30) == []
    assert deduplicator.filter("client", [anomaly], now=60) == [anomaly]


def test_resolved_anomaly_is_emitted_immediately_if_it_recurs():
    deduplicator = AnomalyDeduplicator(cooldown_seconds=60)
    anomaly = make_service_anomaly()

    deduplicator.filter("client", [anomaly], now=0)
    assert deduplicator.filter("client", [], now=10) == []
    assert deduplicator.filter("client", [anomaly], now=20) == [anomaly]


def test_severity_escalation_bypasses_cooldown():
    deduplicator = AnomalyDeduplicator(cooldown_seconds=900)
    warning = make_service_anomaly()
    warning.severity = AlertSeverity.WARNING
    critical = make_service_anomaly()

    assert deduplicator.filter("client", [warning], now=0) == [warning]
    assert deduplicator.filter("client", [warning], now=10) == []
    assert deduplicator.filter("client", [critical], now=20) == [critical]
    assert deduplicator.filter("client", [critical], now=30) == []


def test_severity_downgrade_is_not_emitted():
    deduplicator = AnomalyDeduplicator(cooldown_seconds=900)
    critical = make_service_anomaly()
    warning = make_service_anomaly()
    warning.severity = AlertSeverity.WARNING

    assert deduplicator.filter("client", [critical], now=0) == [critical]
    assert deduplicator.filter("client", [warning], now=10) == []
