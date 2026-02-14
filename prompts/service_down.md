A service appears to be down or unresponsive.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Service: {service_name}
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Instructions
1. Use get_service_status to confirm the service state
2. Use get_service_logs to check for crash logs or error messages
3. Use get_listening_ports to verify if the service port is still open
4. Check if related services or dependencies are also affected

Provide your root cause analysis and remediation steps.
