import datetime

# Ref: https://prometheus.io/docs/alerting/latest/alerts_api/
async def send_to_alertmanager(client, config, summary, description, severity="info", minion_id="", metric_name=""):
    """Send an enriched alert to AlertManager.

    Args:
        client: an httpx.AsyncClient used for the POST
        config: the loaded settings dict (provides alertmanager.url)
        summary: one-line summary of the issue
        description: full AI-generated root cause analysis
        severity: alert severity (info, warning, critical)
        minion_id: the affected minion
        metric_name: the metric that triggered the alert
    """
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
        response = await client.post(URL, json=payload)
        if response.status_code == 200:
            return "Success: Message routed through Alertmanager."
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Connection Failed: {str(e)}"
