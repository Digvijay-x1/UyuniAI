# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Runtime minion discovery from Uyuni and Prometheus.

Uyuni is the authority for which systems the agent may inspect. Prometheus is
only used to map those trusted minion IDs to exporter ``instance`` labels; a
Prometheus label can never add a Salt target to the allowlist.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class InventoryError(RuntimeError):
    """Raised when a discovery response is unavailable or malformed."""


def _bounded_error(value: object, limit: int = 300) -> str:
    return str(value).strip().replace("\x00", "")[:limit]


def _api_value(payload: object) -> object:
    if not isinstance(payload, Mapping):
        raise InventoryError("Uyuni API response must be a JSON object")
    if payload.get("success") is False:
        raise InventoryError(
            f"Uyuni API request failed: {_bounded_error(payload.get('message'))}"
        )
    result = payload.get("result")
    # Uyuni's REST facade wraps the method return value in a result array.
    if isinstance(result, list) and len(result) == 1:
        result = result[0]
    return result


def _api_result(payload: object) -> list[object]:
    result = _api_value(payload)
    if not isinstance(result, list):
        raise InventoryError("Uyuni API result must be a list")
    return result


class UyuniAPIClient:
    """Authenticated client for the Uyuni manager REST API."""

    def __init__(self, config: Mapping, client: httpx.AsyncClient | None = None):
        api = config["uyuni_api"]
        self.url = str(api["url"]).rstrip("/")
        self.username = str(api["username"])
        self.password = str(api.get("password", ""))
        self._client = client or httpx.AsyncClient(
            verify=bool(api.get("verify_tls", True)),
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    async def login(self) -> None:
        async with self._login_lock:
            if self._logged_in:
                return
            response = await self._client.post(
                f"{self.url}/auth/login",
                json={"login": self.username, "password": self.password},
            )
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise InventoryError(
                    f"Uyuni API login failed: HTTP {response.status_code}"
                ) from exc
            self._logged_in = True

    async def _get(self, path: str) -> object:
        if not self._logged_in:
            await self.login()
        response = await self._client.get(f"{self.url}/{path.lstrip('/')}")
        if response.status_code == 401:
            self._logged_in = False
            await self.login()
            response = await self._client.get(f"{self.url}/{path.lstrip('/')}")
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise InventoryError(
                f"Uyuni API request failed: HTTP {response.status_code}"
            ) from exc
        except ValueError as exc:
            raise InventoryError("Uyuni API returned invalid JSON") from exc

    async def list_active_systems(self) -> list[dict]:
        active_payload, id_map_payload = await asyncio.gather(
            self._get("system/listActiveSystems"),
            self._get("system/getMinionIdMap"),
        )
        result = _api_result(active_payload)
        id_map = _api_value(id_map_payload)
        if not isinstance(id_map, Mapping):
            raise InventoryError("Uyuni minion ID map must be an object")
        system_to_minion = {
            str(system_id): str(minion_id).strip()
            for minion_id, system_id in id_map.items()
            if str(minion_id).strip()
        }
        systems: list[dict] = []
        for item in result:
            if not isinstance(item, Mapping):
                raise InventoryError("Uyuni active-system entry must be an object")
            name = str(item.get("name", "")).strip()
            if not name:
                raise InventoryError("Uyuni active-system entry has no name")
            minion_id = system_to_minion.get(str(item.get("id")))
            if minion_id:
                system = dict(item)
                system["minion_id"] = minion_id
                systems.append(system)
        return systems

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


async def list_prometheus_targets(
    client: httpx.AsyncClient,
    prometheus_url: str,
) -> list[dict]:
    """Return configured active scrape targets from Prometheus."""
    url = f"{prometheus_url.rstrip('/')}/api/v1/targets"
    try:
        response = await client.get(url, params={"state": "active"}, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise InventoryError(
            f"Prometheus target discovery failed: {_bounded_error(exc)}"
        ) from exc
    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        raise InventoryError("Prometheus target discovery returned an error")
    data = payload.get("data")
    targets = data.get("activeTargets") if isinstance(data, Mapping) else None
    if not isinstance(targets, list):
        raise InventoryError("Prometheus activeTargets must be a list")
    if not all(isinstance(item, Mapping) for item in targets):
        raise InventoryError("Prometheus target entry must be an object")
    return [dict(item) for item in targets]


def _normalized_host(value: object) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        return ""
    if "://" in rendered:
        return (urlparse(rendered).hostname or "").lower().rstrip(".")
    if rendered.startswith("[") and "]" in rendered:
        return rendered[1 : rendered.index("]")].lower().rstrip(".")
    host, separator, port = rendered.rpartition(":")
    if separator and host and port.isdigit():
        rendered = host
    return rendered.lower().rstrip(".")


def _short_host(value: str) -> str:
    return value.split(".", 1)[0]


def _target_indexes(
    targets: list[dict], job_config: Mapping[str, list[str]]
) -> dict[str, dict[str, str]]:
    job_to_service = {
        job.lower(): service
        for service, jobs in job_config.items()
        for job in jobs
    }
    indexes: dict[str, dict[str, str]] = {
        "node": {},
        "apache": {},
        "postgres": {},
    }
    for target in targets:
        labels = target.get("labels")
        discovered = target.get("discoveredLabels")
        labels = labels if isinstance(labels, Mapping) else {}
        discovered = discovered if isinstance(discovered, Mapping) else {}
        job = str(labels.get("job") or discovered.get("job") or "").lower()
        service = job_to_service.get(job)
        if service is None:
            continue
        instance = str(
            labels.get("instance") or discovered.get("__address__") or ""
        ).strip()
        if not instance:
            continue
        aliases = {
            _normalized_host(instance),
            _normalized_host(discovered.get("__address__")),
            _normalized_host(target.get("scrapeUrl")),
        }
        for alias in aliases - {""}:
            indexes[service].setdefault(alias, instance)
    return indexes


def _find_target(index: Mapping[str, str], system_names: set[str]) -> str | None:
    for name in sorted(system_names, key=len, reverse=True):
        if name in index:
            return index[name]
    short_names = {_short_host(name) for name in system_names}
    matches = {
        instance
        for host, instance in index.items()
        if _short_host(host) in short_names
    }
    return next(iter(matches)) if len(matches) == 1 else None


def build_minion_inventory(
    systems: list[dict],
    targets: list[dict],
    inventory_config: Mapping,
) -> list[dict]:
    """Join trusted Uyuni systems with Prometheus exporter labels."""
    jobs = inventory_config.get("prometheus_jobs", {})
    indexes = _target_indexes(targets, jobs)
    node_port = int(inventory_config.get("node_exporter_port", 9100))
    minions: list[dict] = []
    seen: set[str] = set()
    for system in systems:
        name = str(system.get("name", "")).strip()
        minion_id = str(system.get("minion_id") or name).strip()
        if not minion_id:
            raise InventoryError("Uyuni system has no usable minion ID")
        if minion_id in seen:
            raise InventoryError(f"duplicate Uyuni minion ID: {minion_id}")
        seen.add(minion_id)
        system_names = {
            alias
            for alias in (_normalized_host(minion_id), _normalized_host(name))
            if alias
        }
        node_instance = _find_target(indexes["node"], system_names)
        minion = {
            "id": minion_id,
            # A missing target is still monitored: its expected node-exporter
            # label yields explicit missing-telemetry evidence.
            "instance": node_instance or f"{minion_id}:{node_port}",
        }
        apache_instance = _find_target(indexes["apache"], system_names)
        postgres_instance = _find_target(indexes["postgres"], system_names)
        if apache_instance:
            minion["apache_instance"] = apache_instance
        if postgres_instance:
            minion["postgres_instance"] = postgres_instance
        minions.append(minion)
    return sorted(minions, key=lambda item: item["id"])


class InventoryProvider:
    """Refreshable inventory with last-known-good failure behavior."""

    def __init__(self, config: Mapping):
        self._config = config
        self._settings = config.get("inventory", {"provider": "static"})
        self._static = [dict(item) for item in config.get("minions", [])]
        self._uyuni = (
            UyuniAPIClient(config)
            if self._settings.get("provider", "static") == "uyuni"
            else None
        )
        self._last_good: list[dict] | None = None
        self._refreshed_at = 0.0
        self._lock = asyncio.Lock()

    async def refresh(
        self,
        prometheus_client: httpx.AsyncClient,
        *,
        force: bool = False,
    ) -> list[dict]:
        if self._uyuni is None:
            return [dict(item) for item in self._static]
        interval = float(self._settings.get("refresh_interval_seconds", 60))
        now = time.monotonic()
        if (
            not force
            and self._last_good is not None
            and now - self._refreshed_at < interval
        ):
            return [dict(item) for item in self._last_good]
        async with self._lock:
            try:
                systems, targets = await asyncio.gather(
                    self._uyuni.list_active_systems(),
                    list_prometheus_targets(
                        prometheus_client, self._config["prometheus"]["url"]
                    ),
                )
                discovered = build_minion_inventory(
                    systems, targets, self._settings
                )
            except Exception as exc:
                if self._last_good is None:
                    raise
                logger.warning(
                    "Inventory refresh failed; retaining %d last-known-good "
                    "minion(s): %s",
                    len(self._last_good),
                    exc,
                )
                return [dict(item) for item in self._last_good]
            self._last_good = discovered
            self._refreshed_at = time.monotonic()
            logger.info(
                "Discovered %d active Uyuni minion(s); Apache=%d PostgreSQL=%d",
                len(discovered),
                sum("apache_instance" in item for item in discovered),
                sum("postgres_instance" in item for item in discovered),
            )
            return [dict(item) for item in discovered]

    async def aclose(self) -> None:
        if self._uyuni is not None:
            await self._uyuni.aclose()
