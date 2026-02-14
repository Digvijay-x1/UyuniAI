import os
import yaml


def load_config():
    """Load settings from config/settings.yaml"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "settings.yaml"
    )
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    
    # Override API key from environment if set
    api_key = os.environ.get("LLM_API_KEY", "")
    if api_key:
        config["llm"]["api_key"] = api_key
    
    return config
