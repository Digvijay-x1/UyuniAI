PostgreSQL issue detected on {minion_id}.

## Alert Details
- Server: {minion_id}
- Metric: {metric_name}
- Current Value: {current_value}
- Threshold: {threshold}
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Steps (mandatory)

CALL get_postgres_active_queries with minion_id="{minion_id}" — find long-running or stuck queries consuming connections.
CALL get_postgres_connections with minion_id="{minion_id}" — get connection breakdown by database and state.
CALL get_postgres_locks with minion_id="{minion_id}" — check for deadlocks or blocked queries.
If the above show errors or anomalies, CALL get_postgres_log with minion_id="{minion_id}" to check for FATAL, ERROR, or deadlock detection messages.

Look for: long-running queries holding connections, "idle in transaction" connections not released, deadlocks between concurrent transactions, connection pool exhaustion, or missing indexes causing full table scans.
