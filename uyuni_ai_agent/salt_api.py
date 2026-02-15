import requests

from uyuni_ai_agent.config import load_config


class ToolsServerClient:
    """HTTP client for the Flask tools server running inside the Uyuni container.

    Simple HTTP requests to the tools_server.py Flask app.
    """

    def __init__(self):
        config = load_config()
        self.url = config["tools_server"]["url"]

    def run_command(self, minion_id, cmd):
        """Run a shell command on a minion."""
        print("[DEBUG] tools_server: run_command minion=%s cmd=%s" % (minion_id, cmd[:60]))  #LOGS REM
        try:
            response = requests.post(
                f"{self.url}/run_command",
                json={"minion_id": minion_id, "cmd": cmd},
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()["result"]
            return f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Tools server call failed: {str(e)}"

    def disk_usage(self, minion_id):
        """Get disk usage for a minion."""
        print("[DEBUG] tools_server: disk_usage minion=%s" % minion_id)  #LOGS REM
        try:
            response = requests.get(
                f"{self.url}/disk_usage",
                params={"minion_id": minion_id},
                timeout=30,
            )
            if response.status_code == 200:
                return str(response.json()["result"])
            return f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Tools server call failed: {str(e)}"

    def service_status(self, minion_id, service):
        """Check if a service is running on a minion."""
        print("[DEBUG] tools_server: service_status minion=%s service=%s" % (minion_id, service))  #LOGS REM
        try:
            response = requests.get(
                f"{self.url}/service_status",
                params={"minion_id": minion_id, "service": service},
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()["result"]
            return f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Tools server call failed: {str(e)}"

    def service_logs(self, minion_id, service, lines=50):
        """Get recent journal logs for a service."""
        print("[DEBUG] tools_server: service_logs minion=%s service=%s" % (minion_id, service))  #LOGS REM
        try:
            response = requests.get(
                f"{self.url}/service_logs",
                params={"minion_id": minion_id, "service": service, "lines": lines},
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()["result"]
            return f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Tools server call failed: {str(e)}"


# Shared instance used by all tools
tools_client = ToolsServerClient()
