import asyncio

import pytest

from uyuni_ai_agent.resilience import CircuitState, DependencyManager
from uyuni_ai_agent.salt_api import (
    SaltAPIClient,
    SaltAPIError,
    extract_minion_result,
)


def salt_config():
    return {
        "salt_api": {
            "url": "https://localhost:9080",
            "username": "agent",
            "password": "test-only",
            "eauth": "file",
        },
        "minions": [{"id": "client", "instance": "client:9100"}],
        "concurrency": {"max_salt_calls": 2},
    }


def test_extract_minion_result_requires_the_exact_expected_minion():
    assert extract_minion_result(
        {"return": [{"client": {"ok": True}}]},
        "client",
    ) == {"ok": True}

    with pytest.raises(SaltAPIError, match="no data for minion"):
        extract_minion_result({"return": [{"other": True}]}, "client")


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"return": []}, {"return": ["not-an-object"]}],
)
def test_extract_minion_result_rejects_malformed_salt_responses(payload):
    with pytest.raises(SaltAPIError):
        extract_minion_result(payload, "client")


def test_unconfigured_salt_target_is_rejected_before_network_access():
    client = SaltAPIClient(salt_config())

    result = asyncio.run(client.run_command("*", "true"))

    assert result == (
        "Salt API call failed: minion '*' is not configured for this agent"
    )


def test_service_log_line_count_is_bounded_before_network_access():
    client = SaltAPIClient(salt_config())

    with pytest.raises(ValueError, match="between 1 and 200"):
        asyncio.run(client.service_logs("client", "apache2", lines=1000))


def test_false_cmd_run_result_is_normalized_to_inspection_failure(monkeypatch):
    client = SaltAPIClient(salt_config())

    async def false_result(*_args, **_kwargs):
        return False

    monkeypatch.setattr(client, "_safe_call", false_result)
    result = asyncio.run(client.run_command("client", "true"))

    assert result == "Salt API call failed: minion returned no cmd.run result"


def test_false_service_status_is_valid_evidence_not_dependency_failure(
    monkeypatch,
):
    async def scenario():
        manager = DependencyManager(
            ["salt"],
            failure_threshold=1,
            recovery_timeout_seconds=30,
        )
        client = SaltAPIClient(salt_config(), dependency_manager=manager)

        async def stopped_service(*_args, **_kwargs):
            return False

        monkeypatch.setattr(client, "_call", stopped_service)
        result = await client.service_status("client", "apache2.service")
        return result, manager.snapshot("salt")

    result, snapshot = asyncio.run(scenario())
    assert result is False
    assert snapshot.state is CircuitState.CLOSED
    assert snapshot.consecutive_failures == 0


def test_false_cmd_result_is_minion_telemetry_not_api_dependency(monkeypatch):
    async def scenario():
        manager = DependencyManager(
            ["salt"],
            failure_threshold=1,
            recovery_timeout_seconds=30,
        )
        client = SaltAPIClient(salt_config(), dependency_manager=manager)

        async def no_minion_return(*_args, **_kwargs):
            return False

        monkeypatch.setattr(client, "_call", no_minion_return)
        result = await client.run_command("client", "true")
        return result, manager.snapshot("salt")

    result, snapshot = asyncio.run(scenario())
    assert result == "Salt API call failed: minion returned no cmd.run result"
    assert snapshot.state is CircuitState.CLOSED
    assert snapshot.consecutive_failures == 0
