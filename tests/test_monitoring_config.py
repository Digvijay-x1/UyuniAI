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
        "139.59.3.229:9898"
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
