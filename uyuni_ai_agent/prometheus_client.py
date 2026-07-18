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

import logging

logger = logging.getLogger(__name__)


async def query_prometheus(prom_ql, client, prometheus_url):
    """Execute an instant PromQL query and return the results."""
    URL = f"{prometheus_url}/api/v1/query"
    logger.debug("querying prometheus: %s query=%s", URL, prom_ql[:80])

    params = {
        'query': prom_ql
    }

    try:
        response = await client.get(URL, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json()['data']['result']
            return results
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Connection Failed: {str(e)}"


async def query_prometheus_range(prom_ql, start, end, client, prometheus_url, step="1m"):
    """Execute a range PromQL query over a time window."""
    URL = f"{prometheus_url}/api/v1/query_range"

    params = {
        'query': prom_ql,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'step': step
    }

    try:
        response = await client.get(URL, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()['data']['result']
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Connection Failed: {str(e)}"


# ── Node Exporter Metrics ──

async def get_memory_usage_percent(instance, client, prometheus_url):
    """Get current memory usage percentage for an instance."""
    query = (
        f'100 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} '
        f'/ node_memory_MemTotal_bytes{{instance="{instance}"}} * 100)'
    )
    result = await query_prometheus(query, client, prometheus_url)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


async def _get_first_sample_value(query, client, prometheus_url):
    """Return the first finite-looking Prometheus sample or zero."""
    result = await query_prometheus(query, client, prometheus_url)
    if isinstance(result, list) and result:
        try:
            value = float(result[0]["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            return 0.0
        if value >= 0:
            return value
    return 0.0


async def get_memory_pressure_metrics(instance, client, prometheus_url):
    """Return memory, swap activity, and secondary CPU-pressure signals.

    Swap usage alone is not proof of current thrashing because inactive pages
    can remain swapped out after an incident. The pswpin/pswpout rates provide
    the current activity needed for that distinction.
    """
    selector = f'instance="{instance}"'
    available = await _get_first_sample_value(
        f'node_memory_MemAvailable_bytes{{{selector}}}',
        client,
        prometheus_url,
    )
    total = await _get_first_sample_value(
        f'node_memory_MemTotal_bytes{{{selector}}}',
        client,
        prometheus_url,
    )
    swap_total = await _get_first_sample_value(
        f'node_memory_SwapTotal_bytes{{{selector}}}',
        client,
        prometheus_url,
    )
    swap_free = await _get_first_sample_value(
        f'node_memory_SwapFree_bytes{{{selector}}}',
        client,
        prometheus_url,
    )
    swap_in = await _get_first_sample_value(
        f'rate(node_vmstat_pswpin{{{selector}}}[2m])',
        client,
        prometheus_url,
    )
    swap_out = await _get_first_sample_value(
        f'rate(node_vmstat_pswpout{{{selector}}}[2m])',
        client,
        prometheus_url,
    )
    system_cpu = await _get_first_sample_value(
        (
            f'avg(irate(node_cpu_seconds_total{{{selector},'
            'mode="system"}[2m])) * 100'
        ),
        client,
        prometheus_url,
    )
    iowait_cpu = await _get_first_sample_value(
        (
            f'avg(irate(node_cpu_seconds_total{{{selector},'
            'mode="iowait"}[2m])) * 100'
        ),
        client,
        prometheus_url,
    )

    memory_usage = (
        max(0.0, min(100.0, 100.0 - (available / total * 100.0)))
        if total > 0
        else 0.0
    )
    swap_used = max(0.0, swap_total - min(swap_free, swap_total))
    swap_usage = (
        max(0.0, min(100.0, swap_used / swap_total * 100.0))
        if swap_total > 0
        else 0.0
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
        "swap_activity_pages_per_second": swap_in + swap_out,
        "system_cpu_percent": system_cpu,
        "iowait_cpu_percent": iowait_cpu,
    }


async def get_cpu_usage_percent(instance, client, prometheus_url):
    """Get current CPU usage percentage for an instance."""
    query = (
        f'100 - (avg(irate(node_cpu_seconds_total'
        f'{{instance="{instance}",mode="idle"}}[5m])) * 100)'
    )
    result = await query_prometheus(query, client, prometheus_url)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


async def get_disk_usage_percent(instance, client, prometheus_url, mountpoint="/"):
    """Get disk usage percentage for a mountpoint on an instance."""
    query = (
        f'100 - (node_filesystem_avail_bytes'
        f'{{instance="{instance}",mountpoint="{mountpoint}"}} '
        f'/ node_filesystem_size_bytes'
        f'{{instance="{instance}",mountpoint="{mountpoint}"}} * 100)'
    )
    result = await query_prometheus(query, client, prometheus_url)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


async def get_filesystem_usage_percent(instance, client, prometheus_url):
    """Return usage for every writable, persistent filesystem on an instance.

    Filesystems are discovered from node_exporter labels, so adding or removing
    a mount does not require an agent configuration change.
    """
    excluded_fstypes = (
        "autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|"
        "fusectl|hugetlbfs|mqueue|overlay|proc|pstore|ramfs|securityfs|"
        "squashfs|sysfs|tracefs|tmpfs"
    )
    selector = (
        f'instance="{instance}",'
        f'fstype!~"{excluded_fstypes}"'
    )
    query = (
        f'(100 - (node_filesystem_avail_bytes{{{selector}}} '
        f'/ node_filesystem_size_bytes{{{selector}}} * 100)) '
        f'and on(instance,device,mountpoint) '
        f'(node_filesystem_readonly{{instance="{instance}"}} == 0)'
    )
    result = await query_prometheus(query, client, prometheus_url)
    if not isinstance(result, list):
        return []

    filesystems = []
    for sample in result:
        metric = sample.get("metric", {})
        try:
            usage = float(sample["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        mountpoint = metric.get("mountpoint")
        if not mountpoint or usage < 0 or usage > 100:
            continue
        filesystems.append({
            "mountpoint": mountpoint,
            "device": metric.get("device", "unknown"),
            "fstype": metric.get("fstype", "unknown"),
            "usage_percent": usage,
        })
    return sorted(filesystems, key=lambda item: item["mountpoint"])


# ── Apache Exporter Metrics ──

async def get_apache_busy_workers_percent(instance, client, prometheus_url):
    """Get Apache busy workers as a percentage of total workers.

    Uses apache_workers{state="busy"} / (busy + idle) * 100
    from the apache_exporter on :9117.
    """
    busy_query = f'apache_workers{{instance="{instance}",state="busy"}}'
    idle_query = f'apache_workers{{instance="{instance}",state="idle"}}'

    busy_result = await query_prometheus(busy_query, client, prometheus_url)
    idle_result = await query_prometheus(idle_query, client, prometheus_url)

    busy = 0.0
    idle = 0.0
    if isinstance(busy_result, list) and busy_result:
        busy = float(busy_result[0]['value'][1])
    if isinstance(idle_result, list) and idle_result:
        idle = float(idle_result[0]['value'][1])

    total = busy + idle
    if total == 0:
        return 0.0
    return (busy / total) * 100


async def get_apache_requests_per_sec(instance, client, prometheus_url):
    """Get Apache request rate (requests per second over 5m window).

    Uses rate(apache_accesses_total[5m]) from the apache_exporter.
    """
    query = f'rate(apache_accesses_total{{instance="{instance}"}}[5m])'
    result = await query_prometheus(query, client, prometheus_url)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


# ── PostgreSQL Exporter Metrics ──

async def get_postgres_active_connections_percent(instance, client, prometheus_url):
    """Get total PostgreSQL connections as a percentage of max_connections.

    Uses sum(pg_stat_database_numbackends) for total connections and
    pg_settings_max_connections from the postgres_exporter on :9187.
    Counts ALL connections (active + idle + idle-in-transaction) since
    connection exhaustion is the real concern regardless of state.
    """
    backends_query = (
        f'sum(pg_stat_database_numbackends{{instance="{instance}"}})'
    )
    max_query = (
        f'pg_settings_max_connections{{instance="{instance}"}}'
    )

    backends_result = await query_prometheus(backends_query, client, prometheus_url)
    max_result = await query_prometheus(max_query, client, prometheus_url)

    backends = 0.0
    max_conn = 100.0  # safe default
    if isinstance(backends_result, list) and backends_result:
        backends = float(backends_result[0]['value'][1])
    if isinstance(max_result, list) and max_result:
        max_conn = float(max_result[0]['value'][1])

    if max_conn == 0:
        return 0.0
    return (backends / max_conn) * 100


async def get_postgres_deadlocks_per_min(instance, client, prometheus_url):
    """Get PostgreSQL deadlock rate (deadlocks per minute over 5m window).

    Uses rate(pg_stat_database_deadlocks[5m]) * 60 from the postgres_exporter.
    """
    query = (
        f'sum(rate(pg_stat_database_deadlocks{{instance="{instance}"}}[5m])) * 60'
    )
    result = await query_prometheus(query, client, prometheus_url)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


# ── Combined Metrics ──

async def get_all_metrics(instance, client, config, apache_instance=None, postgres_instance=None):
    """Get all key metrics for an instance. Returns a dict summary.

    Includes node_exporter metrics always. Apache and PostgreSQL metrics
    are included only if their exporter instances are configured.

    Metrics are fetched sequentially (no inner parallelism).
    """
    prometheus_url = config["prometheus"]["url"]
    filesystems = await get_filesystem_usage_percent(
        instance, client, prometheus_url
    )
    root_usage = next(
        (
            fs["usage_percent"]
            for fs in filesystems
            if fs["mountpoint"] == "/"
        ),
        0.0,
    )
    memory_pressure = await get_memory_pressure_metrics(
        instance, client, prometheus_url
    )
    metrics = {
        "memory_percent": memory_pressure["memory_usage_percent"],
        "memory_pressure": memory_pressure,
        "cpu_percent": await get_cpu_usage_percent(instance, client, prometheus_url),
        "disk_percent": root_usage,
        "filesystems": filesystems,
    }

    if apache_instance:
        metrics["apache_busy_workers_percent"] = await get_apache_busy_workers_percent(
            apache_instance, client, prometheus_url
        )
        metrics["apache_requests_per_sec"] = await get_apache_requests_per_sec(
            apache_instance, client, prometheus_url
        )

    if postgres_instance:
        metrics["postgres_active_connections_percent"] = await get_postgres_active_connections_percent(
            postgres_instance, client, prometheus_url
        )
        metrics["postgres_deadlocks_per_min"] = await get_postgres_deadlocks_per_min(
            postgres_instance, client, prometheus_url
        )

    return metrics
