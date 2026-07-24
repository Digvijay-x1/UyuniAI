Apache overload detected on {minion_id}.

## Alert Details

- Server: {minion_id}
- Metric: {metric_name}
- Current Value: {current_value}
- Threshold: {threshold}
- Severity: {severity}

## Current Prometheus Metrics

{metrics}

## Investigation requirements

Use the pre-collected server-status, recent access-log aggregates, active TCP
connections, process ownership, configuration, and error evidence. You may CALL
get_apache_overload_snapshot with minion_id="{minion_id}" again if the live
state needs confirmation.

Metric semantics are mandatory: Prometheus `apache_requests_per_sec` is the
recent five-minute rate of a counter. The `ReqPerSec` and `DurationPerReq`
values emitted by mod_status are lifetime averages since Apache's RestartTime.
Never use a low lifetime average to reject a recent Prometheus rate. A completed
burst also normally has no active client sockets by investigation time. When
the bounded ten-minute access aggregate contains a dominant recent client/path
and the counter rate rose, treat those as corroborating traffic evidence—not
an exporter error.

Do not map BusyWorkers to a predetermined answer. Compare both hypotheses:

1. **Traffic spike:** high recent request rate or a dominant client/path in the
   access aggregates, short/quickly completed requests, and no large set of
   long-lived backend connections. Report the observed client and path, but do
   not call it malicious or a DDoS without evidence.
2. **Slow internal backend:** high BusyWorkers with relatively low completed
   request rate, many established Apache-to-backend connections, a ProxyPass,
   CGI, PHP, or application target that matches those connections, and no
   access-log volume sufficient to explain saturation.

For the slow-backend case, follow the dependency one layer further. The
pre-collected PostgreSQL evidence is deliberately included. If it shows
blocked queries and an identifiable blocker, name PostgreSQL lock contention
and the uncommitted owning transaction as the root cause; describe the proxied
application and Apache BusyWorkers as downstream effects. If PostgreSQL is
healthy with no blockers, explicitly rule it out and stop at the evidenced
backend process. Do not invent a database dependency from a ProxyPass alone.
The blocker's command metadata is only its most recently observed statement;
attribute retained locks to the open transaction, not to that statement,
unless the lock-acquiring statement is directly proven.

Also consider Apache errors, an undersized MaxRequestWorkers setting, and
resource pressure, but only when evidence supports them. State whether Apache
is running and workers are busy versus failing. Explain the causal difference
between incoming volume and workers waiting on a dependency. Include concrete
counts, paths/ports, and responsible process or systemd unit where available.
