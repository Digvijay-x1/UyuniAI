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
from collections.abc import Mapping

import httpx

from uyuni_ai_agent.apache_inspection import build_apache_overload_command
from uyuni_ai_agent.cpu_inspection import build_cpu_pressure_command
from uyuni_ai_agent.disk_inspection import (
    build_large_files_command,
    build_service_references_command,
)
from uyuni_ai_agent.memory_inspection import build_memory_pressure_command
from uyuni_ai_agent.postgres_inspection import (
    build_postgres_blocking_command,
    build_postgres_connection_activity_command,
    build_postgres_health_command,
)
from uyuni_ai_agent.resilience import DependencyManager, DependencyUnavailable
from uyuni_ai_agent.systemd import validate_systemd_service
from uyuni_ai_agent.validation import bounded_int, validate_configured_minion

logger = logging.getLogger(__name__)


class SaltAPIError(RuntimeError):
    """Raised when Salt returns a malformed or incomplete API response."""


def extract_minion_result(payload, minion_id):
    """Extract one exact minion result from a Salt lowstate response."""
    if not isinstance(payload, Mapping):
        raise SaltAPIError("Salt API response must be a JSON object")
    returns = payload.get("return")
    if not isinstance(returns, list) or not returns:
        raise SaltAPIError("Salt API response has no return data")
    result = returns[0]
    if not isinstance(result, Mapping):
        raise SaltAPIError("Salt API return data must be an object")
    if minion_id not in result:
        raise SaltAPIError(f"Salt API returned no data for minion {minion_id!r}")
    return result[minion_id]


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

    def __init__(
        self,
        config,
        dependency_manager: DependencyManager | None = None,
    ):
        api_cfg = config["salt_api"]
        concurrency_cfg = config.get("concurrency", {})
        self.url = api_cfg["url"]
        self.username = api_cfg["username"]
        self.password = api_cfg.get("password", "")
        self.eauth = api_cfg.get("eauth", "file")
        self.allowed_minions = frozenset(
            minion["id"] for minion in config["minions"]
        )
        # Global cap on concurrent Salt API calls (protects the Salt Master).
        self.salt_semaphore = asyncio.Semaphore(
            concurrency_cfg.get("max_salt_calls", 10)
        )
        self._client: httpx.AsyncClient | None = None
        self._login_lock = asyncio.Lock()
        self.logged_in = False
        self._dependency_manager = dependency_manager
        self._operation_timeout_seconds = float(
            config.get("timeouts", {}).get("salt_operation_seconds", 70)
        )

    async def start(self):
        """Create the HTTP client and log in eagerly.

        Eager login eliminates the lazy-login race where many concurrent tool
        calls would all try to log in at once.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                verify=False, timeout=httpx.Timeout(60.0)
            )
        await self.login()

    async def aclose(self):
        """Close the underlying HTTP client. Idempotent."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def login(self):
        """Authenticate via /login. Session cookies are stored automatically."""
        if self._client is None:
            raise SaltAPIError("Salt API client has not been started")
        logger.debug("salt_api: logging in to %s", self.url)
        self.logged_in = False
        try:
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
        except Exception:
            self.logged_in = False
            raise
        logger.debug("salt_api: login successful")

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
        tgt = validate_configured_minion(tgt, self.allowed_minions)
        await self._ensure_login()
        if self._client is None:
            raise SaltAPIError("Salt API client has not been started")

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

        try:
            data = resp.json()
        except ValueError as exc:
            raise SaltAPIError("Salt API returned invalid JSON") from exc
        return extract_minion_result(data, tgt)

    async def _safe_call(self, minion_id, fun, arg=None):
        """Run one Salt function and convert expected I/O failures to evidence."""
        try:
            if self._dependency_manager is None:
                return await self._call(minion_id, fun, arg)
            return await self._dependency_manager.execute(
                "salt",
                lambda: self._call(minion_id, fun, arg),
                timeout_seconds=self._operation_timeout_seconds,
            )
        except (
            httpx.HTTPError,
            SaltAPIError,
            DependencyUnavailable,
            ValueError,
        ) as exc:
            if isinstance(exc, (httpx.HTTPError, DependencyUnavailable)):
                self.logged_in = False
            logger.warning(
                "Salt API call failed: minion=%s function=%s error=%s",
                minion_id,
                fun,
                exc,
            )
            return f"Salt API call failed: {exc}"

    async def run_command(self, minion_id, cmd):
        """Run a shell command on a minion via cmd.run."""
        logger.debug("salt_api: cmd.run minion=%s cmd=%s", minion_id, cmd[:60])
        result = await self._safe_call(minion_id, "cmd.run", [cmd])
        # Salt returns the boolean False when a minion job does not return.
        # cmd.run itself has string output, so False/None are transport state,
        # not valid command results.
        if result is False or result is None:
            return "Salt API call failed: minion returned no cmd.run result"
        return str(result)

    async def disk_usage(self, minion_id):
        """Get disk usage for a minion via disk.usage."""
        logger.debug("salt_api: disk.usage minion=%s", minion_id)
        return str(await self._safe_call(minion_id, "disk.usage"))

    async def service_status(self, minion_id, service):
        """Check if a service is running on a minion."""
        service = validate_systemd_service(service)
        logger.debug("salt_api: service.status minion=%s service=%s", minion_id, service)
        return await self._safe_call(minion_id, "service.status", [service])

    async def largest_files(
        self, minion_id, path, min_size="10M", limit=20
    ):
        """Return a bounded, size-sorted list of files on one filesystem."""
        return await self.run_command(
            minion_id,
            build_large_files_command(path, min_size, limit),
        )

    async def service_references(self, minion_id, path):
        """Find systemd unit files that reference an absolute path."""
        return await self.run_command(
            minion_id,
            build_service_references_command(path),
        )

    async def service_logs(self, minion_id, service, lines=50):
        """Get recent journal logs for a service."""
        service = validate_systemd_service(service)
        lines = bounded_int(lines, name="lines", minimum=1, maximum=200)
        logger.debug("salt_api: service_logs minion=%s service=%s", minion_id, service)
        cmd = f"journalctl -u {service} -n {lines} --no-pager"
        return await self.run_command(minion_id, cmd)

    async def failed_systemd_services(self, minion_id):
        """Return failed or auto-restarting services with a fixed command.

        A service with ``Restart=`` may stay in ``activating/auto-restart``
        forever instead of settling in ``failed``. Both states are therefore
        queried. The command is intentionally not supplied by the LLM.
        """
        cmd = (
            "systemctl list-units --type=service --state=failed,activating "
            "--no-legend --no-pager --plain"
        )
        logger.debug("salt_api: failed_systemd_services minion=%s", minion_id)
        return await self.run_command(minion_id, cmd)

    async def service_details(self, minion_id, service):
        """Return bounded diagnostic properties for one systemd service."""
        service = validate_systemd_service(service)
        properties = (
            "Id,Description,LoadState,ActiveState,SubState,Result,"
            "ExecMainCode,ExecMainStatus,NRestarts,Restart,FragmentPath,ExecStart"
        )
        cmd = (
            f"systemctl show {service} --no-pager "
            f"--property={properties}"
        )
        logger.debug("salt_api: service_details minion=%s service=%s", minion_id, service)
        return await self.run_command(minion_id, cmd)

    async def memory_pressure_snapshot(self, minion_id):
        """Return bounded live memory, swap, CPU, and top-RSS evidence."""
        logger.debug("salt_api: memory_pressure_snapshot minion=%s", minion_id)
        return await self.run_command(
            minion_id,
            build_memory_pressure_command(),
        )

    async def cpu_pressure_snapshot(self, minion_id):
        """Return bounded live load, CPU, process, and PSI evidence."""
        logger.debug("salt_api: cpu_pressure_snapshot minion=%s", minion_id)
        return await self.run_command(
            minion_id,
            build_cpu_pressure_command(),
        )

    async def apache_overload_snapshot(self, minion_id):
        """Return bounded Apache load, traffic, backend, and config evidence."""
        logger.debug("salt_api: apache_overload_snapshot minion=%s", minion_id)
        return await self.run_command(
            minion_id,
            build_apache_overload_command(),
        )

    async def postgres_blocking_activity(self, minion_id):
        """Return PostgreSQL blocked/blocker pairs using a fixed read-only SQL."""
        logger.debug("salt_api: postgres_blocking_activity minion=%s", minion_id)
        return await self.run_command(
            minion_id,
            build_postgres_blocking_command(),
        )

    async def postgres_health(self, minion_id):
        """Prove PostgreSQL accepts SQL using a fixed read-only query."""
        logger.debug("salt_api: postgres_health minion=%s", minion_id)
        return await self.run_command(
            minion_id,
            build_postgres_health_command(),
        )

    async def postgres_connection_activity(self, minion_id):
        """Return fixed read-only PostgreSQL connection-capacity evidence."""
        logger.debug(
            "salt_api: postgres_connection_activity minion=%s", minion_id
        )
        return await self.run_command(
            minion_id,
            build_postgres_connection_activity_command(),
        )


# Shared instance used by all tools. Initialized once at startup via
# set_salt_client() from main.run(); tools read salt_api.salt_client at call
# time so the value set after their import is observed.
salt_client: SaltAPIClient | None = None


def set_salt_client(client):
    """Set the shared async Salt client. Called once from main.run() at startup."""
    global salt_client
    salt_client = client
