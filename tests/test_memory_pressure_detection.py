import asyncio
import time

from uyuni_ai_agent.anomaly_detector import (
    AlertSeverity,
    check_all_metrics,
    memory_pressure_anomaly,
)
from uyuni_ai_agent.memory_inspection import build_memory_pressure_command
from uyuni_ai_agent.prometheus_client import get_memory_pressure_metrics

THRESHOLDS = {
    "warning": 70,
    "critical": 95,
    "pressure": {
        "swap_activity_pages_per_second": {
            "warning": 1,
            "critical": 100,
        },
        "swap_usage_percent": {
            "warning": 5,
            "critical": 25,
        },
    },
}


def pressure_snapshot(**overrides):
    snapshot = {
        "memory_usage_percent": 82.0,
        "memory_available_bytes": 720_000_000,
        "memory_total_bytes": 4_000_000_000,
        "swap_total_bytes": 2_000_000_000,
        "swap_used_bytes": 800_000_000,
        "swap_usage_percent": 40.0,
        "swap_in_pages_per_second": 30.0,
        "swap_out_pages_per_second": 90.0,
        "swap_activity_pages_per_second": 120.0,
        "system_cpu_percent": 35.0,
        "iowait_cpu_percent": 15.0,
    }
    snapshot.update(overrides)
    return snapshot


def test_active_swapping_escalates_correlated_memory_pressure():
    anomaly = memory_pressure_anomaly(
        pressure_snapshot(), THRESHOLDS, "client"
    )

    assert anomaly.metric_name == "memory_pressure"
    assert anomaly.resource == "host-memory"
    assert anomaly.severity is AlertSeverity.CRITICAL
    assert anomaly.context["active_swapping"] is True
    assert "active swapping" in anomaly.description


def test_swap_occupancy_without_activity_is_not_called_thrashing():
    anomaly = memory_pressure_anomaly(
        pressure_snapshot(
            swap_activity_pages_per_second=0,
            swap_in_pages_per_second=0,
            swap_out_pages_per_second=0,
        ),
        THRESHOLDS,
        "client",
    )

    assert anomaly.severity is AlertSeverity.WARNING
    assert anomaly.context["active_swapping"] is False
    assert "active swapping" not in anomaly.description


def test_normal_memory_does_not_alert_even_if_old_swap_is_occupied():
    assert memory_pressure_anomaly(
        pressure_snapshot(
            memory_usage_percent=40,
            swap_activity_pages_per_second=0,
        ),
        THRESHOLDS,
        "client",
    ) is None


def test_cpu_anomaly_is_folded_into_active_swapping_incident():
    metrics = {
        "memory_percent": 82.0,
        "memory_pressure": pressure_snapshot(),
        "cpu_percent": 98.0,
        "filesystems": [],
    }
    config = {
        "thresholds": {
            "memory": THRESHOLDS,
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

    assert [item.metric_name for item in anomalies] == ["memory_pressure"]
    assert anomalies[0].context["cpu_usage_percent"] == 98.0


class FakeResponse:
    status_code = 200

    def __init__(self, value):
        self.value = value

    def json(self):
        return {
            "data": {
                "result": [
                    {"metric": {}, "value": [time.time(), str(self.value)]}
                ]
            }
        }


class FakePrometheusClient:
    async def get(self, url, params, timeout):
        query = params["query"]
        values = {
            "MemAvailable": 800,
            "MemTotal": 4000,
            "SwapTotal": 2000,
            "SwapFree": 1200,
            "pswpin": 30,
            "pswpout": 70,
            'mode="system"': 25,
            'mode="iowait"': 10,
        }
        return FakeResponse(next(
            value for marker, value in values.items() if marker in query
        ))


def test_prometheus_memory_snapshot_has_current_swap_rates():
    snapshot = asyncio.run(get_memory_pressure_metrics(
        "client:9100",
        FakePrometheusClient(),
        "http://prometheus:9090",
    ))

    assert snapshot["memory_usage_percent"] == 80.0
    assert snapshot["swap_usage_percent"] == 40.0
    assert snapshot["swap_activity_pages_per_second"] == 100.0
    assert snapshot["system_cpu_percent"] == 25.0
    assert snapshot["iowait_cpu_percent"] == 10.0


def test_memory_probe_is_fixed_bounded_and_omits_process_arguments():
    command = build_memory_pressure_command()

    assert "vmstat -w 1 3" in command
    assert "--sort=-rss | head -n 16" in command
    assert "/proc/pressure/memory" in command
    assert "journalctl -k --since '-10 minutes'" in command
    assert "args" not in command
