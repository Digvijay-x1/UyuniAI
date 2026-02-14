A high CPU usage anomaly has been detected.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Current CPU Usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Instructions
1. Use get_top_cpu_processes to find which processes are consuming the most CPU
2. If a specific service is the top consumer, use get_service_logs to check for errors
3. Check if any process is stuck in a loop or if this is a temporary spike
4. Look for correlation with other metrics (memory, disk I/O)

Provide your root cause analysis and remediation steps.
