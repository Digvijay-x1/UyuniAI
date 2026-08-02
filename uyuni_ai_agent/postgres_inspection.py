"""Safe, read-only PostgreSQL lock inspection helpers."""

from __future__ import annotations

import json
import shlex

_BLOCKING_ACTIVITY_SQL = r"""
WITH lock_pairs AS (
    SELECT
        waiting.pid AS blocked_pid,
        COALESCE(waiting.datname, 'unknown') AS database,
        COALESCE(waiting.usename, 'unknown') AS blocked_user,
        COALESCE(waiting.application_name, '') AS blocked_application,
        COALESCE(waiting.client_addr::text, 'local') AS blocked_client,
        waiting.state AS blocked_state,
        waiting.wait_event_type,
        waiting.wait_event,
        GREATEST(
            0,
            FLOOR(EXTRACT(EPOCH FROM clock_timestamp() - waiting.query_start))
        )::bigint AS blocked_seconds,
        COALESCE(waiting.query_id::text, 'unavailable') AS blocked_query_id,
        LEFT(
            UPPER(split_part(ltrim(COALESCE(waiting.query, '')), ' ', 1)),
            32
        ) AS blocked_command,
        blocker.pid AS blocker_pid,
        COALESCE(blocker.usename, 'unknown') AS blocker_user,
        COALESCE(blocker.application_name, '') AS blocker_application,
        COALESCE(blocker.client_addr::text, 'local') AS blocker_client,
        blocker.state AS blocker_state,
        blocker.wait_event_type AS blocker_wait_event_type,
        GREATEST(
            0,
            FLOOR(
                EXTRACT(
                    EPOCH FROM clock_timestamp() -
                    COALESCE(blocker.xact_start, blocker.state_change)
                )
            )
        )::bigint AS blocker_transaction_seconds,
        COALESCE(blocker.query_id::text, 'unavailable') AS blocker_query_id,
        LEFT(
            UPPER(split_part(ltrim(COALESCE(blocker.query, '')), ' ', 1)),
            32
        ) AS blocker_command
    FROM pg_stat_activity AS waiting
    CROSS JOIN LATERAL
        unnest(pg_blocking_pids(waiting.pid)) AS blocked_by(blocker_pid)
    JOIN pg_stat_activity AS blocker
        ON blocker.pid = blocked_by.blocker_pid
    WHERE waiting.wait_event_type = 'Lock'
),
bounded_pairs AS (
    SELECT *
    FROM lock_pairs
    ORDER BY blocked_seconds DESC, blocked_pid, blocker_pid
    LIMIT 100
)
SELECT COALESCE(
    json_agg(bounded_pairs ORDER BY blocked_seconds DESC, blocked_pid),
    '[]'::json
)::text
FROM bounded_pairs
""".strip()


_HEALTH_SQL = r"""
SELECT json_build_object(
    'available', true,
    'server_version', current_setting('server_version'),
    'database', current_database(),
    'in_recovery', pg_is_in_recovery(),
    'postmaster_uptime_seconds',
        FLOOR(EXTRACT(EPOCH FROM clock_timestamp() - pg_postmaster_start_time()))::bigint
)::text
""".strip()


