# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class SaltAPIClient:
    """Async client for the Salt REST API (rest_cherrypy) inside the Uyuni container.

    Uses an httpx.AsyncClient with cookie-based authentication as shown in the
    official Salt REST API docs:
    https://docs.saltproject.io/en/latest/ref/netapi/all/salt.netapi.rest_cherrypy.html

    Concurrency: a single shared instance is created at startup
    (set_salt_client) and used by all tools. ``salt_semaphore`` bounds the
    number of concurrent Salt API calls across all minions/investigations so
    the Salt Master is not overwhelmed during alert storms. Login is eager
    (start()) and re-login is guarded by a lock so concurrent 401s trigger
    only one re-login.
    """

    def __init__(self, config):
        api_cfg = config["salt_api"]
        concurrency_cfg = config.get("concurrency", {})
        self.url = api_cfg["url"]
        self.username = api_cfg["username"]
        self.password = api_cfg.get("password", "")
        self.eauth = api_cfg.get("eauth", "file")
        # Global cap on concurrent Salt API calls (protects the Salt Master).
        self.salt_semaphore = asyncio.Semaphore(
            concurrency_cfg.get("max_salt_calls", 10)
        )
        self._client: httpx.AsyncClient | None = None
        self._login_lock = asyncio.Lock()
        self.logged_in = False

    async def start(self):
        """Create the HTTP client and log in eagerly.

        Eager login eliminates the lazy-login race where many concurrent tool
        calls would all try to log in at once.
        """
        self._client = httpx.AsyncClient(verify=False, timeout=httpx.Timeout(60.0))
        await self.login()

    async def aclose(self):
        """Close the underlying HTTP client. Idempotent."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def login(self):
        """Authenticate via /login. Session cookies are stored automatically."""
        logger.debug("salt_api: logging in to %s", self.url)
        resp = await self._client.post(
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

    async def _ensure_login(self):
        """Login if we haven't yet.

        Double-checked locking: if the session expires mid-flight and several
        tool calls hit a 401 concurrently, only one of them re-logs in.
        """
        if self.logged_in:
            return
        async with self._login_lock:
            if self.logged_in:
                return
            await self.login()

    async def _call(self, tgt, fun, arg=None):
        """Make a Salt API call via POST /. Uses session cookies for auth.

        Body is a JSON array of lowstate dicts as per the docs.
        Re-authenticates once on 401. Bounded by salt_semaphore to protect the
        Salt Master under concurrent alert storms.
        """
        await self._ensure_login()

        lowstate = {
            "client": "local",
            "tgt": tgt,
            "fun": fun,
        }
        if arg:
            lowstate["arg"] = arg

        async with self.salt_semaphore:
            resp = await self._client.post(
                self.url,
                json=[lowstate],
                timeout=60,
            )

            # Token/cookie expired -- re-login and retry once
            if resp.status_code == 401:
                logger.warning("salt_api: session expired, re-authenticating...")
                self.logged_in = False
                await self._ensure_login()
                resp = await self._client.post(
                    self.url,
                    json=[lowstate],
                    timeout=60,
                )

            resp.raise_for_status()

        data = resp.json()
        result = data.get("return", [{}])[0]
        return result.get(tgt, "No response from minion")

    async def run_command(self, minion_id, cmd):
        """Run a shell command on a minion via cmd.run."""
        logger.debug("salt_api: cmd.run minion=%s cmd=%s", minion_id, cmd[:60])
        try:
            return await self._call(minion_id, "cmd.run", [cmd])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    async def disk_usage(self, minion_id):
        """Get disk usage for a minion via disk.usage."""
        logger.debug("salt_api: disk.usage minion=%s", minion_id)
        try:
            return str(await self._call(minion_id, "disk.usage"))
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    async def service_status(self, minion_id, service):
        """Check if a service is running on a minion."""
        logger.debug("salt_api: service.status minion=%s service=%s", minion_id, service)
        try:
            return await self._call(minion_id, "service.status", [service])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"

    async def service_logs(self, minion_id, service, lines=50):
        """Get recent journal logs for a service."""
        logger.debug("salt_api: service_logs minion=%s service=%s", minion_id, service)
        cmd = f"journalctl -u {service} -n {lines} --no-pager"
        try:
            return await self._call(minion_id, "cmd.run", [cmd])
        except Exception as e:
            return f"Salt API call failed: {str(e)}"


# Shared instance used by all tools. Initialized once at startup via
# set_salt_client() from main.run(); tools read salt_api.salt_client at call
# time so the value set after their import is observed.
salt_client: SaltAPIClient | None = None


def set_salt_client(client):
    """Set the shared async Salt client. Called once from main.run() at startup."""
    global salt_client
    salt_client = client
