from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.react_agent import get_prompt_for_anomaly


def test_connection_prompt_requires_capacity_owner_and_availability_evidence():
    anomaly = Anomaly(
        minion_id="client",
        metric_name="postgres_connections",
        current_value=96.0,
        threshold=90.0,
        severity=AlertSeverity.CRITICAL,
        description="PostgreSQL connection utilization at 96.0",
        service_name="postgresql",
        resource="postgresql:cluster",
        context={"connection_utilization_percent": 96.0},
    )

    prompt = get_prompt_for_anomaly(anomaly, {})
    normalized_prompt = " ".join(prompt.split())

    assert "max_connections" in prompt
    assert "remaining normal slots" in prompt
    assert "idle in transaction" in prompt
    assert "application" in prompt
    assert "Do not recommend restarting PostgreSQL" in normalized_prompt
    assert "normal_capacity_exhausted=true" in prompt