_CONNECTION_ACTIVITY_SQL = r"""
WITH settings AS (
    SELECT
        current_setting('max_connections')::integer AS max_connections,
        current_setting('superuser_reserved_connections')::integer
            AS superuser_reserved_connections,
        COALESCE(
            NULLIF(current_setting('reserved_connections', true), ''),
            '0'
        )::integer AS reserved_connections
),
client_activity AS (
    SELECT
        pid,
        COALESCE(datname, 'unknown') AS database,
        COALESCE(usename, 'unknown') AS username,
        COALESCE(NULLIF(application_name, ''), 'unspecified') AS application,
        COALESCE(state, 'unknown') AS state,
        xact_start,
        state_change
    FROM pg_stat_activity
    WHERE backend_type = 'client backend'
),
grouped AS (
    SELECT
        database,
        username,
        application,
        state,
        count(*)::integer AS connection_count,
        CASE
            WHEN min(xact_start) IS NULL THEN 0
            ELSE GREATEST(
                0,
                FLOOR(
                    EXTRACT(
                        EPOCH FROM clock_timestamp() - min(xact_start)
                    )
                )
            )::bigint
        END AS oldest_transaction_seconds,
        GREATEST(
            0,
            FLOOR(
                EXTRACT(
                    EPOCH FROM clock_timestamp() - min(state_change)
                )
            )
        )::bigint AS longest_state_seconds
    FROM client_activity
    GROUP BY database, username, application, state
),
totals AS (
    SELECT
        count(*)::integer AS current_connections,
        count(*) FILTER (WHERE state = 'active')::integer
            AS active_connections,
        count(*) FILTER (WHERE state = 'idle')::integer
            AS idle_connections,
        count(*) FILTER (WHERE state = 'idle in transaction')::integer
            AS idle_in_transaction_connections,
        COALESCE(
            GREATEST(
                0,
                FLOOR(
                    EXTRACT(
                        EPOCH FROM clock_timestamp() -
                        min(xact_start) FILTER (
                            WHERE state = 'idle in transaction'
                        )
                    )
                )
            )::bigint,
            0
        ) AS oldest_idle_transaction_seconds
    FROM client_activity
)
SELECT json_build_object(
    'available', true,
    'max_connections', settings.max_connections,
    'superuser_reserved_connections',
        settings.superuser_reserved_connections,
    'reserved_connections', settings.reserved_connections,
    'normal_connection_limit',
        settings.max_connections -
        settings.superuser_reserved_connections -
        settings.reserved_connections,
    'current_connections', totals.current_connections,
    'utilization_percent',
        ROUND(
            (
                100.0 * totals.current_connections /
                NULLIF(settings.max_connections, 0)
            )::numeric,
            2
        )::double precision,
    'remaining_normal_slots',
        GREATEST(
            0,
            settings.max_connections -
            settings.superuser_reserved_connections -
            settings.reserved_connections -
            totals.current_connections
        ),
    'normal_capacity_exhausted',
        totals.current_connections >= (
            settings.max_connections -
            settings.superuser_reserved_connections -
            settings.reserved_connections
        ),
    'active_connections', totals.active_connections,
    'idle_connections', totals.idle_connections,
    'idle_in_transaction_connections',
        totals.idle_in_transaction_connections,
    'oldest_idle_transaction_seconds',
        totals.oldest_idle_transaction_seconds,
    'groups',
        COALESCE(
            (
                SELECT json_agg(row_to_json(summary))
                FROM (
                    SELECT *
                    FROM grouped
                    ORDER BY
                        connection_count DESC,
                        oldest_transaction_seconds DESC,
                        database,
                        application,
                        state
                    LIMIT 100
                ) AS summary
            ),
            '[]'::json
        )
)::text
FROM settings
CROSS JOIN totals
""".strip()


def _read_only_psql_command(sql: str) -> str:
    """Build a bounded local psql command from SQL owned by this module."""
    options = "-c statement_timeout=5000 -c default_transaction_read_only=on"
    return (
        f"sudo -n -u postgres env PGOPTIONS={shlex.quote(options)} "
        "psql --no-psqlrc --dbname=postgres --tuples-only --no-align "
        f"--quiet --set=ON_ERROR_STOP=1 --command={shlex.quote(sql)}"
    )


def build_postgres_blocking_command() -> str:
    """Return the fixed command used to inspect blocked lock waiters."""
    return _read_only_psql_command(_BLOCKING_ACTIVITY_SQL)


def build_postgres_health_command() -> str:
    """Return the fixed command proving the PostgreSQL server is responsive."""
    return _read_only_psql_command(_HEALTH_SQL)


def build_postgres_connection_activity_command() -> str:
    """Return the fixed command used to inspect connection capacity and owners."""
    return _read_only_psql_command(_CONNECTION_ACTIVITY_SQL)


