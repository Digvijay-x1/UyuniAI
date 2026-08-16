import asyncio

import pytest
from pydantic import ValidationError

from uyuni_ai_agent.models import RootCauseAnalysis
from uyuni_ai_agent.react_agent import (
    _invoke_structured_with_rate_limit_retry,
    _rate_limit_retry_delay,
)


class RateLimited(Exception):
    status_code = 429
    response = None


def test_rate_limit_delay_defaults_to_one_minute_and_ignores_other_errors():
    assert _rate_limit_retry_delay(RateLimited()) == 60.0
    assert _rate_limit_retry_delay(RuntimeError("failed")) is None


def test_structured_output_retries_once_after_rate_limit(monkeypatch):
    calls = []
    sleeps = []

    class FakeStructuredLlm:
        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                raise RateLimited()
            return "structured"

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("uyuni_ai_agent.react_agent.asyncio.sleep", fake_sleep)
    result = asyncio.run(
        _invoke_structured_with_rate_limit_retry(FakeStructuredLlm(), ["input"])
    )

    assert result == "structured"
    assert len(calls) == 2
    assert sleeps == [60.0]


def test_structured_output_does_not_retry_unrelated_failures(monkeypatch):
    class FakeStructuredLlm:
        async def ainvoke(self, _messages):
            raise RuntimeError("provider failed")

    async def fail_if_sleeping(_delay):
        raise AssertionError("non-rate-limit failures must not be retried")

    monkeypatch.setattr(
        "uyuni_ai_agent.react_agent.asyncio.sleep", fail_if_sleeping
    )
    with pytest.raises(RuntimeError, match="provider failed"):
        asyncio.run(
            _invoke_structured_with_rate_limit_retry(
                FakeStructuredLlm(), ["input"]
            )
        )


def test_structured_output_retries_once_with_schema_repair_instruction():
    calls = []
    validation_error = None
    try:
        RootCauseAnalysis.model_validate({"confidence": "high"})
    except ValidationError as error:
        validation_error = error

    class FakeStructuredLlm:
        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                raise validation_error
            return "repaired"

    result = asyncio.run(
        _invoke_structured_with_rate_limit_retry(FakeStructuredLlm(), ["input"])
    )

    assert result == "repaired"
    assert len(calls) == 2
    assert "confidence as a number" in calls[1][-1][1]
