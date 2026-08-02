# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dataclasses import dataclass, field
from fnmatch import fnmatch
import re
import time
from typing import Any, Dict, List, Optional
from enum import Enum

from uyuni_ai_agent.prometheus_client import get_all_metrics
from uyuni_ai_agent.postgres_inspection import parse_postgres_lock_pairs


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
    service_name: Optional[str] = None
    resource: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def identity_key(self):
        """Stable identity used to deduplicate repeated polling results."""
        return (
            self.minion_id,
            self.metric_name,
            self.service_name or "",
            self.resource or "",
        )


def _check_threshold(value, thresholds, minion_id, metric_name, label):
    """Check a value against warning/critical thresholds. Returns Anomaly or None."""
    if value is None:
        return None
    value = float(value)
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


def parse_failed_systemd_services(output):
    """Parse failed and ``activating/auto-restart`` systemd units.

    Returns dictionaries containing ``name`` and ``description``. Salt errors
    and unexpected lines are ignored rather than being turned into false
    service-down alerts.
    """
    if not isinstance(output, str):
        return []

    stripped = output.strip()
    if not stripped or stripped.startswith("Salt API call failed:"):
        return []

    services = []
    for raw_line in stripped.splitlines():
        line = raw_line.strip().lstrip("●").strip()
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load_state, active_state, sub_state = parts[:4]
        is_failed = active_state == "failed"
        is_restart_loop = (
            active_state == "activating" and sub_state == "auto-restart"
        )
        if unit.endswith(".service") and load_state == "loaded" and (
            is_failed or is_restart_loop
        ):
            services.append({
                "name": unit,
                "description": parts[4] if len(parts) == 5 else unit,
                "sub_state": sub_state,
                "active_state": active_state,
            })
    return services


def _salt_inspection_failure(output):
    """Return a bounded failure message, or None for valid command output."""
    if output is False or output is None:
        return "Salt minion returned no command result"
    if not isinstance(output, str):
        return f"Salt returned unexpected {type(output).__name__} output"
    stripped = output.strip()
    failure_markers = (
        "salt api call failed:",
        "minion did not return",
        "no response from any minions",
    )
    if any(marker in stripped.lower() for marker in failure_markers):
        return stripped[:500]
    return None


def _salt_telemetry_anomaly(minion_id, check, failure):
    return Anomaly(
        minion_id=minion_id,
        metric_name="telemetry_unavailable",
        current_value=1.0,
        threshold=1.0,
        severity=AlertSeverity.WARNING,
        description=f"Salt inspection telemetry for {minion_id} is unavailable",
        resource=f"telemetry:salt_inspection:{minion_id}",
        context={
            "source": "salt",
            "exporter": "salt_inspection",
            "target": minion_id,
            "observations": [{
                "name": check,
                "status": "error",
                "error": failure,
            }],
        },
    )


async def check_failed_services(minion_id, salt_client, config):
    """Discover failed systemd services without a per-service allowlist."""
    service_cfg = config.get("service_monitoring", {})
    if not service_cfg.get("enabled", True):
        return []

    output = await salt_client.failed_systemd_services(minion_id)
    failure = _salt_inspection_failure(output)
    if failure:
        return [_salt_telemetry_anomaly(
            minion_id, "systemd_service_discovery", failure
        )]
    ignored = service_cfg.get("ignored_units", [])
    anomalies = []
    for service in parse_failed_systemd_services(output):
        name = service["name"]
        if any(fnmatch(name, pattern) for pattern in ignored):
            continue
        state_label = (
            "in an automatic restart loop"
            if service["active_state"] == "activating"
            else "in failed state"
        )
        anomalies.append(Anomaly(
            minion_id=minion_id,
            metric_name="service_down",
            current_value=1.0,
            threshold=1.0,
            severity=AlertSeverity.CRITICAL,
            description=f"Systemd service {name} is {state_label}",
            service_name=name,
            context={
                "unit_description": service["description"],
                "active_state": service["active_state"],
                "sub_state": service["sub_state"],
            },
        ))
    return anomalies


