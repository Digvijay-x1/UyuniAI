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


def get_all_metrics(instance):
    """Get all key metrics for an instance. Returns a dict summary."""
    return {
        "memory_percent": get_memory_usage_percent(instance),
        "cpu_percent": get_cpu_usage_percent(instance),
        "disk_percent": get_disk_usage_percent(instance),
    }
