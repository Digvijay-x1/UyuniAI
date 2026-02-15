import requests
import datetime

from uyuni_ai_agent.config import load_config

# Ref: https://prometheus.io/docs/alerting/latest/alerts_api/
def send_to_alertmanager(summary, description, severity="info", minion_id="", metric_name=""):
    """Send an enriched alert to AlertManager.
    
    Args:
        summary: one-line summary of the issue
        description: full AI-generated root cause analysis
        severity: alert severity (info, warning, critical)
        minion_id: the affected minion
        metric_name: the metric that triggered the alert
    """
    config = load_config()
    URL = f"{config['alertmanager']['url']}/api/v2/alerts"

    payload = [{
        "labels": {
            "alertname": "AIAgentResponse",
            "severity": severity,
            "source": "ai-bot",
            "minion": minion_id,
            "metric": metric_name,
        },
        "annotations": {
            "summary": summary,
            "description": description
        },
        "startsAt": datetime.datetime.now().isoformat() + "Z"
    }]

    try:
        response = requests.post(URL, json=payload)
        if response.status_code == 200:
            return "Success: Message routed through Alertmanager."
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Connection Failed: {str(e)}"
