High filesystem usage detected on {minion_id}.

## Alert Details

- Server: {minion_id}
- Instance: {instance}
- Mountpoint: {mountpoint}
- Device: {device}
- Current Usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}
- Concurrent failed/restarting services: {related_services}

## Current Prometheus Metrics

{metrics}

## Investigation Steps (mandatory)

Call `get_disk_usage` with `minion_id="{minion_id}"` to confirm the affected
filesystem and its current capacity.

Call `find_large_files` with `minion_id="{minion_id}"` and
`path="{mountpoint}"` to identify the largest files on that filesystem.

Call `find_service_references` with `minion_id="{minion_id}"` and
`path="{mountpoint}"` to find systemd units whose definitions reference the
affected filesystem.

You MUST inspect every plausible unit returned by that search, plus the
concurrent failed/restarting services listed above, with `get_service_details`
and `get_service_logs`, using the `service` argument. Do this before producing
the final answer. Correlate `ExecStart`, `Restart`, `NRestarts`, timestamps, and
errors with the large file and mountpoint.

Look for runaway logs, crash loops, old backups, core dumps, or temporary files.
Do not stop at "the filesystem is full." Explain which process or service
created the data and cite the file size, service command, restart evidence, or
log messages that establish causation. Do not modify the minion.

Recommend only valid, evidence-based remediation. For systemd restart-rate
limiting, the valid unit directives are `StartLimitIntervalSec` and
`StartLimitBurst`; never invent a `RestartLimit` directive. Do not recommend
changing a setting to the value it already has.
