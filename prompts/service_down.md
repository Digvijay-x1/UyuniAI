A systemd service is in the failed state on {minion_id}.

## Alert Details

- Server: {minion_id}
- Instance: {instance}
- Service: {service_name}
- Severity: {severity}

## Current Prometheus Metrics

{metrics}

## Investigation Steps (mandatory)

Call `get_service_status` with `minion_id="{minion_id}"` and
`service="{service_name}"` to confirm the service state.

Call `get_service_details` with `minion_id="{minion_id}"` and
`service="{service_name}"` to inspect the exit result and `ExecStart`.

Call `get_service_logs` with `minion_id="{minion_id}"` and
`service="{service_name}"` to find the concrete failure message.

Call `get_listening_ports` with `minion_id="{minion_id}"` to determine whether
another process owns the service's expected port.

Correlate the evidence. Look for restart loops, dependency failures, port
conflicts, OOM kills, missing files, permission errors, or configuration errors.
Do not stop at "the service is inactive." State the underlying cause and cite
the process, port, exit status, or log message that proves it. Do not make any
changes to the minion.
