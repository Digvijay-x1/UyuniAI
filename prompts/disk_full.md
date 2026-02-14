A high disk usage anomaly has been detected.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Current Disk Usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Instructions
1. Use get_disk_usage to check which partitions are filling up
2. Use find_large_files to identify what is consuming disk space
3. Check for log files that may have grown excessively
4. Look for old backups or temp files that can be cleaned

Provide your root cause analysis and remediation steps.
