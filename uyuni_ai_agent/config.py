import os
import logging
import yaml

logger = logging.getLogger(__name__)
logger.debug("config.py module loaded")


def load_config():
    """Load settings from config/settings.yaml"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "settings.yaml"
    )
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
    
    return config
