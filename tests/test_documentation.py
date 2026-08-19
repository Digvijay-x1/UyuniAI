import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def markdown_files():
    yield from ROOT.glob("*.md")
    yield from (ROOT / "docs").rglob("*.md")


def test_relative_markdown_links_resolve():
    missing = []

    for document in markdown_files():
        content = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(content):
            target = raw_target.strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative_path = target.split("#", 1)[0]
            if relative_path and not (document.parent / relative_path).exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")

    assert not missing, "Missing documentation targets:\n" + "\n".join(missing)


def test_every_self_monitoring_alert_has_a_runbook_mapping():
    rules = yaml.safe_load(
        (ROOT / "deploy/monitoring/agent-self-alerts.yml").read_text(
            encoding="utf-8"
        )
    )
    alert_names = {
        rule["alert"]
        for group in rules["groups"]
        for rule in group["rules"]
    }
    runbook_index = (
        ROOT / "docs/runbooks/README.md"
    ).read_text(encoding="utf-8")

    missing = sorted(
        alert_name
        for alert_name in alert_names
        if f"`{alert_name}`" not in runbook_index
    )

    assert not missing, "Self-alerts without runbooks: " + ", ".join(missing)
