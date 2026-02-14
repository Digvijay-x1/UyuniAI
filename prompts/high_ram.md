A high memory usage anomaly has been detected.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Current Memory Usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Instructions
1. Use get_top_memory_processes to find which processes are consuming the most RAM
2. If a specific service is the top consumer, use get_service_logs to check for errors
3. Check if disk swap is being used heavily
4. Identify whether this is a memory leak or expected high usage

Provide your root cause analysis and remediation steps.
