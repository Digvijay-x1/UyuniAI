import requests
import datetime

def send_to_alertmanager(summary, description):
    # The Alertmanager API endpoint
    URL = "http://167.71.227.138:9093/api/v2/alerts"
    
    # Standard Alertmanager JSON format
    payload = [{
        "labels": {
            "alertname": "AIAgentResponse",
            "severity": "info",
            "source": "ai-bot"
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


print(send_to_alertmanager("this is the summary that this is created by AI ovc", "this is the description which was also created by ai"))