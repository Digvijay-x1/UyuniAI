A service appears to be down or unresponsive on {minion_id}.

## Alert Details
- Server: {minion_id}
- Instance: {instance}
- Service: {service_name}
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Steps (mandatory)

CALL get_service_status with minion_id="{minion_id}" and service_name="{service_name}" — confirm the service state.
CALL get_service_logs with minion_id="{minion_id}" and service_name="{service_name}" — check for crash logs or error messages.
CALL get_listening_ports with minion_id="{minion_id}" — verify if the service port is still open or something else took it.

Look for: crash loops (repeated start/stop), dependency failures, port conflicts, OOM kills, or config errors after a recent change.
