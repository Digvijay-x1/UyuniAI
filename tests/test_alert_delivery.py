import asyncio

import httpx

from uyuni_ai_agent import alert_manager


class Response:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class Client:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def post(self, *_args, **_kwargs):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def config():
    return {"alertmanager": {"url": "http://alertmanager:9093"}}


def test_transient_server_errors_retry_then_succeed(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(alert_manager.asyncio, "sleep", no_sleep)
    client = Client([Response(500), Response(503), Response(200)])

    result = asyncio.run(
        alert_manager.send_alert_payload(client, config(), {"labels": {}})
    )

    assert result.startswith("Success:")
    assert client.calls == 3


def test_rejected_payload_does_not_retry(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(alert_manager.asyncio, "sleep", no_sleep)
    client = Client([Response(400, "invalid")])

    result = asyncio.run(
        alert_manager.send_alert_payload(client, config(), {"labels": {}})
    )

    assert result == "Error: 400 - invalid"
    assert client.calls == 1


def test_network_failure_is_bounded_to_three_attempts(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(alert_manager.asyncio, "sleep", no_sleep)
    failure = httpx.ConnectError("offline")
    client = Client([failure, failure, failure])

    result = asyncio.run(
        alert_manager.send_alert_payload(client, config(), {"labels": {}})
    )

    assert result == "Connection failed: offline"
    assert client.calls == 3