def postgres_blocking_anomalies(lock_pairs, thresholds, minion_id):
    """Group PostgreSQL lock waits by database and create stable anomalies."""
    warning = max(0, int(thresholds.get("warning", 5)))
    critical = max(warning, int(thresholds.get("critical", 30)))
    by_database = {}

    for pair in lock_pairs:
        if pair["blocked_seconds"] < warning:
            continue
        by_database.setdefault(pair["database"], []).append(pair)

    anomalies = []
    for database, pairs in sorted(by_database.items()):
        blocked_pids = sorted({pair["blocked_pid"] for pair in pairs})
        blocker_pids = sorted({pair["blocker_pid"] for pair in pairs})
        longest_wait = max(pair["blocked_seconds"] for pair in pairs)
        severity = (
            AlertSeverity.CRITICAL
            if longest_wait >= critical
            else AlertSeverity.WARNING
        )
        threshold = critical if severity is AlertSeverity.CRITICAL else warning
        query_word = "query" if len(blocked_pids) == 1 else "queries"
        anomalies.append(Anomaly(
            minion_id=minion_id,
            metric_name="postgres_blocked_transaction",
            current_value=float(longest_wait),
            threshold=float(threshold),
            severity=severity,
            description=(
                f"PostgreSQL database {database} has {len(blocked_pids)} "
                f"{query_word} blocked by a transaction for up to "
                f"{longest_wait}s"
            ),
            service_name="postgresql",
            resource=f"postgresql:{database}",
            context={
                "database": database,
                "blocked_pids": blocked_pids,
                "blocker_pids": blocker_pids,
                "blocked_pairs": pairs,
            },
        ))
    return anomalies


_WEB_APPLICATION_HINT = re.compile(
    r"(apache|httpd|web|backend|frontend|api|php|cgi|wsgi|gunicorn)",
    re.IGNORECASE,
)
_DEFAULT_APACHE_TRAFFIC_THRESHOLD = 500.0


def _is_apache_dependency_candidate(
    anomaly,
    traffic_spike_threshold=_DEFAULT_APACHE_TRAFFIC_THRESHOLD,
):
    requests_per_second = anomaly.context.get("requests_per_second")
    return (
        anomaly.metric_name == "apache_busy_workers"
        and requests_per_second is not None
        and float(requests_per_second) < float(traffic_spike_threshold)
    )


def _is_postgres_dependency_candidate(anomaly):
    return (
        anomaly.metric_name == "postgres_blocked_transaction"
        and any(
            _WEB_APPLICATION_HINT.search(
                str(pair.get("blocked_application") or "")
            )
            for pair in anomaly.context.get("blocked_pairs", [])
        )
    )


