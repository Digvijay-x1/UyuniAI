from copy import deepcopy

import pytest
from pydantic import ValidationError

from uyuni_ai_agent.config import _apply_runtime_overrides
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
        "incident_store": {
            "path": "/var/lib/uyuni-ai-agent/incidents.db",
            "resolve_after_healthy_cycles": 2,
        },
        "investigation_queue": {
            "max_pending": 50,
            "workers": 3,
            "max_job_age_seconds": 300,
            "shutdown_grace_seconds": 30,
        },
        "observability": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 9898,
            "readiness_max_age_seconds": 180,
        },
        "resilience": {
            "failure_threshold": 3,
            "recovery_timeout_seconds": 30,
            "initial_backoff_seconds": 1,
            "maximum_backoff_seconds": 60,
            "jitter_ratio": 0.2,
            "salt_login_timeout_seconds": 20,
        },
        "timeouts": {
            "salt_operation_seconds": 70,
            "prometheus_operation_seconds": 30,
            "minion_seconds": 90,
            "poll_cycle_seconds": 180,
            "llm_seconds": 240,
            "investigation_seconds": 300,
            "alertmanager_seconds": 30,
        },
        "quality_gates": {
            "max_evidence_age_seconds": 300,
            "minimum_supporting_records": 1,
            "deterministic_analysis_enabled": True,
        },
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


def test_uyuni_inventory_does_not_require_static_minions():
    config = valid_config()
    config["minions"] = []
    config["dependency_correlation"]["postgres_apache"] = []
    config["inventory"] = {
        "provider": "uyuni",
        "refresh_interval_seconds": 60,
    }
    config["uyuni_api"] = {
        "url": "https://uyuni.example/rhn/manager/api",
        "username": "inventory-agent",
        "password": "test-only",
    }

    validated = validate_config(config)

    assert validated["inventory"]["provider"] == "uyuni"
    assert validated["minions"] == []


def test_uyuni_inventory_requires_api_credentials():
    config = valid_config()
    config["minions"] = []
    config["dependency_correlation"]["postgres_apache"] = []
    config["inventory"] = {"provider": "uyuni"}
    config["uyuni_api"] = {
        "url": "https://uyuni.example/rhn/manager/api",
        "username": "inventory-agent",
        "password": "",
    }

    with pytest.raises(ValidationError, match="UYUNI_API_PASSWORD"):
        validate_config(config)


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
        (
            lambda config: config["investigation_queue"].update(
                {"max_pending": 0}
            ),
            "greater than or equal to 1",
        ),
        (
            lambda config: config["observability"].update({"port": 70000}),
            "less than or equal to 65535",
        ),
        (
            lambda config: config["resilience"].update({
                "initial_backoff_seconds": 10,
                "maximum_backoff_seconds": 5,
            }),
            "maximum_backoff_seconds must be >= initial_backoff_seconds",
        ),
        (
            lambda config: config["timeouts"].update({
                "minion_seconds": 100,
                "poll_cycle_seconds": 90,
            }),
            "poll_cycle_seconds must be >= minion_seconds",
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


def test_runtime_endpoint_overrides_support_immutable_images():
    config = valid_config()
    config["uyuni_api"] = {
        "url": "https://uyuni.example/rhn/manager/api",
        "username": "inventory-agent",
        "password": "test-only",
    }

    _apply_runtime_overrides(
        config,
        {
            "PROMETHEUS_URL": "http://prometheus.override:9090",
            "ALERTMANAGER_URL": "http://alertmanager.override:9093",
            "SALT_API_URL": "https://salt.override:9080",
            "UYUNI_API_URL": "https://uyuni.override/rhn/manager/api",
        },
    )

    validated = validate_config(config)
    assert validated["prometheus"]["url"] == "http://prometheus.override:9090"
    assert validated["alertmanager"]["url"] == "http://alertmanager.override:9093"
    assert validated["salt_api"]["url"] == "https://salt.override:9080"
    assert (
        validated["uyuni_api"]["url"]
        == "https://uyuni.override/rhn/manager/api"
    )
