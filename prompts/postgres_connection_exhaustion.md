PostgreSQL connection capacity is high on {minion_id}.

## Alert Details

- Server: {minion_id}
- Metric: {metric_name}
- Current connection utilization: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus Metrics

{metrics}

## Investigation requirements

Use the pre-collected PostgreSQL health, fixed connection-capacity snapshot,
and lock evidence before drawing a conclusion. You may CALL
get_postgres_connections, get_postgres_health, or get_postgres_locks with
minion_id="{minion_id}" again if the live state needs confirmation.

Your RCA must:

1. State whether PostgreSQL is running and accepting read-only queries.
2. Compare current connections with `max_connections`, the normal connection
   limit, reserved capacity, and remaining normal slots.
3. Identify the database, user, application, and state group holding most
   connections. Include the count and transaction age when present.
4. Distinguish these cases from evidence:
   - many `idle in transaction` sessions: application transactions or a pool
     are not releasing connections;
   - many ordinary `idle` sessions: an oversized/leaking pool may be retaining
     capacity, but do not claim open transactions;
   - many `active` sessions: genuine concurrent work or slow queries;
   - lock pairs: capacity pressure may be downstream of lock contention.
5. Use “normal connection capacity is exhausted” only when the snapshot marks
   `normal_capacity_exhausted=true`. Otherwise say “near exhaustion” or “high
   utilization” and report the exact remaining normal slots.
6. Recommend fixing the owning application path and pool/transaction lifecycle.
   For idle transactions, mention commit/rollback and a carefully chosen
   `idle_in_transaction_session_timeout`. Do not recommend restarting
   PostgreSQL as the primary fix.

Do not expose full query text. Do not infer an outage merely from high
connection utilization.
