# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from langchain_core.rate_limiters import InMemoryRateLimiter

_rate_limiters = {}


def _get_rate_limiter(config):
    """Return one process-wide limiter shared by all clients for a model."""
    requests_per_minute = config["llm"].get("requests_per_minute")
    if requests_per_minute is None:
        return None

    key = (
        config["llm"]["provider"],
        config["llm"]["model"],
        float(requests_per_minute),
    )
    limiter = _rate_limiters.get(key)
    if limiter is None:
        limiter = InMemoryRateLimiter(
            requests_per_second=float(requests_per_minute) / 60.0,
            check_every_n_seconds=0.1,
            max_bucket_size=1,
        )
        _rate_limiters[key] = limiter
    return limiter


def get_llm(config):
    """Return a configured LangChain chat LLM based on the passed config.

    Supports: huggingface, google_genai, openai, tokenrouter.
    The API key is read from config["llm"]["api_key"] (populated from the
    LLM_API_KEY env var by load_config()) with an env fallback.

    Chat-model construction is synchronous; investigations use each client's
    asynchronous invocation interface.
    """
    provider = config["llm"]["provider"]
    model = config["llm"]["model"]
    api_key = config["llm"].get("api_key", os.environ.get("LLM_API_KEY", ""))
    rate_limiter = _get_rate_limiter(config)

    if provider == "huggingface":
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
        llm_model = HuggingFaceEndpoint(
            repo_id=model,
            huggingfacehub_api_token=api_key,
            task="text-generation",
            max_new_tokens=512,
        )
        return ChatHuggingFace(llm=llm_model)

    elif provider == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            rate_limiter=rate_limiter,
        )
    elif provider == "tokenrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url="https://api.tokenrouter.com/v1",
            rate_limiter=rate_limiter,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