def correlate_dependency_anomalies(
    anomalies,
    dependency_edges=None,
    apache_traffic_threshold=_DEFAULT_APACHE_TRAFFIC_THRESHOLD,
):
    """Collapse an evidenced Apache/PostgreSQL symptom pair into one incident.

    Correlation is intentionally conservative: Apache must be worker-saturated
    without a traffic-rate alert, and a blocked PostgreSQL application name
    must identify a web/application tier. The investigation still validates
    the process, port, proxy and database relationship from live evidence.
    Cross-minion candidates additionally require an explicit topology edge;
    same-minion candidates can be inferred without one.
    """
    apache_indexes = [
        index
        for index, anomaly in enumerate(anomalies)
        if _is_apache_dependency_candidate(anomaly, apache_traffic_threshold)
    ]
    postgres_indexes = [
        index
        for index, anomaly in enumerate(anomalies)
        if _is_postgres_dependency_candidate(anomaly)
    ]
    if not apache_indexes or not postgres_indexes:
        return anomalies

    dependency_edges = dependency_edges or []
    selected_pair = None
    for apache_index in apache_indexes:
        apache_candidate = anomalies[apache_index]
        for postgres_index in postgres_indexes:
            postgres_candidate = anomalies[postgres_index]
            same_minion = (
                apache_candidate.minion_id == postgres_candidate.minion_id
            )
            configured_edge = any(
                edge.get("apache_minion") == apache_candidate.minion_id
                and edge.get("postgres_minion") == postgres_candidate.minion_id
                for edge in dependency_edges
                if isinstance(edge, dict)
            )
            if same_minion or configured_edge:
                selected_pair = (apache_index, postgres_index)
                break
        if selected_pair:
            break

    if selected_pair is None:
        return anomalies

    apache_index, postgres_index = selected_pair
    apache = anomalies[apache_index]
    postgres = anomalies[postgres_index]
    severity = (
        AlertSeverity.CRITICAL
        if AlertSeverity.CRITICAL in {apache.severity, postgres.severity}
        else AlertSeverity.WARNING
    )
    database = postgres.context.get("database", "unknown")
    cross_minion = apache.minion_id != postgres.minion_id
    if cross_minion:
        description = (
            f"Correlated PostgreSQL lock waits in {database} on "
            f"{postgres.minion_id} and Apache worker saturation at "
            f"{apache.current_value:.1f}% on {apache.minion_id}"
        )
        resource = (
            f"dependency-chain:{postgres.minion_id}:postgresql:{database}"
            f"->{apache.minion_id}:apache"
        )
    else:
        description = (
            f"Correlated PostgreSQL lock waits in {database} and Apache "
            f"worker saturation at {apache.current_value:.1f}%"
        )
        resource = f"dependency-chain:postgresql:{database}->apache"

    correlated = Anomaly(
        minion_id=apache.minion_id,
        metric_name="postgres_apache_chain",
        current_value=postgres.current_value,
        threshold=postgres.threshold,
        severity=severity,
        description=description,
        service_name="postgresql->apache2",
        resource=resource,
        context={
            **postgres.context,
            "apache_minion_id": apache.minion_id,
            "postgres_minion_id": postgres.minion_id,
            "correlated_minion_ids": [
                postgres.minion_id,
                apache.minion_id,
            ],
            "apache_busy_workers_percent": apache.current_value,
            "apache_requests_per_second": float(
                apache.context.get("requests_per_second", 0.0)
            ),
            "correlated_metric_names": [
                apache.metric_name,
                postgres.metric_name,
            ],
        },
    )

    result = []
    insertion_index = min(apache_index, postgres_index)
    for index, anomaly in enumerate(anomalies):
        if index == insertion_index:
            result.append(correlated)
        if index not in {apache_index, postgres_index}:
            result.append(anomaly)
    return result


