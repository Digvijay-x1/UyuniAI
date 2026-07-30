from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.react_agent import ALL_TOOLS, get_prompt_for_anomaly


def test_service_anomaly_uses_service_rca_prompt_and_registered_tools():
    anomaly = Anomaly(
        minion_id="client",
        metric_name="service_down",
        current_value=1,
        threshold=1,
        severity=AlertSeverity.CRITICAL,
        description="Systemd service my-web.service is in failed state",
        service_name="my-web.service",
    )

    prompt = get_prompt_for_anomaly(anomaly, {"memory_percent": 10})
    tool_names = {tool.name for tool in ALL_TOOLS}

    assert 'service="my-web.service"' in prompt
    assert "get_service_details" in prompt
    assert "get_service_logs" in prompt
    assert "get_listening_ports" in prompt
    assert "get_service_details" in tool_names


def test_disk_anomaly_requires_file_and_service_correlation():
    anomaly = Anomaly(
        minion_id="client",
        metric_name="disk",
        current_value=96,
        threshold=95,
        severity=AlertSeverity.CRITICAL,
        description="Filesystem /mnt/my-lab-disk usage at 96.0",
        resource="/mnt/my-lab-disk",
        context={
            "mountpoint": "/mnt/my-lab-disk",
            "device": "/dev/loop0",
            "related_unhealthy_services": ["my-crashloop.service"],
        },
    )

    prompt = get_prompt_for_anomaly(anomaly, {"disk_percent": 10})
    tool_names = {tool.name for tool in ALL_TOOLS}

    assert 'path="/mnt/my-lab-disk"' in prompt
    assert "my-crashloop.service" in prompt
    assert "find_service_references" in prompt
    assert "find_service_references" in tool_names
