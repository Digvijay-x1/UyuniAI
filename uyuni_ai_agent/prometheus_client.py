import logging
import requests
from datetime import datetime, timedelta

from uyuni_ai_agent.config import load_config

logger = logging.getLogger(__name__)


def query_prometheus(prom_ql):
    """Execute an instant PromQL query and return the results."""
    config = load_config()
    URL = f"{config['prometheus']['url']}/api/v1/query"
    logger.debug("querying prometheus: %s query=%s", URL, prom_ql[:80])

    params = {
        'query': prom_ql
    }

    try:
        response = requests.get(URL, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json()['data']['result']
            return results
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Connection Failed: {str(e)}"


def query_prometheus_range(prom_ql, start, end, step="1m"):
    """Execute a range PromQL query over a time window."""
    config = load_config()
    URL = f"{config['prometheus']['url']}/api/v1/query_range"

    params = {
        'query': prom_ql,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'step': step
    }

    try:
        response = requests.get(URL, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()['data']['result']
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Connection Failed: {str(e)}"


# ── Node Exporter Metrics ──

def get_memory_usage_percent(instance):
    """Get current memory usage percentage for an instance."""
    query = (
        f'100 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} '
        f'/ node_memory_MemTotal_bytes{{instance="{instance}"}} * 100)'
    )
    result = query_prometheus(query)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


def get_cpu_usage_percent(instance):
    """Get current CPU usage percentage for an instance."""
    query = (
        f'100 - (avg(irate(node_cpu_seconds_total'
        f'{{instance="{instance}",mode="idle"}}[5m])) * 100)'
    )
    result = query_prometheus(query)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


def get_disk_usage_percent(instance, mountpoint="/"):
    """Get disk usage percentage for a mountpoint on an instance."""
    query = (
        f'100 - (node_filesystem_avail_bytes'
        f'{{instance="{instance}",mountpoint="{mountpoint}"}} '
        f'/ node_filesystem_size_bytes'
        f'{{instance="{instance}",mountpoint="{mountpoint}"}} * 100)'
    )
    result = query_prometheus(query)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


# ── Apache Exporter Metrics ──

def get_apache_busy_workers_percent(instance):
    """Get Apache busy workers as a percentage of total workers.

    Uses apache_workers{state="busy"} / (busy + idle) * 100
    from the apache_exporter on :9117.
    """
    busy_query = f'apache_workers{{instance="{instance}",state="busy"}}'
    idle_query = f'apache_workers{{instance="{instance}",state="idle"}}'

    busy_result = query_prometheus(busy_query)
    idle_result = query_prometheus(idle_query)

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


def get_apache_requests_per_sec(instance):
    """Get Apache request rate (requests per second over 5m window).

    Uses rate(apache_accesses_total[5m]) from the apache_exporter.
    """
    query = f'rate(apache_accesses_total{{instance="{instance}"}}[5m])'
    result = query_prometheus(query)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


# ── PostgreSQL Exporter Metrics ──

def get_postgres_active_connections_percent(instance):
    """Get active PostgreSQL connections as a percentage of max_connections.

    Uses pg_stat_activity and pg_settings from the postgres_exporter on :9187.
    """
    active_query = (
        f'pg_stat_activity_count{{instance="{instance}",state="active"}}'
    )
    max_query = (
        f'pg_settings_max_connections{{instance="{instance}"}}'
    )

    active_result = query_prometheus(active_query)
    max_result = query_prometheus(max_query)

    active = 0.0
    max_conn = 100.0  # safe default
    if isinstance(active_result, list) and active_result:
        active = float(active_result[0]['value'][1])
    if isinstance(max_result, list) and max_result:
        max_conn = float(max_result[0]['value'][1])

    if max_conn == 0:
        return 0.0
    return (active / max_conn) * 100


def get_postgres_deadlocks_per_min(instance):
    """Get PostgreSQL deadlock rate (deadlocks per minute over 5m window).

    Uses rate(pg_stat_database_deadlocks[5m]) * 60 from the postgres_exporter.
    """
    query = (
        f'sum(rate(pg_stat_database_deadlocks{{instance="{instance}"}}[5m])) * 60'
    )
    result = query_prometheus(query)
    if isinstance(result, list) and result:
        return float(result[0]['value'][1])
    return 0.0


# ── Combined Metrics ──

def get_all_metrics(instance, apache_instance=None, postgres_instance=None):
    """Get all key metrics for an instance. Returns a dict summary.

    Includes node_exporter metrics always. Apache and PostgreSQL metrics
    are included only if their exporter instances are configured.
    """
    metrics = {
        "memory_percent": get_memory_usage_percent(instance),
        "cpu_percent": get_cpu_usage_percent(instance),
        "disk_percent": get_disk_usage_percent(instance),
    }

    if apache_instance:
        metrics["apache_busy_workers_percent"] = get_apache_busy_workers_percent(apache_instance)
        metrics["apache_requests_per_sec"] = get_apache_requests_per_sec(apache_instance)

    if postgres_instance:
        metrics["postgres_active_connections_percent"] = get_postgres_active_connections_percent(postgres_instance)
        metrics["postgres_deadlocks_per_min"] = get_postgres_deadlocks_per_min(postgres_instance)

    return metrics