def parse_postgres_connection_snapshot(output):
    """Parse the bounded connection-capacity JSON returned by PostgreSQL."""
    if not isinstance(output, str):
        return {}

    stripped = output.strip()
    if not stripped or stripped.startswith("Salt API call failed:"):
        return {}
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        raw = json.loads(stripped[start:end + 1])
    except (TypeError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("available") is not True:
        return {}

    integer_fields = (
        "max_connections",
        "superuser_reserved_connections",
        "reserved_connections",
        "normal_connection_limit",
        "current_connections",
        "remaining_normal_slots",
        "active_connections",
        "idle_connections",
        "idle_in_transaction_connections",
        "oldest_idle_transaction_seconds",
    )
    try:
        snapshot = {
            field: max(0, int(raw.get(field, 0)))
            for field in integer_fields
        }
        snapshot["utilization_percent"] = max(
            0.0, min(100.0, float(raw.get("utilization_percent", 0.0)))
        )
    except (TypeError, ValueError):
        return {}
    snapshot["available"] = True
    snapshot["normal_capacity_exhausted"] = bool(
        raw.get("normal_capacity_exhausted", False)
    )

    groups = []
    for group in raw.get("groups", [])[:100]:
        if not isinstance(group, dict):
            continue
        try:
            count = max(0, int(group.get("connection_count", 0)))
            oldest = max(
                0, int(group.get("oldest_transaction_seconds", 0))
            )
            state_seconds = max(
                0, int(group.get("longest_state_seconds", 0))
            )
        except (TypeError, ValueError):
            continue
        groups.append({
            "database": str(group.get("database") or "unknown")[:128],
            "username": str(group.get("username") or "unknown")[:128],
            "application": str(
                group.get("application") or "unspecified"
            )[:256],
            "state": str(group.get("state") or "unknown")[:64],
            "connection_count": count,
            "oldest_transaction_seconds": oldest,
            "longest_state_seconds": state_seconds,
        })
    snapshot["groups"] = groups
    return snapshot


def parse_postgres_lock_pairs(output):
    """Parse and validate the JSON produced by the blocking-activity query."""
    if not isinstance(output, str):
        return []

    stripped = output.strip()
    if not stripped or stripped.startswith("Salt API call failed:"):
        return []

    # PostgreSQL's json_agg(composite_row) representation can place each
    # object on a separate physical line even in unaligned mode. Extract the
    # complete bounded array rather than assuming one JSON value per line.
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start < 0 or end < start:
        return []

    try:
        raw_pairs = json.loads(stripped[start:end + 1])
    except (TypeError, ValueError):
        return []
    if not isinstance(raw_pairs, list):
        return []

    pairs = []
    for raw in raw_pairs[:100]:
        if not isinstance(raw, dict):
            continue
        try:
            blocked_pid = int(raw["blocked_pid"])
            blocker_pid = int(raw["blocker_pid"])
            blocked_seconds = max(0, int(raw["blocked_seconds"]))
            blocker_seconds = max(
                0, int(raw.get("blocker_transaction_seconds", 0))
            )
        except (KeyError, TypeError, ValueError):
            continue
        if (
            raw.get("wait_event_type") != "Lock"
            or blocked_pid <= 0
            or blocker_pid <= 0
        ):
            continue

        pairs.append({
            "blocked_pid": blocked_pid,
            "database": str(raw.get("database") or "unknown")[:128],
            "blocked_user": str(raw.get("blocked_user") or "unknown")[:128],
            "blocked_application": str(
                raw.get("blocked_application") or ""
            )[:256],
            "blocked_client": str(raw.get("blocked_client") or "local")[:128],
            "blocked_state": str(raw.get("blocked_state") or "unknown")[:64],
            "wait_event_type": "Lock",
            "wait_event": str(raw.get("wait_event") or "unknown")[:128],
            "blocked_seconds": blocked_seconds,
            "blocked_query_id": str(
                raw.get("blocked_query_id") or "unavailable"
            )[:64],
            "blocked_command": str(
                raw.get("blocked_command") or "UNKNOWN"
            )[:32],
            "blocker_pid": blocker_pid,
            "blocker_user": str(raw.get("blocker_user") or "unknown")[:128],
            "blocker_application": str(
                raw.get("blocker_application") or ""
            )[:256],
            "blocker_client": str(raw.get("blocker_client") or "local")[:128],
            "blocker_state": str(raw.get("blocker_state") or "unknown")[:64],
            "blocker_wait_event_type": (
                str(raw["blocker_wait_event_type"])[:128]
                if raw.get("blocker_wait_event_type") is not None
                else None
            ),
            "blocker_transaction_seconds": blocker_seconds,
            "blocker_query_id": str(
                raw.get("blocker_query_id") or "unavailable"
            )[:64],
            "blocker_command": str(
                raw.get("blocker_command") or "UNKNOWN"
            )[:32],
        })
    return pairs