class DependencyCorrelationWindow:
    """Hold cross-minion candidates briefly for adjacent scrape cycles.

    Prometheus targets are not guaranteed to scrape at the same instant. A
    PostgreSQL lock can therefore be visible one agent cycle before the
    downstream Apache BusyWorkers metric. Candidates on explicitly configured
    dependency edges are held for a bounded interval; if the counterpart
    appears, one correlated incident is returned. If it never appears, the
    original anomaly is released after the grace period.

    Only low-throughput Apache worker saturation and PostgreSQL waits owned by
    a web/backend-like application are delayed. Unrelated anomalies and
    traffic spikes pass through immediately.
    """

    def __init__(
        self,
        grace_seconds=90,
        apache_traffic_threshold=_DEFAULT_APACHE_TRAFFIC_THRESHOLD,
    ):
        self.grace_seconds = max(0.0, float(grace_seconds))
        self.apache_traffic_threshold = max(
            0.0,
            float(apache_traffic_threshold),
        )
        self._first_seen = {}
        self.last_held_count = 0

    def _is_cross_minion_candidate(self, anomaly, dependency_edges):
        for edge in dependency_edges:
            if not isinstance(edge, dict):
                continue
            postgres_minion = edge.get("postgres_minion")
            apache_minion = edge.get("apache_minion")
            if not postgres_minion or not apache_minion:
                continue
            if (
                anomaly.minion_id == postgres_minion
                and _is_postgres_dependency_candidate(anomaly)
            ):
                return True
            if (
                anomaly.minion_id == apache_minion
                and _is_apache_dependency_candidate(
                    anomaly,
                    self.apache_traffic_threshold,
                )
            ):
                return True
        return False

    def correlate(self, anomalies, dependency_edges=None, now=None):
        dependency_edges = dependency_edges or []
        now = time.monotonic() if now is None else float(now)
        self.last_held_count = 0

        correlated = correlate_dependency_anomalies(
            anomalies,
            dependency_edges,
            self.apache_traffic_threshold,
        )
        if any(
            anomaly.metric_name == "postgres_apache_chain"
            for anomaly in correlated
        ):
            # The current live snapshots contain both sides, so no older
            # candidate should survive and create a later standalone alert.
            self._first_seen.clear()
            return correlated

        candidate_keys = {
            anomaly.identity_key()
            for anomaly in anomalies
            if self._is_cross_minion_candidate(anomaly, dependency_edges)
        }
        for stale_key in set(self._first_seen) - candidate_keys:
            self._first_seen.pop(stale_key, None)

        result = []
        for anomaly in anomalies:
            key = anomaly.identity_key()
            if key not in candidate_keys or self.grace_seconds == 0:
                result.append(anomaly)
                continue

            first_seen = self._first_seen.setdefault(key, now)
            if now - first_seen < self.grace_seconds:
                self.last_held_count += 1
                continue
            result.append(anomaly)

        return result


async def check_postgres_blocked_transactions(minion_id, salt_client, config):
    """Detect persistent lock waits across every database in one cluster."""
    postgres_cfg = config.get("postgres_lock_monitoring", {})
    if not postgres_cfg.get("enabled", True):
        return []

    output = await salt_client.postgres_blocking_activity(minion_id)
    failure = _salt_inspection_failure(output)
    if failure:
        return [_salt_telemetry_anomaly(
            minion_id, "postgres_lock_discovery", failure
        )]
    pairs = parse_postgres_lock_pairs(output)
    thresholds = (
        config.get("thresholds", {})
        .get("postgres", {})
        .get("blocked_transaction_seconds", {})
    )
    return postgres_blocking_anomalies(pairs, thresholds, minion_id)


def filesystem_anomalies(filesystems, thresholds, minion_id):
    """Build mount-specific anomalies from node_exporter filesystem samples."""
    anomalies = []
    for filesystem in filesystems:
        disk_usage = filesystem["usage_percent"]
        mountpoint = filesystem["mountpoint"]
        anomaly = _check_threshold(
            disk_usage,
            thresholds,
            minion_id,
            "disk",
            f"Filesystem {mountpoint} usage",
        )
        if anomaly:
            anomaly.resource = mountpoint
            anomaly.context.update({
                "mountpoint": mountpoint,
                "device": filesystem["device"],
                "fstype": filesystem["fstype"],
            })
            anomalies.append(anomaly)
    return anomalies


