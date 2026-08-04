from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_agent_scrape_job_is_explicit_and_bounded():
    config = yaml.safe_load(
        (ROOT / "deploy/monitoring/prometheus-agent-scrape.yml").read_text()
    )

    jobs = config["scrape_configs"]
    assert len(jobs) == 1
    assert jobs[0]["job_name"] == "uyuni-ai-agent"
    assert jobs[0]["scrape_timeout"] == "10s"
    assert jobs[0]["static_configs"][0]["targets"] == [
        "UYUNI_AGENT_TARGET:9898"
    ]


def test_self_alerts_cover_availability_dependencies_and_backpressure():
    config = yaml.safe_load(
        (ROOT / "deploy/monitoring/agent-self-alerts.yml").read_text()
    )
    rules = [
        rule
        for group in config["groups"]
        for rule in group["rules"]
    ]
    names = {rule["alert"] for rule in rules}

    assert {
        "UyuniAIAgentTargetDown",
        "UyuniAIAgentNotReady",
        "UyuniAIAgentPollStalled",
        "UyuniAIAgentDependencyCircuitOpen",
        "UyuniAIAgentQueueSaturated",
        "UyuniAIAgentAlertDeliveryFailures",
    } <= names
    assert all(rule.get("labels", {}).get("severity") for rule in rules)


def test_metrics_proxy_is_source_restricted_and_socket_activated():
    root = ROOT / "deploy/monitoring"
    socket = (root / "uyuni-ai-agent-metrics-proxy.socket").read_text()
    service = (root / "uyuni-ai-agent-metrics-proxy.service").read_text()
    firewall = (root / "uyuni-ai-agent-metrics.nft").read_text()
    proxy = (root / "uyuni-ai-agent-metrics-proxy").read_text()

    assert "ListenStream=0.0.0.0:9898" in socket
    assert "uyuni-ai-agent-metrics-firewall.service" in socket
    assert "NoNewPrivileges=yes" in service
    assert "ReadWritePaths=" not in service
    assert "Restart=" not in service
    assert "MONITORING_SERVER_IP tcp dport 9898 accept" in firewall
    assert "tcp dport 9898 counter drop" in firewall
    assert "systemd-socket-proxyd" in proxy
    assert "127.0.0.1:19898" in proxy
    assert "podman inspect" not in proxy


def test_production_quadlet_exposes_only_a_loopback_metrics_backend():
    quadlet = (ROOT / "deploy/agent/uyuni-ai-agent.container").read_text()

    assert "PublishPort=127.0.0.1:19898:9898" in quadlet
    assert "HealthCmd=/usr/local/bin/python" in quadlet


def test_agent_monitoring_installers_render_site_specific_addresses():
    monitoring_installer = (
        ROOT / "deploy/monitoring/install-agent-monitoring.sh"
    ).read_text()
    proxy_installer = (
        ROOT / "deploy/agent/install-metrics-proxy.sh"
    ).read_text()

    assert "UYUNI_AGENT_TARGET" in monitoring_installer
    assert "MONITORING_SERVER_IP" in proxy_installer
    assert "monitoring-server-ipv4" in proxy_installer
