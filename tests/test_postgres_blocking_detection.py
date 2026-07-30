import asyncio
import json

from uyuni_ai_agent.anomaly_detector import (
    AlertSeverity,
    check_postgres_blocked_transactions,
    postgres_blocking_anomalies,
)
from uyuni_ai_agent.postgres_inspection import (
    build_postgres_blocking_command,
    parse_postgres_lock_pairs,
)


def lock_pair(**overrides):
    pair = {
        "blocked_pid": 202,
        "database": "my_anomaly_lab",
        "blocked_user": "postgres",
        "blocked_application": "my-anomaly-blocked",
        "blocked_client": "local",
        "blocked_state": "active",
        "wait_event_type": "Lock",
        "wait_event": "transactionid",
        "blocked_seconds": 45,
        "blocked_query_id": "123456",
        "blocked_command": "UPDATE",
        "blocker_pid": 101,
        "blocker_user": "postgres",
        "blocker_application": "my-anomaly-blocker",
        "blocker_client": "local",
        "blocker_state": "idle in transaction",
        "blocker_wait_event_type": "Client",
        "blocker_transaction_seconds": 50,
        "blocker_query_id": "789012",
        "blocker_command": "SELECT",
    }
    pair.update(overrides)
    return pair


def test_parser_keeps_blocked_and_blocker_evidence():
    pairs = parse_postgres_lock_pairs(json.dumps([lock_pair()]))

    assert len(pairs) == 1
    assert pairs[0]["blocked_pid"] == 202
    assert pairs[0]["blocker_pid"] == 101
    assert pairs[0]["wait_event_type"] == "Lock"
    assert pairs[0]["blocker_state"] == "idle in transaction"
    assert pairs[0]["blocked_command"] == "UPDATE"
    assert "blocked_query" not in pairs[0]


def test_parser_rejects_errors_and_non_lock_rows():
    assert parse_postgres_lock_pairs("Salt API call failed: timeout") == []
    assert parse_postgres_lock_pairs("not json") == []
    assert parse_postgres_lock_pairs(
        json.dumps([lock_pair(wait_event_type="IO")])
    ) == []


def test_parser_accepts_postgres_multiline_json_aggregate():
    second = lock_pair(blocked_pid=203)
    multiline = (
        "[" + json.dumps(lock_pair()) + ",\n " + json.dumps(second) + "]"
    )

    parsed = parse_postgres_lock_pairs(multiline)

    assert [item["blocked_pid"] for item in parsed] == [202, 203]


def test_anomalies_group_waiters_by_database_and_apply_duration_thresholds():
    pairs = [
        lock_pair(blocked_pid=202, blocked_seconds=45),
        lock_pair(blocked_pid=203, blocked_seconds=10),
        lock_pair(
            blocked_pid=204,
            database="other_db",
            blocked_seconds=2,
        ),
    ]
    anomalies = postgres_blocking_anomalies(
        pairs,
        {"warning": 5, "critical": 30},
        "client",
    )

    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly.metric_name == "postgres_blocked_transaction"
    assert anomaly.resource == "postgresql:my_anomaly_lab"
    assert anomaly.current_value == 45
    assert anomaly.severity is AlertSeverity.CRITICAL
    assert anomaly.context["blocked_pids"] == [202, 203]
    assert anomaly.context["blocker_pids"] == [101]


class FakeSaltClient:
    async def postgres_blocking_activity(self, minion_id):
        assert minion_id == "client"
        return json.dumps([lock_pair(blocked_seconds=8)])


def test_async_detector_uses_fixed_salt_probe():
    config = {
        "thresholds": {
            "postgres": {
                "blocked_transaction_seconds": {
                    "warning": 5,
                    "critical": 30,
                }
            }
        }
    }

    anomalies = asyncio.run(check_postgres_blocked_transactions(
        "client", FakeSaltClient(), config
    ))

    assert len(anomalies) == 1
    assert anomalies[0].severity is AlertSeverity.WARNING


def test_postgres_probe_is_read_only_and_bounded():
    command = build_postgres_blocking_command()

    assert "default_transaction_read_only=on" in command
    assert "statement_timeout=5000" in command
    assert "pg_blocking_pids" in command
    assert "wait_event_type = " in command
    assert "--dbname=postgres" in command
    assert "AS blocked_query," not in command
