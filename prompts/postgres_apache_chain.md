A correlated PostgreSQL-to-Apache incident was detected.

## Correlation candidate

- Apache/application minion: {apache_minion_id}
- PostgreSQL minion: {postgres_minion_id}
- Metric: {metric_name}
- Longest PostgreSQL wait: {current_value} seconds
- Alert threshold: {threshold} seconds
- Severity: {severity}

## Current Prometheus metrics

{metrics}

## Mandatory causal validation

The detector grouped Apache worker saturation with PostgreSQL lock waits because
the completed request rate was low and the blocked application name looked
like a web/backend tier. This is a candidate relationship, not proof by name.
Use the pre-collected, minion-labelled evidence to validate all links. When
calling another tool, pass `{apache_minion_id}` for Apache/application evidence
and `{postgres_minion_id}` for PostgreSQL evidence:

1. Apache is running but BusyWorkers is high while request throughput is low.
2. Established Apache connections terminate at a specific local backend port,
   and ProxyPass/configuration points to the same port.
3. The owning backend process/systemd unit is identified.
4. PostgreSQL is available rather than stopped.
5. PostgreSQL shows that backend application's sessions waiting on locks.
6. Trace the lock chain to the original `idle in transaction` blocker. Later
   blocked application sessions may also appear as secondary blockers; do not
   mistake them for independent root causes.

Only when those links match, report one root-cause chain:

`uncommitted PostgreSQL transaction -> blocked application pool/queries ->
slow backend -> occupied Apache workers`

Treat Apache saturation and secondary lock waits as symptoms. Do not recommend
restarting Apache or PostgreSQL as the primary fix. Recommend correcting the
transaction owner/code path, using COMMIT/ROLLBACK for coordinated immediate
relief, and applying transaction/pool timeouts carefully.

`blocker_command` is only the most recently observed statement in that session.
Attribute retained locks to the open transaction unless the lock-acquiring
statement is directly proven. If the process/port/application links do not
match, explicitly reject the correlation and report the incidents separately.
