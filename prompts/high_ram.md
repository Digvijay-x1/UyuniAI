High memory usage detected on {minion_id}.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Current Memory Usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Steps (mandatory)

CALL get_top_memory_processes with minion_id="{minion_id}" — find what is eating RAM.
CALL get_top_cpu_processes with minion_id="{minion_id}" — check if high memory correlates with CPU.
Then, if a specific service is the top consumer, CALL get_service_logs for that service to check for errors or memory leak patterns.

Look for: memory leaks (growing RSS over time), OOM-killed processes, excessive caching, or swap thrashing.
