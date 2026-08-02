import asyncio
import time

import pytest

from uyuni_ai_agent.anomaly_detector import check_all_metrics
from uyuni_ai_agent.evidence import EvidenceStatus
from uyuni_ai_agent.prometheus_client import (
    get_cpu_usage_percent,
    query_prometheus,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def get(self, url, params, timeout):
        if self.error:
            raise self.error
        return self.response


def payload(result):
    return {"status": "success", "data": {"result": result}}


@pytest.mark.parametrize(
    "client, expected_status",
    [
        (
            FakeClient(FakeResponse(500, payload({}), "server failed")),
            EvidenceStatus.ERROR,
        ),
        (
            FakeClient(FakeResponse(200, payload([]))),
            EvidenceStatus.MISSING,
        ),
        (
            FakeClient(error=TimeoutError("timed out")),
            EvidenceStatus.ERROR,
        ),
        (
            FakeClient(FakeResponse(200, ValueError("bad json"))),
            EvidenceStatus.ERROR,
        ),
    ],
)
def test_query_failures_are_not_returned_as_empty_or_zero(client, expected_status):
    result = asyncio.run(query_prometheus(
        "up", client, "http://prometheus:9090"
    ))

    assert result.status is expected_status
    assert result.samples == []
    assert result.error


def test_old_prometheus_sample_is_explicitly_stale():
    client = FakeClient(FakeResponse(200, payload([
        {"metric": {}, "value": [600, "1"]},
    ])))

    result = asyncio.run(query_prometheus(
        "up",
        client,
        "http://prometheus:9090",
        max_sample_age_seconds=300,
        now=1000,
    ))

    assert result.status is EvidenceStatus.STALE
    assert result.observed_at == 600


def test_non_finite_metric_value_is_an_error_not_zero():
    client = FakeClient(FakeResponse(200, payload([
        {"metric": {}, "value": [time.time(), "NaN"]},
    ])))

    reading = asyncio.run(get_cpu_usage_percent(
        "client:9100", client, "http://prometheus:9090"
    ))

    assert reading.status is EvidenceStatus.ERROR
    assert reading.value is None
    assert "non-finite" in reading.error


def _threshold_config():
    return {
        "thresholds": {
            "memory": {"warning": 70, "critical": 95},
            "cpu": {"warning": 70, "critical": 95},
            "disk": {"warning": 75, "critical": 95},
        }
    }


def test_missing_cpu_is_skipped_and_becomes_a_telemetry_anomaly():
    metrics = {
        "memory_percent": 20,
        "memory_pressure": {
            "memory_usage_percent": 20,
            "swap_activity_pages_per_second": None,
            "swap_usage_percent": None,
        },
        "cpu_percent": None,
        "filesystems": [],
        "telemetry": {
            "node_exporter_up": {
                "name": "node_exporter_up",
                "target": "client:9100",
                "exporter": "node_exporter",
                "status": "ok",
                "value": 1.0,
            },
            "memory_available_bytes": {
                "name": "memory_available_bytes",
                "target": "client:9100",
                "exporter": "node_exporter",
                "status": "ok",
                "value": 80.0,
            },
            "memory_total_bytes": {
                "name": "memory_total_bytes",
                "target": "client:9100",
                "exporter": "node_exporter",
                "status": "ok",
                "value": 100.0,
            },
            "filesystems": {
                "name": "filesystems",
                "target": "client:9100",
                "exporter": "node_exporter",
                "status": "ok",
                "value": [],
            },
            "cpu_percent": {
                "name": "cpu_percent",
                "target": "client:9100",
                "exporter": "node_exporter",
                "status": "error",
                "value": None,
                "error": "Prometheus HTTP 500",
            },
        },
    }

    anomalies = asyncio.run(check_all_metrics(
        "client:9100",
        "client",
        None,
        _threshold_config(),
        metrics=metrics,
    ))

    assert [anomaly.metric_name for anomaly in anomalies] == [
        "telemetry_unavailable"
    ]
    assert anomalies[0].resource == "telemetry:node_exporter:client:9100"
    assert anomalies[0].context["observations"][0]["name"] == "cpu_percent"


def test_successful_numeric_zero_remains_usable():
    client = FakeClient(FakeResponse(200, payload([
        {"metric": {}, "value": [time.time(), "0"]},
    ])))

    reading = asyncio.run(get_cpu_usage_percent(
        "client:9100", client, "http://prometheus:9090"
    ))

    assert reading.status is EvidenceStatus.OK
    assert reading.value == 0.0
