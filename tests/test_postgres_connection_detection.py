import json

from uyuni_ai_agent.postgres_inspection import (
    build_postgres_connection_activity_command,
    parse_postgres_connection_snapshot,
)


def test_connection_snapshot_parser_preserves_capacity_and_ownership():
    raw = {
        "available": True,
        "max_connections": 100,
        "superuser_reserved_connections": 3,
        "reserved_connections": 0,
        "normal_connection_limit": 97,
        "current_connections": 97,
        "utilization_percent": 97.0,
        "remaining_normal_slots": 0,
        "normal_capacity_exhausted": True,
        "active_connections": 2,
        "idle_connections": 1,
        "idle_in_transaction_connections": 94,
        "oldest_idle_transaction_seconds": 61,
        "groups": [{
            "database": "my_pool_lab",
            "username": "postgres",
            "application": "my-pool-exhaustion",
            "state": "idle in transaction",
            "connection_count": 94,
            "oldest_transaction_seconds": 61,
            "longest_state_seconds": 60,
        }],
    }

    snapshot = parse_postgres_connection_snapshot(json.dumps(raw))

    assert snapshot["available"] is True
    assert snapshot["normal_capacity_exhausted"] is True
    assert snapshot["remaining_normal_slots"] == 0
    assert snapshot["idle_in_transaction_connections"] == 94
    assert snapshot["groups"][0]["application"] == "my-pool-exhaustion"
    assert snapshot["groups"][0]["state"] == "idle in transaction"


def test_connection_snapshot_rejects_invalid_or_unavailable_output():
    assert parse_postgres_connection_snapshot("not-json") == {}
    assert parse_postgres_connection_snapshot(
        json.dumps({"available": False})
    ) == {}


def test_connection_probe_is_fixed_read_only_bounded_and_redacted():
    command = build_postgres_connection_activity_command()

    assert "statement_timeout=5000" in command
    assert "default_transaction_read_only=on" in command
    assert "--dbname=postgres" in command
    assert "application_name" in command
    assert "idle in transaction" in command
    assert "query," not in command
    assert "pg_terminate_backend" not in command