def memory_pressure_anomaly(memory_metrics, thresholds, minion_id):
    """Build one correlated memory-pressure anomaly from host signals.

    Swap usage is retained state and does not prove current thrashing. Active
    pswpin/pswpout rates are tracked separately and are required before a CPU
    alert can be treated as a secondary effect of swapping.
    """
    raw_usage = memory_metrics.get("memory_usage_percent")
    if raw_usage is None:
        return None
    usage = float(raw_usage)
    warning = float(thresholds.get("warning", float("inf")))
    critical = float(thresholds.get("critical", float("inf")))
    if usage < warning:
        return None

    pressure_thresholds = thresholds.get("pressure", {})
    activity_thresholds = pressure_thresholds.get(
        "swap_activity_pages_per_second", {}
    )
    swap_usage_thresholds = pressure_thresholds.get(
        "swap_usage_percent", {}
    )
    raw_activity = memory_metrics.get("swap_activity_pages_per_second")
    raw_swap_usage = memory_metrics.get("swap_usage_percent")
    activity = float(raw_activity) if raw_activity is not None else 0.0
    swap_usage = float(raw_swap_usage) if raw_swap_usage is not None else 0.0
    activity_warning = float(activity_thresholds.get("warning", 1.0))
    activity_critical = float(activity_thresholds.get("critical", 100.0))
    swap_usage_critical = float(swap_usage_thresholds.get("critical", 25.0))
    active_swapping = activity >= activity_warning

    is_critical = (
        usage >= critical
        or (active_swapping and activity >= activity_critical)
        or (active_swapping and swap_usage >= swap_usage_critical)
    )
    severity = (
        AlertSeverity.CRITICAL if is_critical else AlertSeverity.WARNING
    )
    threshold = critical if is_critical and usage >= critical else warning
    if active_swapping:
        description = (
            f"Host memory usage is {usage:.1f}% with active swapping at "
            f"{activity:.1f} pages/s"
        )
    else:
        description = f"Host memory usage is {usage:.1f}%"

    return Anomaly(
        minion_id=minion_id,
        metric_name="memory_pressure",
        current_value=usage,
        threshold=threshold,
        severity=severity,
        description=description,
        resource="host-memory",
        context={
            **memory_metrics,
            "active_swapping": active_swapping,
        },
    )


_REQUIRED_TELEMETRY = {
    "node_exporter": {
        "memory_available_bytes",
        "memory_total_bytes",
        "cpu_percent",
        "filesystems",
    },
    "apache_exporter": {
        "apache_busy_workers_percent",
        "apache_requests_per_sec",
    },
    "postgres_exporter": {
        "postgres_active_connections_percent",
        "postgres_deadlocks_per_min",
    },
}


def telemetry_anomalies(metrics, minion_id):
    """Expose monitoring blind spots instead of interpreting them as zero."""
    observations = metrics.get("telemetry") or {}
    anomalies = []
    for exporter, required_names in _REQUIRED_TELEMETRY.items():
        exporter_observations = {
            name: observation
            for name, observation in observations.items()
            if observation.get("exporter") == exporter
        }
        if not exporter_observations:
            continue

        up = exporter_observations.get(f"{exporter}_up")
        target = next(iter(exporter_observations.values())).get(
            "target", "unknown"
        )
        failures = []
        if up is None:
            failures.append({
                "name": f"{exporter}_up",
                "status": "missing",
                "error": "target health query was not collected",
            })
        elif up.get("status") != "ok":
            failures.append({"name": f"{exporter}_up", **up})
        elif float(up.get("value", 0.0)) != 1.0:
            failures.append({
                "name": f"{exporter}_up",
                **up,
                "status": "error",
                "error": "Prometheus target reports up=0",
            })
        else:
            for name in sorted(required_names):
                observation = exporter_observations.get(name)
                if observation is None or observation.get("status") != "ok":
                    failures.append({
                        "name": name,
                        **(observation or {
                            "status": "missing",
                            "error": "metric was not collected",
                        }),
                    })
        if not failures:
            continue

        statuses = sorted({item.get("status", "error") for item in failures})
        anomaly = Anomaly(
            minion_id=minion_id,
            metric_name="telemetry_unavailable",
            current_value=1.0,
            threshold=1.0,
            severity=AlertSeverity.WARNING,
            description=(
                f"{exporter} telemetry for {target} is unavailable "
                f"({', '.join(statuses)})"
            ),
            resource=f"telemetry:{exporter}:{target}",
            context={
                "exporter": exporter,
                "target": target,
                "observations": failures,
            },
        )
        anomalies.append(anomaly)
    return anomalies


