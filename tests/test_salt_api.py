import asyncio

import pytest

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
