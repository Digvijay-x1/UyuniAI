PostgreSQL blocked-transaction anomaly detected on {minion_id}.

## Alert Details
- Server: {minion_id}
- Database: {database}
- Blocked PID(s): {blocked_pids}
- Blocker PID(s): {blocker_pids}
- Longest observed wait: {current_value} seconds
- Alert threshold: {threshold} seconds
- Severity: {severity}

## Current Prometheus Metrics
{metrics}

## Investigation Steps (mandatory)

CALL get_postgres_health with minion_id="{minion_id}" to prove whether the
database server is available and accepting SQL.

CALL get_postgres_locks with minion_id="{minion_id}" to identify each blocked
session, its wait event, and the transaction/session blocking it.

Correlate the two outputs. A responsive server with an active session waiting
on wait_event_type=Lock is not a PostgreSQL outage. If its blocker is
"idle in transaction", state explicitly that an open, uncommitted transaction
is holding a lock required by another query.

The pre-collected evidence also includes an Apache/dependency snapshot. If
Apache has high BusyWorkers, many connections to a proxied application, and
that application name matches the blocked PostgreSQL sessions, report one
causal chain: uncommitted PostgreSQL transaction -> blocked application
queries -> slow backend -> occupied Apache workers. Do not report independent
Apache and PostgreSQL causes when this evidence joins them.

## RCA guardrails

- Do not call this a deadlock unless PostgreSQL explicitly reports a deadlock.
  A one-way lock wait is blocking, not a deadlock.
- Report the exact wait event (for example, `transactionid`). Do not claim a
  lock granularity such as row-level or table-level unless evidence directly
  establishes it.
- Do not recommend restarting PostgreSQL for an available server. A restart
  would disrupt unrelated sessions and conceal the application defect.
- Recommend identifying the application/request that owns the blocker and
  correcting the code path that leaves transactions open.
- For immediate mitigation, recommend coordinating a COMMIT or ROLLBACK by the
  transaction owner. Only suggest canceling or terminating the identified
  blocker after impact review; never terminate arbitrary sessions.
- Cite the blocked PID, blocker PID, database, command/query ID, wait event,
  session states, and observed wait/transaction duration from evidence.
- `blocker_command` is only the session's most recently observed statement.
  An idle transaction can retain locks acquired by an earlier statement. Do
  not claim that the reported command acquired the lock; attribute the lock to
  the open transaction unless acquisition is directly proven.
- Raw SQL text is intentionally excluded from remote evidence to avoid sending
  literals or customer data to the LLM and alerting systems.
