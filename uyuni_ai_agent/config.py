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
import logging

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv not installed -- fall back to real env only
    load_dotenv = None

logger = logging.getLogger(__name__)

# Project root (parent of the uyuni_ai_agent package).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")


if load_dotenv is not None:
    load_dotenv(dotenv_path=_ENV_PATH, override=False)


def _configure_langsmith():
    """Report LangSmith tracing status.

    LangChain/LangGraph enable tracing automatically when the LANGSMITH_*
    (or legacy LANGCHAIN_*) environment variables are present, so there is
    nothing to wire up in code -- you only need to drop the key into .env.
    This function just surfaces whether tracing is active in the logs.
    """
    tracing = os.environ.get(
        "LANGSMITH_TRACING", os.environ.get("LANGCHAIN_TRACING_V2", "")
    ).lower() in ("1", "true", "yes")
    has_key = bool(
        os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    )

    if tracing and has_key:
        project = os.environ.get(
            "LANGSMITH_PROJECT", os.environ.get("LANGCHAIN_PROJECT", "default")
        )
        logger.info("LangSmith tracing ENABLED (project=%s)", project)
    elif tracing and not has_key:
        logger.warning(
            "LANGSMITH_TRACING is on but no LANGSMITH_API_KEY is set; "
            "tracing will not work. Add the key to your .env."
        )
    else:
        logger.debug("LangSmith tracing disabled.")


def load_config():
    """Load settings from config/settings.yaml, overlaying secrets from the env."""
    config_path = os.path.join(_PROJECT_ROOT, "config", "settings.yaml")
    logger.debug("loading config from: %s", config_path)
    logger.debug("file exists: %s", os.path.exists(config_path))
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    logger.debug("config loaded, keys: %s", list(config.keys()))

    # Override LLM API key from environment if set
    api_key = os.environ.get("LLM_API_KEY", "")
    if api_key:
        config["llm"]["api_key"] = api_key

    # Override Salt API password from environment if set
    salt_pw = os.environ.get("SALT_API_PASSWORD", "")
    if salt_pw:
        config["salt_api"]["password"] = salt_pw

    # Surface LangSmith tracing status (enabled purely via env vars).
    _configure_langsmith()

    return config
