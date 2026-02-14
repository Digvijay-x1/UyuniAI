import os
import yaml

print("[DEBUG] config.py module loaded")  #LOGS REM


def load_config():
    """Load settings from config/settings.yaml"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "settings.yaml"
    )
    print("[DEBUG] loading config from: %s" % config_path)  #LOGS REM
    print("[DEBUG] file exists: %s" % os.path.exists(config_path))  #LOGS REM
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    print("[DEBUG] config loaded, keys: %s" % list(config.keys()))  #LOGS REM
    
    # Override LLM API key from environment if set
    api_key = os.environ.get("LLM_API_KEY", "")
    if api_key:
        config["llm"]["api_key"] = api_key
    
    return config
