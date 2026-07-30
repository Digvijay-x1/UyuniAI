from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.react_agent import ALL_TOOLS, get_prompt_for_anomaly


def test_cpu_prompt_requires_process_and_pressure_evidence():
    anomaly = Anomaly(
        minion_id="client",
        metric_name="cpu",
        current_value=98,
        threshold=95,
        severity=AlertSeverity.CRITICAL,
        description="CPU usage at 98%",
        resource="host-cpu",
    )

    prompt = get_prompt_for_anomaly(anomaly, {"cpu_percent": 98})
    names = {item.name for item in ALL_TOOLS}

    assert "get_cpu_pressure_snapshot" in prompt
    assert "user CPU, system CPU, I/O wait, steal time" in prompt
    assert "possible secondary symptom" in prompt
    assert "authoritative logical CPU count" in prompt
    assert "get_cpu_pressure_snapshot" in names
