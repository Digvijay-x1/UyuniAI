import requests

from uyuni_ai_agent.config import load_config


class SaltAPI:
    """Client for the Uyuni Salt HTTP API.
    
    Since the agent runs as a sidecar container (not inside Uyuni),
    we use the Salt API over HTTP instead of LocalClient.
    """

    def __init__(self):
        config = load_config()
        self.url = config["salt_api"]["url"]
        self.username = config["salt_api"]["username"]
        self.password = config["salt_api"]["password"]
        self.token = None

    def login(self):
        """Authenticate and get a session token."""
        response = requests.post(
            f"{self.url}/login",
            json={
                "username": self.username,
                "password": self.password,
                "eauth": "auto",
            },
        )
        if response.status_code == 200:
            self.token = response.json()["return"][0]["token"]
        else:
            raise Exception(f"Salt API login failed: {response.status_code} - {response.text}")

    def cmd(self, minion_id, fun, arg=None):
        """Execute a Salt command on a minion via the API."""
        if not self.token:
            self.login()

        payload = {
            "client": "local",
            "tgt": minion_id,
            "fun": fun,
        }
        if arg:
            payload["arg"] = arg

        headers = {"X-Auth-Token": self.token}

        try:
            response = requests.post(self.url, json=payload, headers=headers)
            if response.status_code == 200:
                result = response.json()["return"][0]
                return result.get(minion_id, "No response from minion")
            elif response.status_code == 401:
                self.login()
                headers = {"X-Auth-Token": self.token}
                response = requests.post(self.url, json=payload, headers=headers)
                if response.status_code == 200:
                    result = response.json()["return"][0]
                    return result.get(minion_id, "No response from minion")
            return f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Salt API call failed: {str(e)}"


# Shared instance used by all tools
salt_api = SaltAPI()
