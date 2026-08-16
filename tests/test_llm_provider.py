from uyuni_ai_agent import llm_provider


def test_rate_limiter_is_shared_by_agent_and_structured_clients():
    config = {
        "llm": {
            "provider": "tokenrouter",
            "model": "test-model",
            "requests_per_minute": 4.5,
        }
    }
    llm_provider._rate_limiters.clear()

    first = llm_provider._get_rate_limiter(config)
    second = llm_provider._get_rate_limiter(config)

    assert first is second


def test_rate_limiter_is_optional():
    config = {"llm": {"provider": "openai", "model": "test-model"}}
    assert llm_provider._get_rate_limiter(config) is None
