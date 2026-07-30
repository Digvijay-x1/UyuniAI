from uyuni_ai_agent.anomaly_detector import Anomaly, AlertSeverity
from uyuni_ai_agent.react_agent import get_prompt_for_anomaly


def test_blocked_transaction_prompt_distinguishes_availability_from_lock_wait():
    anomaly = Anomaly(
        minion_id="client",
        metric_name="postgres_blocked_transaction",
        current_value=45,
        threshold=30,
        severity=AlertSeverity.CRITICAL,
        description="blocked transaction",
        service_name="postgresql",
        resource="postgresql:my_anomaly_lab",
        context={
            "database": "my_anomaly_lab",
            "blocked_pids": [202],
            "blocker_pids": [101],
        },
    )

    prompt = get_prompt_for_anomaly(anomaly, {})

    assert "get_postgres_health" in prompt
    assert "get_postgres_locks" in prompt
    assert "idle in transaction" in prompt
    assert "not a PostgreSQL outage" in prompt
    assert "Do not recommend restarting PostgreSQL" in prompt
    assert "COMMIT or ROLLBACK" in prompt
