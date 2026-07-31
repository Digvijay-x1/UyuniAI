from copy import deepcopy

import pytest
from pydantic import ValidationError

from uyuni_ai_agent.config_schema import validate_config


def valid_config():
    return {
        "prometheus": {"url": "http://monitoring.example:9090/"},
        "alertmanager": {"url": "http://monitoring.example:9093"},
        "salt_api": {
            "url": "https://localhost:9080",
            "username": "agent",
            "password": "",
            "eauth": "file",
        },
        "minions": [
            {
                "id": "database1",
                "instance": "database1.example:9100",
                "postgres_instance": "database1.example:9187",
            },
            {
                "id": "web1",
                "instance": "web1.example:9100",
                "apache_instance": "web1.example:9117",
            },
        ],
        "dependency_correlation": {
            "grace_seconds": 90,
            "postgres_apache": [
                {
                    "postgres_minion": "database1",
                    "apache_minion": "web1",
                }
            ],
        },
        "thresholds": {
            "memory": {
                "warning": 70,
                "critical": 95,
                "pressure": {
                    "swap_activity_pages_per_second": {
                        "warning": 1,
                        "critical": 100,
                    },
                    "swap_usage_percent": {
                        "warning": 5,
                        "critical": 25,
                    },
                },
            },
            "cpu": {"warning": 70, "critical": 95},
            "disk": {"warning": 75, "critical": 95},
            "apache": {
                "busy_workers_percent": {"warning": 75, "critical": 90},
                "requests_per_sec": {"warning": 500, "critical": 1000},
            },
            "postgres": {
                "active_connections_percent": {
                    "warning": 75,
                    "critical": 90,
                },
                "deadlocks_per_min": {"warning": 1, "critical": 5},
                "blocked_transaction_seconds": {
                    "warning": 5,
                    "critical": 30,
                },
            },
        },
        "llm": {"provider": "openai", "model": "test-model"},
        "logging": {"level": "info"},
        "polling": {"interval_seconds": 60},
        "service_monitoring": {"enabled": True, "ignored_units": []},
        "postgres_lock_monitoring": {"enabled": True},
        "deduplication": {"cooldown_seconds": 900},
        "concurrency": {
            "max_minions": 8,
            "max_salt_calls": 8,
            "max_llm_calls": 5,
        },
    }


def test_valid_config_is_normalized_and_preserves_dictionary_interface():
    config = validate_config(valid_config())

    assert config["prometheus"]["url"] == "http://monitoring.example:9090"
    assert config["logging"]["level"] == "INFO"
    assert config["minions"][0]["id"] == "database1"


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (
            lambda config: config["minions"].append(
                deepcopy(config["minions"][0])
            ),
            "minion ids must be unique",
        ),
        (
            lambda config: config["dependency_correlation"][
                "postgres_apache"
            ][0].update({"postgres_minion": "missing"}),
            "unknown PostgreSQL minion",
        ),
        (
            lambda config: config["thresholds"]["cpu"].update(
                {"warning": 90, "critical": 80}
            ),
            "critical threshold must be >= warning threshold",
        ),
        (
            lambda config: config["concurrency"].update({"max_salt_calls": 0}),
            "greater than 0",
        ),
    ],
)
def test_invalid_production_config_fails_at_startup(mutate, expected):
    config = valid_config()
    mutate(config)

    with pytest.raises(ValidationError, match=expected):
        validate_config(config)


def test_unknown_config_keys_are_rejected_as_likely_typos():
    config = valid_config()
    config["polling"]["interval_second"] = 10

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_config(config)
