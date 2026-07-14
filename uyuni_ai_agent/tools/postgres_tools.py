# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from langchain_core.tools import tool

from uyuni_ai_agent import salt_api


@tool
async def get_postgres_active_queries(minion_id: str) -> str:
    """Get currently running PostgreSQL queries with duration and state.

    Returns pid, state, query text, and how long each query has been running.
    Useful for identifying long-running or stuck queries that consume connections.
    """
    sql = (
        "SELECT pid, state, left(query, 100) AS query, "
        "age(clock_timestamp(), query_start) AS duration "
        "FROM pg_stat_activity "
        "WHERE state != 'idle' "
        "ORDER BY query_start"
    )
    return await salt_api.salt_client.run_command(
        minion_id,
        f'sudo -u postgres psql -c "{sql}"'
    )


@tool
async def get_postgres_locks(minion_id: str) -> str:
    """Get PostgreSQL lock information to identify deadlocks and blocking.

    Returns waiting locks and the queries holding them. Look for:
    - 'granted: false' indicates a blocked query
    - Multiple locks on the same relation suggest contention
    """
    sql = (
        "SELECT bl.pid AS blocked_pid, a.query AS blocked_query, "
        "kl.pid AS blocking_pid, ka.query AS blocking_query "
        "FROM pg_locks bl "
        "JOIN pg_stat_activity a ON a.pid = bl.pid "
        "JOIN pg_locks kl ON kl.transactionid = bl.transactionid AND kl.pid != bl.pid "
        "JOIN pg_stat_activity ka ON ka.pid = kl.pid "
        "WHERE NOT bl.granted"
    )
    return await salt_api.salt_client.run_command(
        minion_id,
        f'sudo -u postgres psql -c "{sql}"'
    )


@tool
async def get_postgres_connections(minion_id: str) -> str:
    """Get PostgreSQL connection summary grouped by state and database.

    Returns a breakdown of connections (active, idle, idle in transaction)
    per database. Helps identify which database or app is consuming connections.
    """
    sql = (
        "SELECT datname, state, count(*) "
        "FROM pg_stat_activity "
        "GROUP BY datname, state "
        "ORDER BY count DESC"
    )
    return await salt_api.salt_client.run_command(
        minion_id,
        f'sudo -u postgres psql -c "{sql}"'
    )


@tool
async def get_postgres_log(minion_id: str, lines: int = 50) -> str:
    """Get recent PostgreSQL log entries.

    Returns the last N lines from the PostgreSQL log file.
    Look for ERROR, FATAL, PANIC entries, and deadlock detection messages.
    """
    return await salt_api.salt_client.run_command(
        minion_id,
        f"tail -n {lines} /var/log/postgresql/postgresql-*-main.log 2>/dev/null || "
        f"tail -n {lines} /var/log/postgresql/*.log 2>/dev/null || "
        "echo 'PostgreSQL log not found at expected paths'"
    )
