High CPU usage detected on {minion_id}.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Current CPU Usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Steps (mandatory)

CALL get_top_cpu_processes with minion_id="{minion_id}" — find what is burning CPU.
CALL get_top_memory_processes with minion_id="{minion_id}" — check if high CPU correlates with memory pressure.
Then, if a specific service is the top consumer, CALL get_service_logs for that service to look for crash loops, stuck processes, or runaway threads.

Look for: processes stuck at 100% CPU, fork bombs, cron jobs gone wrong, or compilation/indexing tasks.
