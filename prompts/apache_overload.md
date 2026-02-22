Apache overload detected on {minion_id}.

## Alert Details
- Server: {minion_id}
- Metric: {metric_name}
- Current Value: {current_value}
- Threshold: {threshold}
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Steps (mandatory)

CALL get_apache_status with minion_id="{minion_id}" — get BusyWorkers, IdleWorkers, requests/sec, and scoreboard state.
CALL get_apache_error_log with minion_id="{minion_id}" — check for module errors, segfaults, or AH* error codes.
CALL get_top_cpu_processes with minion_id="{minion_id}" — confirm whether Apache processes are the CPU/memory consumers.
If the error log shows config issues, CALL get_apache_config_check with minion_id="{minion_id}" to verify MaxRequestWorkers and MPM settings.

Look for: traffic spikes overwhelming workers, slow backends (PHP/CGI) holding workers busy, MaxRequestWorkers too low, DDoS or bot floods, or memory leaks in Apache modules.