async def check_all_metrics(
    instance,
    minion_id,
    client,
    config,
    apache_instance=None,
    postgres_instance=None,
    metrics=None,
):
    """Check all metrics for an instance against thresholds.
    Returns a list of Anomaly objects. Empty list means healthy.

    Apache and PostgreSQL checks are skipped if their exporter
    instances are not provided. Metrics are checked sequentially
    (no inner parallelism).
    """
    thresholds = config["thresholds"]
    anomalies = []

    if metrics is None:
        metrics = await get_all_metrics(
            instance,
            client,
            config,
            apache_instance=apache_instance,
            postgres_instance=postgres_instance,
        )

    anomalies.extend(telemetry_anomalies(metrics, minion_id))

    # ── Node Exporter Checks ──

    # Memory check
    memory_metrics = metrics.get("memory_pressure") or {
        "memory_usage_percent": metrics.get("memory_percent"),
        "swap_activity_pages_per_second": None,
        "swap_usage_percent": None,
    }
    memory_anomaly = memory_pressure_anomaly(
        memory_metrics, thresholds["memory"], minion_id
    )
    if memory_anomaly:
        memory_anomaly.context["cpu_usage_percent"] = metrics.get(
            "cpu_percent"
        )
        anomalies.append(memory_anomaly)

    # CPU check
    cpu_usage = metrics.get("cpu_percent")
    anomaly = _check_threshold(
        cpu_usage, thresholds["cpu"], minion_id,
        "cpu", "CPU usage"
    )
    if anomaly:
        anomaly.resource = "host-cpu"
        anomaly.context.update({
            "cpu_usage_percent": cpu_usage,
            "memory_pressure": memory_metrics,
        })
    if anomaly and not (
        memory_anomaly
        and memory_anomaly.context.get("active_swapping", False)
    ):
        anomalies.append(anomaly)

    # Filesystem checks. Mountpoints are discovered from node_exporter so new
    # filesystems do not require per-service or per-mount configuration.
    filesystems = metrics.get("filesystems", [])
    anomalies.extend(
        filesystem_anomalies(filesystems, thresholds["disk"], minion_id)
    )

    # ── Apache Exporter Checks ──

    if apache_instance:
        apache_thresholds = thresholds.get("apache", {})

        busy_pct = metrics.get("apache_busy_workers_percent")
        anomaly = _check_threshold(
            busy_pct,
            apache_thresholds.get("busy_workers_percent", {}),
            minion_id, "apache_busy_workers",
            "Apache busy workers"
        )
        if anomaly:
            anomaly.service_name = "apache2"
            anomaly.resource = "apache:workers"
            anomaly.context.update({
                "apache_instance": apache_instance,
                "busy_workers_percent": busy_pct,
                "requests_per_second": metrics.get(
                    "apache_requests_per_sec"
                ),
            })
            anomalies.append(anomaly)

        rps = metrics.get("apache_requests_per_sec")
        anomaly = _check_threshold(
            rps,
            apache_thresholds.get("requests_per_sec", {}),
            minion_id, "apache_requests",
            "Apache requests per second"
        )
        if anomaly:
            anomaly.service_name = "apache2"
            anomaly.resource = "apache:traffic"
            anomaly.context.update({
                "apache_instance": apache_instance,
                "busy_workers_percent": busy_pct,
                "requests_per_second": rps,
            })
            anomalies.append(anomaly)

    # ── PostgreSQL Exporter Checks ──

    if postgres_instance:
        pg_thresholds = thresholds.get("postgres", {})

        conn_pct = metrics.get("postgres_active_connections_percent")
        anomaly = _check_threshold(
            conn_pct,
            pg_thresholds.get("active_connections_percent", {}),
            minion_id, "postgres_connections",
            "PostgreSQL connection utilization"
        )
        if anomaly:
            anomaly.service_name = "postgresql"
            anomaly.resource = "postgresql:cluster"
            anomaly.context.update({
                "postgres_instance": postgres_instance,
                "connection_utilization_percent": conn_pct,
            })
            anomalies.append(anomaly)

        deadlocks = metrics.get("postgres_deadlocks_per_min")
        anomaly = _check_threshold(
            deadlocks,
            pg_thresholds.get("deadlocks_per_min", {}),
            minion_id, "postgres_deadlocks",
            "PostgreSQL deadlocks/min"
        )
        if anomaly:
            anomalies.append(anomaly)

    return anomalies
