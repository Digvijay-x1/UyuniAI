from uyuni_ai_agent.alert_manager import (
    build_alert_payload,
    build_resolved_payload,
)
from uyuni_ai_agent.models import (
    AnalysisConclusion,
    RootCauseAnalysis,
    Urgency,
)


def test_alert_payload_exposes_conclusion_and_evidence_ids():
    analysis = RootCauseAnalysis(
        summary="Exporter unavailable",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component="apache_exporter",
        root_cause="Prometheus reports the target down [E2].",
        supporting_evidence_ids=["E2"],
        key_evidence=["[E2] up=0"],
        remediation=["Restart the exporter"],
        urgency=Urgency.MEDIUM,
        confidence=1,
    )

    payload = build_alert_payload(
        analysis,
        severity="warning",
        minion_id="client2",
        metric_name="telemetry_unavailable",
        resource="telemetry:apache_exporter:client2:9117",
        incident_id="incident-123",
        starts_at="2026-07-31T00:00:00Z",
    )

    assert payload["annotations"]["conclusion"] == "confirmed"
    assert payload["annotations"]["supporting_evidence_ids"] == "E2"
    assert "*Conclusion:* confirmed" in payload["annotations"]["description"]
    assert payload["labels"]["incident_id"] == "incident-123"
    assert "component" not in payload["labels"]
    assert payload["startsAt"] == "2026-07-31T00:00:00Z"

    resolved = build_resolved_payload(
        payload, ends_at="2026-07-31T00:10:00Z"
    )
    assert resolved["labels"] == payload["labels"]
    assert resolved["startsAt"] == payload["startsAt"]
    assert resolved["endsAt"] == "2026-07-31T00:10:00Z"
