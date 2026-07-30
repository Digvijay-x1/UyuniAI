from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.react_agent import ALL_TOOLS, get_prompt_for_anomaly


def test_memory_pressure_prompt_requires_causal_correlation():
    anomaly = Anomaly(
        minion_id="client",
        metric_name="memory_pressure",
        current_value=82,
        threshold=70,
        severity=AlertSeverity.CRITICAL,
        description="Host memory usage is 82% with active swapping",
        resource="host-memory",
        context={
            "memory_available_bytes": 720_000_000,
            "memory_total_bytes": 4_000_000_000,
            "swap_used_bytes": 800_000_000,
            "swap_total_bytes": 2_000_000_000,
            "swap_usage_percent": 40,
            "swap_in_pages_per_second": 30,
            "swap_out_pages_per_second": 90,
            "system_cpu_percent": 35,
            "iowait_cpu_percent": 15,
            "cpu_usage_percent": 82,
        },
    )

    prompt = get_prompt_for_anomaly(anomaly, {"memory_percent": 82})
    tool_names = {tool.name for tool in ALL_TOOLS}

    assert "Swap usage by itself does not prove" in prompt.replace("*", "")
    assert "get_memory_pressure_snapshot" in prompt
    assert "secondary effect" in prompt
    assert "are KiB" in prompt
    assert "cumulative microseconds" in prompt
    assert "MemoryMax=" in prompt
    assert "must explicitly say whether that CPU usage" in prompt
    assert "get_memory_pressure_snapshot" in tool_names
