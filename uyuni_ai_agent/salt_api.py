import requests
import urllib3

from uyuni_ai_agent.config import load_config

# Suppress SSL warnings for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SaltAPIClient:
    """Client for the Salt REST API (rest_cherrypy) inside the Uyuni container.

    Authenticates via /login with eauth=file, then uses the session token
    for all subsequent Salt commands.
    """

    def __init__(self):
        config = load_config()
        api_cfg = config["salt_api"]
        self.url = api_cfg["url"]
        self.username = api_cfg["username"]
        self.password = api_cfg.get("password", "")
        self.eauth = api_cfg.get("eauth", "file")
        self.token = None

    def login(self):
        """Authenticate and store the session token."""
        print("[DEBUG] salt_api: logging in to %s" % self.url)
        response = requests.post(
            f"{self.url}/login",
            json={
                "username": self.username,
                "password": self.password,
                "eauth": self.eauth,
            },
            verify=False,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        self.token = data["return"][0]["token"]
        print("[DEBUG] salt_api: login successful, token=%s..." % self.token[:12])

    def _ensure_token(self):
        """Login if we don't have a token yet."""
        if not self.token:
            self.login()

    def _call(self, tgt, fun, arg=None):
        """Make a Salt API call. Re-authenticates on 401."""
        self._ensure_token()

        payload = {
            "client": "local",
            "tgt": tgt,
            "fun": fun,
        }
        if arg:
            payload["arg"] = arg

        headers = {"X-Auth-Token": self.token}

        response = requests.post(
            self.url,
            json=payload,
            headers=headers,
            verify=False,
            timeout=60,
        )

        # Token expired -- re-login and retry once
        if response.status_code == 401:
            print("[DEBUG] salt_api: token expired, re-authenticating...")
            self.login()
            headers["X-Auth-Token"] = self.token
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                verify=False,
                timeout=60,
            )

        response.raise_for_status()
        data = response.json()
        result = data.get("return", [{}])[0]
        return result.get(tgt, "No response from minion")

    def run_command(self, minion_id, cmd):
        """Run a shell command on a minion via cmd.run."""
        print("[DEBUG] salt_api: cmd.run minion=%s cmd=%s" % (minion_id, cmd[:60]))
        try:
            return self._call(minion_id, "cmd.run", [cmd])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    def disk_usage(self, minion_id):
        """Get disk usage for a minion via disk.usage."""
        print("[DEBUG] salt_api: disk.usage minion=%s" % minion_id)
        try:
            return str(self._call(minion_id, "disk.usage"))
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    def service_status(self, minion_id, service):
        """Check if a service is running on a minion."""
        print("[DEBUG] salt_api: service.status minion=%s service=%s" % (minion_id, service))
        try:
            return self._call(minion_id, "service.status", [service])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    def service_logs(self, minion_id, service, lines=50):
        """Get recent journal logs for a service."""
        print("[DEBUG] salt_api: service_logs minion=%s service=%s" % (minion_id, service))
        cmd = f"journalctl -u {service} -n {lines} --no-pager"
        try:
            return self._call(minion_id, "cmd.run", [cmd])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"


# Shared instance used by all tools
salt_client = SaltAPIClient()
