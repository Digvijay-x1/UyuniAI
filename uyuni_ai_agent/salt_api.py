import logging
import requests
import urllib3

from uyuni_ai_agent.config import load_config

# Suppress SSL warnings for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class SaltAPIClient:
    """Client for the Salt REST API (rest_cherrypy) inside the Uyuni container.

    Uses requests.Session() for cookie-based authentication as shown in
    the official Salt REST API docs:
    https://docs.saltproject.io/en/latest/ref/netapi/all/salt.netapi.rest_cherrypy.html
    """

    def __init__(self):
        config = load_config()
        api_cfg = config["salt_api"]
        self.url = api_cfg["url"]
        self.username = api_cfg["username"]
        self.password = api_cfg.get("password", "")
        self.eauth = api_cfg.get("eauth", "file")
        self.session = requests.Session()
        self.session.verify = False
        self.logged_in = False

    def login(self):
        """Authenticate via /login. Session cookies are stored automatically."""
        logger.debug("salt_api: logging in to %s", self.url)
        resp = self.session.post(
            f"{self.url}/login",
            data={
                "username": self.username,
                "password": self.password,
                "eauth": self.eauth,
            },
            timeout=15,
        )
        resp.raise_for_status()
        self.logged_in = True
        token = resp.json()["return"][0]["token"]
        logger.debug("salt_api: login successful, token=%s...", token[:12])

    def _ensure_login(self):
        """Login if we haven't yet."""
        if not self.logged_in:
            self.login()

    def _call(self, tgt, fun, arg=None):
        """Make a Salt API call via POST /. Uses session cookies for auth.

        Body is a JSON array of lowstate dicts as per the docs.
        Re-authenticates once on 401.
        """
        self._ensure_login()

        lowstate = {
            "client": "local",
            "tgt": tgt,
            "fun": fun,
        }
        if arg:
            lowstate["arg"] = arg

        resp = self.session.post(
            self.url,
            json=[lowstate],
            timeout=60,
        )

        # Token/cookie expired -- re-login and retry once
        if resp.status_code == 401:
            logger.warning("salt_api: session expired, re-authenticating...")
            self.logged_in = False
            self.login()
            resp = self.session.post(
                self.url,
                json=[lowstate],
                timeout=60,
            )

        resp.raise_for_status()
        data = resp.json()
        result = data.get("return", [{}])[0]
        return result.get(tgt, "No response from minion")

    def run_command(self, minion_id, cmd):
        """Run a shell command on a minion via cmd.run."""
        logger.debug("salt_api: cmd.run minion=%s cmd=%s", minion_id, cmd[:60])
        try:
            return self._call(minion_id, "cmd.run", [cmd])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    def disk_usage(self, minion_id):
        """Get disk usage for a minion via disk.usage."""
        logger.debug("salt_api: disk.usage minion=%s", minion_id)
        try:
            return str(self._call(minion_id, "disk.usage"))
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    def service_status(self, minion_id, service):
        """Check if a service is running on a minion."""
        logger.debug("salt_api: service.status minion=%s service=%s", minion_id, service)
        try:
            return self._call(minion_id, "service.status", [service])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    def service_logs(self, minion_id, service, lines=50):
        """Get recent journal logs for a service."""
        logger.debug("salt_api: service_logs minion=%s service=%s", minion_id, service)
        cmd = f"journalctl -u {service} -n {lines} --no-pager"
        try:
            return self._call(minion_id, "cmd.run", [cmd])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"


# Shared instance used by all tools
salt_client = SaltAPIClient()
