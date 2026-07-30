import asyncio

from uyuni_ai_agent.anomaly_detector import (
    AlertSeverity,
    filesystem_anomalies,
)
from uyuni_ai_agent.prometheus_client import get_filesystem_usage_percent


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "data": {
                "result": [
                    {
                        "metric": {
                            "device": "/dev/vda1",
                            "fstype": "ext4",
                            "mountpoint": "/",
                        },
                        "value": [0, "10.5"],
                    },
                    {
                        "metric": {
                            "device": "/dev/loop0",
                            "fstype": "ext4",
                            "mountpoint": "/mnt/my-lab-disk",
                        },
                        "value": [0, "91.25"],
                    },
                ]
            }
        }


class FakeClient:
    def __init__(self):
        self.query = None

    async def get(self, url, params, timeout):
        self.query = params["query"]
        return FakeResponse()


def test_prometheus_filesystem_discovery_returns_all_mounts():
    client = FakeClient()
    filesystems = asyncio.run(get_filesystem_usage_percent(
        "client:9100", client, "http://prometheus:9090"
    ))

    assert [item["mountpoint"] for item in filesystems] == [
        "/",
        "/mnt/my-lab-disk",
    ]
    assert filesystems[1]["usage_percent"] == 91.25
    assert "node_filesystem_readonly" in client.query
    assert 'fstype!~"' in client.query


def test_only_over_threshold_mount_gets_resource_specific_anomaly():
    filesystems = [
        {
            "mountpoint": "/",
            "device": "/dev/vda1",
            "fstype": "ext4",
            "usage_percent": 10.5,
        },
        {
            "mountpoint": "/mnt/my-lab-disk",
            "device": "/dev/loop0",
            "fstype": "ext4",
            "usage_percent": 96.0,
        },
    ]

    anomalies = filesystem_anomalies(
        filesystems,
        {"warning": 75, "critical": 95},
        "client",
    )

    assert len(anomalies) == 1
    assert anomalies[0].resource == "/mnt/my-lab-disk"
    assert anomalies[0].severity is AlertSeverity.CRITICAL
    assert anomalies[0].context["device"] == "/dev/loop0"


def test_disk_anomalies_on_different_mounts_have_distinct_identities():
    filesystems = [
        {
            "mountpoint": mountpoint,
            "device": device,
            "fstype": "ext4",
            "usage_percent": 80.0,
        }
        for mountpoint, device in [
            ("/var", "/dev/vda2"),
            ("/srv", "/dev/vda3"),
        ]
    ]

    anomalies = filesystem_anomalies(
        filesystems,
        {"warning": 75, "critical": 95},
        "client",
    )

    assert anomalies[0].identity_key() != anomalies[1].identity_key()
