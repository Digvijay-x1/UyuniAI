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

"""Prometheus queries with explicit missing, stale, and error semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import math
import time
from typing import Any

from uyuni_ai_agent.evidence import EvidenceStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrometheusQueryResult:
    """Raw Prometheus API result without stringly-typed error handling."""

    status: EvidenceStatus
    query: str
    source: str
    samples: list[dict[str, Any]] = field(default_factory=list)
    observed_at: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class MetricReading:
    """A parsed metric value and the state of the telemetry behind it."""

    name: str
    target: str
    exporter: str
    status: EvidenceStatus
    value: Any = None
    observed_at: float | None = None
    error: str | None = None

    @property
    def usable(self) -> bool:
        return self.status is EvidenceStatus.OK and self.value is not None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def _bounded_error(value: Any, limit: int = 500) -> str:
    rendered = str(value).strip().replace("\x00", "")
    return rendered[:limit]


def _latest_sample_timestamp(samples: list[dict[str, Any]]) -> float | None:
    timestamps: list[float] = []
    for sample in samples:
        raw_values = sample.get("values")
        if isinstance(raw_values, list) and raw_values:
            raw_timestamp = raw_values[-1][0]
        else:
            raw_value = sample.get("value")
            if not isinstance(raw_value, (list, tuple)) or not raw_value:
                continue
            raw_timestamp = raw_value[0]
        try:
            timestamps.append(float(raw_timestamp))
        except (TypeError, ValueError):
            continue
    return max(timestamps) if timestamps else None


def _parse_response(
    response: Any,
    *,
    query: str,
    source: str,
    max_sample_age_seconds: float | None,
    now: float | None,
) -> PrometheusQueryResult:
    if response.status_code != 200:
        return PrometheusQueryResult(
            status=EvidenceStatus.ERROR,
            query=query,
            source=source,
            error=(
                f"HTTP {response.status_code}: "
                f"{_bounded_error(getattr(response, 'text', ''))}"
            ),
        )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        return PrometheusQueryResult(
            status=EvidenceStatus.ERROR,
            query=query,
            source=source,
            error=f"invalid JSON: {_bounded_error(exc)}",
        )
    if payload.get("status", "success") != "success":
        return PrometheusQueryResult(
            status=EvidenceStatus.ERROR,
            query=query,
            source=source,
            error=_bounded_error(payload.get("error", "query failed")),
        )
    data = payload.get("data")
    samples = data.get("result") if isinstance(data, dict) else None
    if not isinstance(samples, list):
        return PrometheusQueryResult(
            status=EvidenceStatus.ERROR,
            query=query,
            source=source,
            error="response data.result is not a list",
        )
    if not samples:
        return PrometheusQueryResult(
            status=EvidenceStatus.MISSING,
            query=query,
            source=source,
            error="query returned no series",
        )

    observed_at = _latest_sample_timestamp(samples)
    if (
        max_sample_age_seconds is not None
        and observed_at is not None
        and (now if now is not None else time.time()) - observed_at
        > max_sample_age_seconds
    ):
        return PrometheusQueryResult(
            status=EvidenceStatus.STALE,
            query=query,
            source=source,
            samples=samples,
            observed_at=observed_at,
            error=(
                f"newest sample is older than {max_sample_age_seconds:.0f}s"
            ),
        )
    return PrometheusQueryResult(
        status=EvidenceStatus.OK,
        query=query,
        source=source,
        samples=samples,
        observed_at=observed_at,
    )


async def query_prometheus(
    prom_ql,
    client,
    prometheus_url,
    *,
    max_sample_age_seconds=300,
    now=None,
):
    """Execute an instant PromQL query and return a typed result."""
    url = f"{prometheus_url}/api/v1/query"
    logger.debug("querying prometheus: %s query=%s", url, prom_ql[:80])
    try:
        response = await client.get(
            url,
            params={"query": prom_ql},
            timeout=10,
        )
    except Exception as exc:
        return PrometheusQueryResult(
            status=EvidenceStatus.ERROR,
            query=prom_ql,
            source=url,
            error=f"connection failed: {_bounded_error(exc)}",
        )
    return _parse_response(
        response,
        query=prom_ql,
        source=url,
        max_sample_age_seconds=max_sample_age_seconds,
        now=now,
    )


async def query_prometheus_range(
    prom_ql,
    start,
    end,
    client,
    prometheus_url,
    step="1m",
):
    """Execute a range PromQL query and return a typed result."""
    url = f"{prometheus_url}/api/v1/query_range"
    try:
        response = await client.get(
            url,
            params={
                "query": prom_ql,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "step": step,
            },
            timeout=10,
        )
    except Exception as exc:
        return PrometheusQueryResult(
            status=EvidenceStatus.ERROR,
            query=prom_ql,
            source=url,
            error=f"connection failed: {_bounded_error(exc)}",
        )
    return _parse_response(
        response,
        query=prom_ql,
        source=url,
        max_sample_age_seconds=None,
        now=None,
    )


def _reading_from_first_sample(
    result: PrometheusQueryResult,
    *,
    name: str,
    target: str,
    exporter: str,
) -> MetricReading:
    if result.status is not EvidenceStatus.OK:
        return MetricReading(
            name=name,
            target=target,
            exporter=exporter,
            status=result.status,
            observed_at=result.observed_at,
            error=result.error,
        )
    try:
        value = float(result.samples[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return MetricReading(
            name=name,
            target=target,
            exporter=exporter,
            status=EvidenceStatus.ERROR,
            observed_at=result.observed_at,
            error=f"invalid sample: {_bounded_error(exc)}",
        )
    if not math.isfinite(value):
        return MetricReading(
            name=name,
            target=target,
            exporter=exporter,
            status=EvidenceStatus.ERROR,
            observed_at=result.observed_at,
            error=f"non-finite sample value: {value}",
        )
    return MetricReading(
        name=name,
        target=target,
        exporter=exporter,
        status=EvidenceStatus.OK,
        value=value,
        observed_at=result.observed_at,
    )


async def _scalar_reading(
    query,
    name,
    target,
    exporter,
    client,
    prometheus_url,
    max_sample_age_seconds,
):
    result = await query_prometheus(
        query,
        client,
        prometheus_url,
        max_sample_age_seconds=max_sample_age_seconds,
    )
    return _reading_from_first_sample(
        result,
        name=name,
        target=target,
        exporter=exporter,
    )


async def get_target_health(
    instance,
    exporter,
    client,
    prometheus_url,
    max_sample_age_seconds=300,
):
    return await _scalar_reading(
        f'up{{instance="{instance}"}}',
        f"{exporter}_up",
        instance,
        exporter,
        client,
        prometheus_url,
        max_sample_age_seconds,
    )


async def get_memory_usage_percent(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    query = (
        f'100 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} '
        f'/ node_memory_MemTotal_bytes{{instance="{instance}"}} * 100)'
    )
    return await _scalar_reading(
        query,
        "memory_percent",
        instance,
        "node_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )


async def get_memory_pressure_metrics(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    """Return memory values plus component-level telemetry state."""
    selector = f'instance="{instance}"'
    specs = {
        "memory_available_bytes": f"node_memory_MemAvailable_bytes{{{selector}}}",
        "memory_total_bytes": f"node_memory_MemTotal_bytes{{{selector}}}",
        "swap_total_bytes": f"node_memory_SwapTotal_bytes{{{selector}}}",
        "swap_free_bytes": f"node_memory_SwapFree_bytes{{{selector}}}",
        "swap_in_pages_per_second": (
            f"rate(node_vmstat_pswpin{{{selector}}}[2m])"
        ),
        "swap_out_pages_per_second": (
            f"rate(node_vmstat_pswpout{{{selector}}}[2m])"
        ),
        "system_cpu_percent": (
            f'avg(irate(node_cpu_seconds_total{{{selector},mode="system"}}[2m])) * 100'
        ),
        "iowait_cpu_percent": (
            f'avg(irate(node_cpu_seconds_total{{{selector},mode="iowait"}}[2m])) * 100'
        ),
    }
    readings = {}
    for name, query in specs.items():
        readings[name] = await _scalar_reading(
            query,
            name,
            instance,
            "node_exporter",
            client,
            prometheus_url,
            max_sample_age_seconds,
        )

    values = {
        name: reading.value if reading.usable else None
        for name, reading in readings.items()
    }
    available = values["memory_available_bytes"]
    total = values["memory_total_bytes"]
    swap_total = values["swap_total_bytes"]
    swap_free = values["swap_free_bytes"]
    swap_in = values["swap_in_pages_per_second"]
    swap_out = values["swap_out_pages_per_second"]

    memory_usage = None
    if available is not None and total is not None and total > 0:
        memory_usage = max(
            0.0,
            min(100.0, 100.0 - (available / total * 100.0)),
        )

    swap_used = None
    swap_usage = None
    if swap_total is not None and swap_free is not None:
        swap_used = max(0.0, swap_total - min(swap_free, swap_total))
        swap_usage = (
            max(0.0, min(100.0, swap_used / swap_total * 100.0))
            if swap_total > 0
            else 0.0
        )
    swap_activity = (
        swap_in + swap_out
        if swap_in is not None and swap_out is not None
        else None
    )
    return {
        "memory_usage_percent": memory_usage,
        "memory_available_bytes": available,
        "memory_total_bytes": total,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": swap_used,
        "swap_usage_percent": swap_usage,
        "swap_in_pages_per_second": swap_in,
        "swap_out_pages_per_second": swap_out,
        "swap_activity_pages_per_second": swap_activity,
        "system_cpu_percent": values["system_cpu_percent"],
        "iowait_cpu_percent": values["iowait_cpu_percent"],
        "_telemetry": {
            name: reading.as_dict() for name, reading in readings.items()
        },
    }


async def get_cpu_usage_percent(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    query = (
        "100 - (avg(irate(node_cpu_seconds_total"
        f'{{instance="{instance}",mode="idle"}}[5m])) * 100)'
    )
    return await _scalar_reading(
        query,
        "cpu_percent",
        instance,
        "node_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )


async def get_disk_usage_percent(
    instance,
    client,
    prometheus_url,
    mountpoint="/",
    max_sample_age_seconds=300,
):
    query = (
        "100 - (node_filesystem_avail_bytes"
        f'{{instance="{instance}",mountpoint="{mountpoint}"}} '
        "/ node_filesystem_size_bytes"
        f'{{instance="{instance}",mountpoint="{mountpoint}"}} * 100)'
    )
    return await _scalar_reading(
        query,
        f"filesystem_usage:{mountpoint}",
        instance,
        "node_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )


async def get_filesystem_usage_percent(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    """Return a reading containing every writable persistent filesystem."""
    excluded_fstypes = (
        "autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|"
        "fusectl|hugetlbfs|mqueue|overlay|proc|pstore|ramfs|securityfs|"
        "squashfs|sysfs|tracefs|tmpfs"
    )
    selector = f'instance="{instance}",fstype!~"{excluded_fstypes}"'
    query = (
        f"(100 - (node_filesystem_avail_bytes{{{selector}}} "
        f"/ node_filesystem_size_bytes{{{selector}}} * 100)) "
        "and on(instance,device,mountpoint) "
        f'(node_filesystem_readonly{{instance="{instance}"}} == 0)'
    )
    result = await query_prometheus(
        query,
        client,
        prometheus_url,
        max_sample_age_seconds=max_sample_age_seconds,
    )
    if result.status is not EvidenceStatus.OK:
        return MetricReading(
            name="filesystems",
            target=instance,
            exporter="node_exporter",
            status=result.status,
            observed_at=result.observed_at,
            error=result.error,
        )

    filesystems = []
    invalid_samples = 0
    for sample in result.samples:
        metric = sample.get("metric", {})
        try:
            usage = float(sample["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            invalid_samples += 1
            continue
        mountpoint = metric.get("mountpoint")
        if not mountpoint or not math.isfinite(usage) or usage < 0 or usage > 100:
            invalid_samples += 1
            continue
        filesystems.append({
            "mountpoint": mountpoint,
            "device": metric.get("device", "unknown"),
            "fstype": metric.get("fstype", "unknown"),
            "usage_percent": usage,
        })
    if not filesystems:
        return MetricReading(
            name="filesystems",
            target=instance,
            exporter="node_exporter",
            status=EvidenceStatus.ERROR,
            observed_at=result.observed_at,
            error=f"no valid filesystem samples ({invalid_samples} invalid)",
        )
    return MetricReading(
        name="filesystems",
        target=instance,
        exporter="node_exporter",
        status=EvidenceStatus.OK,
        value=sorted(filesystems, key=lambda item: item["mountpoint"]),
        observed_at=result.observed_at,
    )


async def get_apache_busy_workers_percent(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    busy = await _scalar_reading(
        f'apache_workers{{instance="{instance}",state="busy"}}',
        "apache_busy_workers",
        instance,
        "apache_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )
    idle = await _scalar_reading(
        f'apache_workers{{instance="{instance}",state="idle"}}',
        "apache_idle_workers",
        instance,
        "apache_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )
    failed = next((reading for reading in (busy, idle) if not reading.usable), None)
    if failed:
        return MetricReading(
            name="apache_busy_workers_percent",
            target=instance,
            exporter="apache_exporter",
            status=failed.status,
            observed_at=failed.observed_at,
            error=failed.error,
        )
    total = busy.value + idle.value
    if total <= 0:
        return MetricReading(
            name="apache_busy_workers_percent",
            target=instance,
            exporter="apache_exporter",
            status=EvidenceStatus.ERROR,
            observed_at=busy.observed_at,
            error="busy + idle workers is zero",
        )
    return MetricReading(
        name="apache_busy_workers_percent",
        target=instance,
        exporter="apache_exporter",
        status=EvidenceStatus.OK,
        value=busy.value / total * 100.0,
        observed_at=busy.observed_at,
    )


async def get_apache_requests_per_sec(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    return await _scalar_reading(
        f'rate(apache_accesses_total{{instance="{instance}"}}[5m])',
        "apache_requests_per_sec",
        instance,
        "apache_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )


async def get_postgres_active_connections_percent(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    backends = await _scalar_reading(
        f'sum(pg_stat_database_numbackends{{instance="{instance}"}})',
        "postgres_connections",
        instance,
        "postgres_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )
    maximum = await _scalar_reading(
        f'pg_settings_max_connections{{instance="{instance}"}}',
        "postgres_max_connections",
        instance,
        "postgres_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )
    failed = next(
        (reading for reading in (backends, maximum) if not reading.usable),
        None,
    )
    if failed:
        return MetricReading(
            name="postgres_active_connections_percent",
            target=instance,
            exporter="postgres_exporter",
            status=failed.status,
            observed_at=failed.observed_at,
            error=failed.error,
        )
    if maximum.value <= 0:
        return MetricReading(
            name="postgres_active_connections_percent",
            target=instance,
            exporter="postgres_exporter",
            status=EvidenceStatus.ERROR,
            observed_at=maximum.observed_at,
            error="max_connections is not positive",
        )
    return MetricReading(
        name="postgres_active_connections_percent",
        target=instance,
        exporter="postgres_exporter",
        status=EvidenceStatus.OK,
        value=backends.value / maximum.value * 100.0,
        observed_at=backends.observed_at,
    )


async def get_postgres_deadlocks_per_min(
    instance, client, prometheus_url, max_sample_age_seconds=300
):
    return await _scalar_reading(
        f'sum(rate(pg_stat_database_deadlocks{{instance="{instance}"}}[5m])) * 60',
        "postgres_deadlocks_per_min",
        instance,
        "postgres_exporter",
        client,
        prometheus_url,
        max_sample_age_seconds,
    )


async def get_all_metrics(
    instance,
    client,
    config,
    apache_instance=None,
    postgres_instance=None,
):
    """Return values plus a typed ``telemetry`` map for every query."""
    prometheus_url = config["prometheus"]["url"]
    max_age = config["prometheus"].get("max_sample_age_seconds", 300)
    telemetry: dict[str, dict[str, Any]] = {}

    node_up = await get_target_health(
        instance,
        "node_exporter",
        client,
        prometheus_url,
        max_age,
    )
    telemetry[node_up.name] = node_up.as_dict()

    filesystems_reading = await get_filesystem_usage_percent(
        instance, client, prometheus_url, max_age
    )
    telemetry[filesystems_reading.name] = filesystems_reading.as_dict()
    filesystems = (
        filesystems_reading.value if filesystems_reading.usable else []
    )
    root_usage = next(
        (
            fs["usage_percent"]
            for fs in filesystems
            if fs["mountpoint"] == "/"
        ),
        None,
    )

    memory_pressure = await get_memory_pressure_metrics(
        instance, client, prometheus_url, max_age
    )
    telemetry.update(memory_pressure.pop("_telemetry"))
    cpu = await get_cpu_usage_percent(
        instance, client, prometheus_url, max_age
    )
    telemetry[cpu.name] = cpu.as_dict()
    metrics = {
        "memory_percent": memory_pressure["memory_usage_percent"],
        "memory_pressure": memory_pressure,
        "cpu_percent": cpu.value if cpu.usable else None,
        "disk_percent": root_usage,
        "filesystems": filesystems,
        "telemetry": telemetry,
    }

    if apache_instance:
        apache_up = await get_target_health(
            apache_instance,
            "apache_exporter",
            client,
            prometheus_url,
            max_age,
        )
        busy = await get_apache_busy_workers_percent(
            apache_instance, client, prometheus_url, max_age
        )
        rps = await get_apache_requests_per_sec(
            apache_instance, client, prometheus_url, max_age
        )
        for reading in (apache_up, busy, rps):
            telemetry[reading.name] = reading.as_dict()
        metrics.update({
            "apache_busy_workers_percent": busy.value if busy.usable else None,
            "apache_requests_per_sec": rps.value if rps.usable else None,
        })

    if postgres_instance:
        postgres_up = await get_target_health(
            postgres_instance,
            "postgres_exporter",
            client,
            prometheus_url,
            max_age,
        )
        connections = await get_postgres_active_connections_percent(
            postgres_instance, client, prometheus_url, max_age
        )
        deadlocks = await get_postgres_deadlocks_per_min(
            postgres_instance, client, prometheus_url, max_age
        )
        for reading in (postgres_up, connections, deadlocks):
            telemetry[reading.name] = reading.as_dict()
        metrics.update({
            "postgres_active_connections_percent": (
                connections.value if connections.usable else None
            ),
            "postgres_deadlocks_per_min": (
                deadlocks.value if deadlocks.usable else None
            ),
        })

    return metrics
