import asyncio

import httpx
import pytest

from uyuni_ai_agent.inventory import (
    InventoryError,
    UyuniAPIClient,
    build_minion_inventory,
    list_prometheus_targets,
)


def inventory_settings():
    return {
        "node_exporter_port": 9100,
        "prometheus_jobs": {
            "node": ["node"],
            "apache": ["apache"],
            "postgres": ["postgres"],
        },
    }


def target(job, instance, *, address=None):
    return {
        "labels": {"job": job, "instance": instance},
        "discoveredLabels": {"__address__": address or instance},
        "scrapeUrl": f"http://{address or instance}/metrics",
        "health": "up",
    }


def test_uyuni_inventory_is_the_authority_and_prometheus_only_adds_endpoints():
    systems = [
        {"id": 1, "name": "db01.example.com"},
        {"id": 2, "name": "web01.example.com"},
    ]
    targets = [
        target("node", "db01.example.com:9100"),
        target("postgres", "db01.example.com:9187"),
        target("node", "web01.example.com:9100"),
        target("apache", "web01.example.com:9117"),
        target("node", "prometheus-only.example.com:9100"),
    ]

    discovered = build_minion_inventory(
        systems, targets, inventory_settings()
    )

    assert discovered == [
        {
            "id": "db01.example.com",
            "instance": "db01.example.com:9100",
            "postgres_instance": "db01.example.com:9187",
        },
        {
            "id": "web01.example.com",
            "instance": "web01.example.com:9100",
            "apache_instance": "web01.example.com:9117",
        },
    ]


def test_missing_node_target_remains_visible_as_missing_telemetry():
    discovered = build_minion_inventory(
        [{"id": 1, "name": "new-client.example.com"}],
        [],
        inventory_settings(),
    )

    assert discovered == [
        {
            "id": "new-client.example.com",
            "instance": "new-client.example.com:9100",
        }
    ]


def test_short_prometheus_hostname_matches_an_unambiguous_fqdn():
    discovered = build_minion_inventory(
        [{"id": 1, "name": "client01.example.com"}],
        [target("node", "client01:9100")],
        inventory_settings(),
    )

    assert discovered[0]["instance"] == "client01:9100"


def test_duplicate_uyuni_minion_ids_are_rejected():
    with pytest.raises(InventoryError, match="duplicate Uyuni minion ID"):
        build_minion_inventory(
            [{"name": "same"}, {"name": "same"}],
            [],
            inventory_settings(),
        )


def test_uyuni_rest_login_and_wrapped_active_system_result():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"success": True, "result": [1]})
        if request.url.path.endswith("/getMinionIdMap"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": [{"client.example.com": 42}],
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [[{"id": 42, "name": "client.example.com"}]],
            },
        )

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = UyuniAPIClient(
                {
                    "uyuni_api": {
                        "url": "https://uyuni.example/rhn/manager/api",
                        "username": "agent",
                        "password": "secret",
                    }
                },
                client=http_client,
            )
            return await client.list_active_systems()

    assert asyncio.run(scenario()) == [
        {
            "id": 42,
            "name": "client.example.com",
            "minion_id": "client.example.com",
        }
    ]
    assert calls[0] == ("POST", "/rhn/manager/api/auth/login")
    assert set(calls[1:]) == {
        ("GET", "/rhn/manager/api/system/listActiveSystems"),
        ("GET", "/rhn/manager/api/system/getMinionIdMap"),
    }


def test_prometheus_target_discovery_rejects_malformed_payload():
    async def scenario():
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"status": "success", "data": {}}
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await list_prometheus_targets(client, "http://prometheus:9090")

    with pytest.raises(InventoryError, match="activeTargets must be a list"):
        asyncio.run(scenario())
