**PostgreSQL Issue on `{minion_id}`**

**Anomaly:** {metric_name} is at **{current_value}** (threshold: {threshold}, severity: {severity})

**Current System Metrics:**
{metrics}

Investigate this PostgreSQL issue on the server. Use the available tools:

1. **get_postgres_active_queries** — Check for long-running or stuck queries that may be consuming connections
2. **get_postgres_locks** — Look for deadlocks or blocked queries waiting on locks
3. **get_postgres_connections** — Get a breakdown of connections by database and state (active, idle, idle in transaction)
4. **get_postgres_log** — Check for ERROR, FATAL, or deadlock detection messages
5. **get_top_memory_processes** / **get_top_cpu_processes** — See if PostgreSQL processes are consuming system resources

Common root causes to look for:
- Long-running queries holding connections open
- "idle in transaction" connections not being released by the application
- Deadlocks between concurrent transactions
- Connection pool exhaustion (too many app connections)
- Missing indexes causing full table scans
- Vacuum not running, leading to table bloat
