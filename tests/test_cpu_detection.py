import asyncio

from uyuni_ai_agent.anomaly_detector import AlertSeverity, check_all_metrics
from uyuni_ai_agent.cpu_inspection import build_cpu_pressure_command


def test_cpu_anomaly_carries_memory_context_for_correlation():
    memory = {
        "memory_usage_percent": 20,
        "swap_activity_pages_per_second": 0,
        "swap_usage_percent": 0,
    }
    metrics = {
        "memory_percent": 20,
        "memory_pressure": memory,
        "cpu_percent": 98,
        "filesystems": [],
    }
    config = {
        "thresholds": {
            "memory": {"warning": 70, "critical": 95},
            "cpu": {"warning": 70, "critical": 95},
            "disk": {"warning": 75, "critical": 95},
        }
    }

    anomalies = asyncio.run(check_all_metrics(
        "client:9100",
        "client",
        None,
        config,
        metrics=metrics,
    ))

    assert len(anomalies) == 1
    assert anomalies[0].metric_name == "cpu"
    assert anomalies[0].severity is AlertSeverity.CRITICAL
    assert anomalies[0].resource == "host-cpu"
    assert anomalies[0].context["memory_pressure"] == memory


def test_cpu_probe_is_fixed_bounded_and_omits_process_arguments():
    command = build_cpu_pressure_command()

    assert "=== LOGICAL_CPU_COUNT ===" in command
    assert "vmstat -w 1 3" in command
    assert "--sort=-%cpu | head -n 16" in command
    assert "/proc/pressure/cpu" in command
    assert "journalctl -k --since '-10 minutes'" in command
    assert "args" not in command
