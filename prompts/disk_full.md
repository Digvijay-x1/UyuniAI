High disk usage detected on {minion_id}.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Current Disk Usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Steps (mandatory)

CALL get_disk_usage with minion_id="{minion_id}" — check which partitions are filling up.
CALL find_large_files with minion_id="{minion_id}" — find the biggest space consumers.
If log files are the culprit, CALL get_service_logs for the relevant service to understand why logs are growing.

Look for: runaway log files, old backups not cleaned up, large core dumps, or /tmp filling up.
