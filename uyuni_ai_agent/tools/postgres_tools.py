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
    """Get active PostgreSQL command metadata with duration and state.

    Returns pid, state, query_id, command type, and duration. Full SQL text is
    intentionally omitted because it may contain customer data or secrets.
    """
    sql = (
        "SELECT pid, state, query_id, "
        "left(upper(split_part(ltrim(query), ' ', 1)), 32) AS command, "
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

    Returns blocked/blocker PIDs, command types, query IDs, states, wait
    events, and durations. Full SQL text is intentionally omitted.
    """
    return await salt_api.salt_client.postgres_blocking_activity(minion_id)


@tool
async def get_postgres_health(minion_id: str) -> str:
    """Prove PostgreSQL is available and accepting read-only SQL.

    Returns server version, recovery state, and postmaster uptime. Use this
    before diagnosing a lock wait so an available-but-blocked database is not
    mistaken for a stopped PostgreSQL service.
    """
    return await salt_api.salt_client.postgres_health(minion_id)


@tool
async def get_postgres_connections(minion_id: str) -> str:
    """Get bounded PostgreSQL connection-capacity and ownership evidence.

    Returns max capacity, reserved slots, current utilization, remaining normal
    slots, idle-transaction age, and counts grouped by database, user,
    application and state. Full SQL text is intentionally omitted.
    """
    return await salt_api.salt_client.postgres_connection_activity(minion_id)


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
