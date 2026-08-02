import asyncio

import pytest

from uyuni_ai_agent.anomaly_detector import (
    AlertSeverity,
    check_failed_services,
    parse_failed_systemd_services,
)
from uyuni_ai_agent.systemd import validate_systemd_service

SYSTEMCTL_OUTPUT = """\
my-web.service loaded failed failed My test web service
● backup@nightly.service loaded failed failed Nightly backup
flapping.service loaded activating auto-restart Flapping worker
"""


class FakeSaltClient:
    def __init__(self, output):
        self.output = output

    async def failed_systemd_services(self, minion_id):
        assert minion_id == "client"
        return self.output


def test_parse_failed_systemd_services():
    services = parse_failed_systemd_services(SYSTEMCTL_OUTPUT)

    assert [service["name"] for service in services] == [
        "my-web.service",
        "backup@nightly.service",
        "flapping.service",
    ]
    assert services[0]["description"] == "My test web service"


def test_parser_ignores_empty_errors_and_non_failed_lines():
    assert parse_failed_systemd_services("") == []
    assert parse_failed_systemd_services(
        "Salt API call failed: permission denied"
    ) == []
    assert parse_failed_systemd_services(
        "healthy.service loaded active running Healthy service"
    ) == []


def test_failed_services_are_discovered_without_service_allowlist():
    anomalies = asyncio.run(check_failed_services(
        "client",
        FakeSaltClient(SYSTEMCTL_OUTPUT),
        {"service_monitoring": {"enabled": True, "ignored_units": []}},
    ))

    assert len(anomalies) == 3
    assert anomalies[0].metric_name == "service_down"
    assert anomalies[0].service_name == "my-web.service"
    assert anomalies[0].severity is AlertSeverity.CRITICAL


def test_ignored_unit_globs_are_applied():
    anomalies = asyncio.run(check_failed_services(
        "client",
        FakeSaltClient(SYSTEMCTL_OUTPUT),
        {
            "service_monitoring": {
                "enabled": True,
                "ignored_units": ["backup@*.service"],
            }
        },
    ))

    assert [anomaly.service_name for anomaly in anomalies] == [
        "my-web.service",
        "flapping.service",
    ]


@pytest.mark.parametrize(
    "output",
    [False, None, "Salt API call failed: minion returned no cmd.run result"],
)
def test_failed_service_inspection_is_not_reported_as_healthy(output):
    anomalies = asyncio.run(check_failed_services(
        "client",
        FakeSaltClient(output),
        {"service_monitoring": {"enabled": True, "ignored_units": []}},
    ))

    assert len(anomalies) == 1
    assert anomalies[0].metric_name == "telemetry_unavailable"
    assert anomalies[0].context["source"] == "salt"
    assert anomalies[0].resource == "telemetry:salt_inspection:client"


@pytest.mark.parametrize(
    "unit",
    [
        "my-web.service; reboot",
        "../../tmp/x.service",
        "my web.service",
        "",
    ],
)
def test_systemd_unit_validation_rejects_command_injection(unit):
    with pytest.raises(ValueError):
        validate_systemd_service(unit)


def test_systemd_unit_validation_accepts_normal_and_template_units():
    assert validate_systemd_service("apache2") == "apache2.service"
    assert validate_systemd_service("my-web") == "my-web.service"
    assert validate_systemd_service("my-web.service") == "my-web.service"
    assert (
        validate_systemd_service("backup@nightly.service")
        == "backup@nightly.service"
    )
