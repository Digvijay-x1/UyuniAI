from dataclasses import dataclass
from typing import List
from enum import Enum

from uyuni_ai_agent.prometheus_client import (
    get_memory_usage_percent,
    get_cpu_usage_percent,
    get_disk_usage_percent,
    get_apache_busy_workers_percent,
    get_apache_requests_per_sec,
    get_postgres_active_connections_percent,
    get_postgres_deadlocks_per_min,
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


def _check_threshold(value, thresholds, minion_id, metric_name, label):
    """Check a value against warning/critical thresholds. Returns Anomaly or None."""
    if value >= thresholds.get("critical", float("inf")):
        return Anomaly(
            minion_id, metric_name, value,
            thresholds["critical"],
            AlertSeverity.CRITICAL,
            f"{label} at {value:.1f}"
        )
    elif value >= thresholds.get("warning", float("inf")):
        return Anomaly(
            minion_id, metric_name, value,
            thresholds["warning"],
            AlertSeverity.WARNING,
            f"{label} at {value:.1f}"
        )
    return None


def check_all_metrics(instance, minion_id, apache_instance=None, postgres_instance=None):
    """Check all metrics for an instance against thresholds.
    Returns a list of Anomaly objects. Empty list means healthy.

    Apache and PostgreSQL checks are skipped if their exporter
    instances are not provided.
    """
    config = load_config()
    thresholds = config["thresholds"]
    anomalies = []

    # ── Node Exporter Checks ──

    # Memory check
    mem_usage = get_memory_usage_percent(instance)
    anomaly = _check_threshold(
        mem_usage, thresholds["memory"], minion_id,
        "memory", f"Memory usage at {mem_usage:.1f}%"
    )
    if anomaly:
        anomalies.append(anomaly)

    # CPU check
    cpu_usage = get_cpu_usage_percent(instance)
    anomaly = _check_threshold(
        cpu_usage, thresholds["cpu"], minion_id,
        "cpu", f"CPU usage at {cpu_usage:.1f}%"
    )
    if anomaly:
        anomalies.append(anomaly)

    # Disk check
    disk_usage = get_disk_usage_percent(instance)
    anomaly = _check_threshold(
        disk_usage, thresholds["disk"], minion_id,
        "disk", f"Disk usage at {disk_usage:.1f}%"
    )
    if anomaly:
        anomalies.append(anomaly)

    # ── Apache Exporter Checks ──

    if apache_instance:
        apache_thresholds = thresholds.get("apache", {})

        busy_pct = get_apache_busy_workers_percent(apache_instance)
        anomaly = _check_threshold(
            busy_pct,
            apache_thresholds.get("busy_workers_percent", {}),
            minion_id, "apache_busy_workers",
            f"Apache busy workers at {busy_pct:.1f}%"
        )
        if anomaly:
            anomalies.append(anomaly)

        rps = get_apache_requests_per_sec(apache_instance)
        anomaly = _check_threshold(
            rps,
            apache_thresholds.get("requests_per_sec", {}),
            minion_id, "apache_requests",
            f"Apache requests/sec at {rps:.1f}"
        )
        if anomaly:
            anomalies.append(anomaly)

    # ── PostgreSQL Exporter Checks ──

    if postgres_instance:
        pg_thresholds = thresholds.get("postgres", {})

        conn_pct = get_postgres_active_connections_percent(postgres_instance)
        anomaly = _check_threshold(
            conn_pct,
            pg_thresholds.get("active_connections_percent", {}),
            minion_id, "postgres_connections",
            f"PostgreSQL active connections at {conn_pct:.1f}%"
        )
        if anomaly:
            anomalies.append(anomaly)

        deadlocks = get_postgres_deadlocks_per_min(postgres_instance)
        anomaly = _check_threshold(
            deadlocks,
            pg_thresholds.get("deadlocks_per_min", {}),
            minion_id, "postgres_deadlocks",
            f"PostgreSQL deadlocks/min at {deadlocks:.1f}"
        )
        if anomaly:
            anomalies.append(anomaly)

    return anomalies
