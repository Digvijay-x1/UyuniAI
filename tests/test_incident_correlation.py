from uyuni_ai_agent.anomaly_detector import (
    AlertSeverity,
    Anomaly,
    DependencyCorrelationWindow,
    correlate_dependency_anomalies,
)


def apache_anomaly(request_rate=0.1, minion_id="client"):
    return Anomaly(
        minion_id=minion_id,
        metric_name="apache_busy_workers",
        current_value=90.0,
        threshold=75.0,
        severity=AlertSeverity.WARNING,
        description="Apache busy workers at 90",
        service_name="apache2",
        resource="apache:workers",
        context={"requests_per_second": request_rate},
    )


def postgres_anomaly(application="checkout-backend", minion_id="client"):
    return Anomaly(
        minion_id=minion_id,
        metric_name="postgres_blocked_transaction",
        current_value=45.0,
        threshold=30.0,
        severity=AlertSeverity.CRITICAL,
        description="blocked transactions",
        service_name="postgresql",
        resource="postgresql:orders",
        context={
            "database": "orders",
            "blocked_pairs": [{
                "blocked_application": application,
                "blocked_pid": 20,
                "blocker_pid": 10,
            }],
        },
    )


def test_correlates_low_throughput_web_lock_pair_into_one_incident():
    result = correlate_dependency_anomalies([
        apache_anomaly(),
        postgres_anomaly(),
    ])

    assert len(result) == 1
    assert result[0].metric_name == "postgres_apache_chain"
    assert result[0].severity is AlertSeverity.CRITICAL
    assert result[0].resource == (
        "dependency-chain:postgresql:orders->apache"
    )
    assert result[0].context["correlated_metric_names"] == [
        "apache_busy_workers",
        "postgres_blocked_transaction",
    ]


def test_does_not_correlate_traffic_spike_or_unrelated_application():
    traffic = correlate_dependency_anomalies([
        apache_anomaly(request_rate=800.0),
        postgres_anomaly(),
    ])
    unrelated = correlate_dependency_anomalies([
        apache_anomaly(),
        postgres_anomaly(application="batch-report-worker"),
    ])

    assert [item.metric_name for item in traffic] == [
        "apache_busy_workers",
        "postgres_blocked_transaction",
    ]
    assert [item.metric_name for item in unrelated] == [
        "apache_busy_workers",
        "postgres_blocked_transaction",
    ]


def test_cross_minion_correlation_requires_explicit_dependency_edge():
    anomalies = [
        apache_anomaly(minion_id="web2"),
        postgres_anomaly(minion_id="database1"),
    ]

    without_edge = correlate_dependency_anomalies(anomalies)
    with_edge = correlate_dependency_anomalies(
        anomalies,
        [{
            "apache_minion": "web2",
            "postgres_minion": "database1",
        }],
    )

    assert [item.metric_name for item in without_edge] == [
        "apache_busy_workers",
        "postgres_blocked_transaction",
    ]
    assert len(with_edge) == 1
    assert with_edge[0].metric_name == "postgres_apache_chain"
    assert with_edge[0].minion_id == "web2"
    assert with_edge[0].context["apache_minion_id"] == "web2"
    assert with_edge[0].context["postgres_minion_id"] == "database1"
    assert with_edge[0].resource == (
        "dependency-chain:database1:postgresql:orders->web2:apache"
    )


EDGE = [{
    "apache_minion": "web2",
    "postgres_minion": "database1",
}]


def test_correlation_window_holds_first_signal_then_groups_next_cycle():
    window = DependencyCorrelationWindow(grace_seconds=90)

    first_cycle = window.correlate(
        [postgres_anomaly(minion_id="database1")],
        EDGE,
        now=0,
    )
    second_cycle = window.correlate(
        [
            postgres_anomaly(minion_id="database1"),
            apache_anomaly(minion_id="web2"),
        ],
        EDGE,
        now=60,
    )

    assert first_cycle == []
    assert len(second_cycle) == 1
    assert second_cycle[0].metric_name == "postgres_apache_chain"


def test_correlation_window_releases_standalone_after_grace_expires():
    window = DependencyCorrelationWindow(grace_seconds=90)
    anomaly = postgres_anomaly(minion_id="database1")

    assert window.correlate([anomaly], EDGE, now=10) == []
    released = window.correlate([anomaly], EDGE, now=101)

    assert released == [anomaly]


def test_resolved_candidate_is_not_correlated_with_a_later_stale_signal():
    window = DependencyCorrelationWindow(grace_seconds=90)

    assert window.correlate(
        [postgres_anomaly(minion_id="database1")],
        EDGE,
        now=0,
    ) == []
    assert window.correlate([], EDGE, now=30) == []
    apache_only = window.correlate(
        [apache_anomaly(minion_id="web2")],
        EDGE,
        now=60,
    )

    assert apache_only == []
    assert window.last_held_count == 1


def test_correlation_window_does_not_delay_unrelated_or_traffic_alerts():
    window = DependencyCorrelationWindow(grace_seconds=90)
    unrelated = postgres_anomaly(
        application="batch-report-worker",
        minion_id="database1",
    )
    traffic = apache_anomaly(request_rate=800, minion_id="web2")

    result = window.correlate([unrelated, traffic], EDGE, now=0)

    assert result == [unrelated, traffic]
