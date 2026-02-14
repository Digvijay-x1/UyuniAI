from dataclasses import dataclass
from typing import List
from enum import Enum

from uyuni_ai_agent.prometheus_client import (
    get_memory_usage_percent,
    get_cpu_usage_percent,
    get_disk_usage_percent,
)
from uyuni_ai_agent.config import load_config


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Anomaly:
    minion_id: str
    metric_name: str
    current_value: float
    threshold: float
    severity: AlertSeverity
    description: str


def check_all_metrics(instance, minion_id):
    """Check all metrics for an instance against thresholds.
    Returns a list of Anomaly objects. Empty list means healthy.
    """
    config = load_config()
    thresholds = config["thresholds"]
    anomalies = []

    # Memory check
    mem_usage = get_memory_usage_percent(instance)
    if mem_usage >= thresholds["memory"]["critical"]:
        anomalies.append(Anomaly(
            minion_id, "memory", mem_usage,
            thresholds["memory"]["critical"],
            AlertSeverity.CRITICAL,
            f"Memory usage at {mem_usage:.1f}%"
        ))
    elif mem_usage >= thresholds["memory"]["warning"]:
        anomalies.append(Anomaly(
            minion_id, "memory", mem_usage,
            thresholds["memory"]["warning"],
            AlertSeverity.WARNING,
            f"Memory usage at {mem_usage:.1f}%"
        ))

    # CPU check
    cpu_usage = get_cpu_usage_percent(instance)
    if cpu_usage >= thresholds["cpu"]["critical"]:
        anomalies.append(Anomaly(
            minion_id, "cpu", cpu_usage,
            thresholds["cpu"]["critical"],
            AlertSeverity.CRITICAL,
            f"CPU usage at {cpu_usage:.1f}%"
        ))
    elif cpu_usage >= thresholds["cpu"]["warning"]:
        anomalies.append(Anomaly(
            minion_id, "cpu", cpu_usage,
            thresholds["cpu"]["warning"],
            AlertSeverity.WARNING,
            f"CPU usage at {cpu_usage:.1f}%"
        ))

    # Disk check
    disk_usage = get_disk_usage_percent(instance)
    if disk_usage >= thresholds["disk"]["critical"]:
        anomalies.append(Anomaly(
            minion_id, "disk", disk_usage,
            thresholds["disk"]["critical"],
            AlertSeverity.CRITICAL,
            f"Disk usage at {disk_usage:.1f}%"
        ))
    elif disk_usage >= thresholds["disk"]["warning"]:
        anomalies.append(Anomaly(
            minion_id, "disk", disk_usage,
            thresholds["disk"]["warning"],
            AlertSeverity.WARNING,
            f"Disk usage at {disk_usage:.1f}%"
        ))

    return anomalies
