import asyncio

from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.evidence import (
    EvidenceLedger,
    EvidenceStatus,
    ground_analysis,
)
from uyuni_ai_agent.models import (
    AnalysisConclusion,
    RootCauseAnalysis,
    Urgency,
)
from uyuni_ai_agent.react_agent import investigate


def analysis(**overrides):
    values = {
        "summary": "Disk incident",
        "conclusion": AnalysisConclusion.CONFIRMED,
        "affected_component": "/var",
        "root_cause": "A crash loop filled the disk [E1].",
        "supporting_evidence_ids": ["E1"],
        "key_evidence": ["[E1] /var is full"],
        "remediation": ["Stop the crash loop"],
        "urgency": Urgency.CRITICAL,
        "confidence": 0.9,
    }
    values.update(overrides)
    return RootCauseAnalysis(**values)


def test_ledger_assigns_stable_ids_and_renders_bounded_records():
    ledger = EvidenceLedger("client")
    first = ledger.add(
        source="prometheus",
        check="disk_usage",
        status=EvidenceStatus.OK,
        summary="Filesystem /var is 98% full",
        details="x" * 100,
        detail_limit=20,
    )
    second = ledger.add(
        source="salt",
        check="largest_files",
        status=EvidenceStatus.OK,
        summary="application.log is the largest file",
    )

    assert (first.id, second.id) == ("E1", "E2")
    assert "[E1]" in ledger.to_prompt()
    assert "...[truncated]" in first.details


def test_confirmed_analysis_with_valid_citations_is_preserved():
    ledger = EvidenceLedger("client")
    ledger.add(
        source="salt",
        check="disk_usage",
        status=EvidenceStatus.OK,
        summary="Filesystem /var is full",
    )

    result = ground_analysis(analysis(), ledger)

    assert result.conclusion is AnalysisConclusion.CONFIRMED
    assert result.confidence == 0.9


def test_uncited_analysis_is_downgraded_to_inconclusive():
    ledger = EvidenceLedger("client")
    ledger.add(
        source="salt",
        check="disk_usage",
        status=EvidenceStatus.OK,
        summary="Filesystem /var is full",
    )

    result = ground_analysis(analysis(
        root_cause="A crash loop filled the disk.",
        supporting_evidence_ids=["E999"],
        key_evidence=["The log is large"],
    ), ledger)

    assert result.conclusion is AnalysisConclusion.INCONCLUSIVE
    assert result.affected_component == "unknown"
    assert result.confidence == 0.3
    assert result.key_evidence == ["[E1] Filesystem /var is full"]


def test_citations_must_match_declared_supporting_records():
    ledger = EvidenceLedger("client")
    ledger.add(
        source="salt",
        check="disk_usage",
        status=EvidenceStatus.OK,
        summary="Filesystem /var is full",
    )
    ledger.add(
        source="salt",
        check="largest_files",
        status=EvidenceStatus.OK,
        summary="application.log is the largest file",
    )

    result = ground_analysis(analysis(
        root_cause="A crash loop filled the disk [E1].",
        supporting_evidence_ids=["E2"],
        key_evidence=["[E1] /var is full"],
    ), ledger)

    assert result.conclusion is AnalysisConclusion.INCONCLUSIVE


def test_failed_collection_forces_conservative_explanation():
    ledger = EvidenceLedger("client")
    ledger.add(
        source="salt",
        check="service_logs",
        status=EvidenceStatus.ERROR,
        summary="Salt service log inspection failed",
    )

    result = ground_analysis(analysis(), ledger)

    assert result.conclusion is AnalysisConclusion.INCONCLUSIVE
    assert "[E1] Salt service log inspection failed" in result.root_cause


def test_telemetry_blind_spot_produces_deterministic_cited_analysis(monkeypatch):
    anomaly = Anomaly(
        minion_id="client2",
        metric_name="telemetry_unavailable",
        current_value=1,
        threshold=1,
        severity=AlertSeverity.WARNING,
        description="apache_exporter telemetry is unavailable",
        resource="telemetry:apache_exporter:client2:9117",
        context={
            "exporter": "apache_exporter",
            "target": "client2:9117",
            "observations": [{
                "name": "apache_exporter_up",
                "status": "error",
                "value": 0,
                "error": "Prometheus target reports up=0",
            }],
        },
    )

    def fail_if_llm_is_built(config):
        raise AssertionError("telemetry coverage RCA must not call an LLM")

    monkeypatch.setattr(
        "uyuni_ai_agent.react_agent.get_agent", fail_if_llm_is_built
    )
    result = asyncio.run(investigate(anomaly, {}, {}))

    assert result.conclusion is AnalysisConclusion.CONFIRMED
    assert result.supporting_evidence_ids == ["E2"]
    assert "[E2]" in result.root_cause
    assert result.confidence == 1.0


def test_salt_blind_spot_produces_source_specific_analysis(monkeypatch):
    anomaly = Anomaly(
        minion_id="client",
        metric_name="telemetry_unavailable",
        current_value=1,
        threshold=1,
        severity=AlertSeverity.WARNING,
        description="Salt inspection telemetry is unavailable",
        resource="telemetry:salt_inspection:client",
        context={
            "source": "salt",
            "exporter": "salt_inspection",
            "target": "client",
            "observations": [{
                "name": "systemd_service_discovery",
                "status": "error",
                "error": "minion returned no result",
            }],
        },
    )

    monkeypatch.setattr(
        "uyuni_ai_agent.react_agent.get_agent",
        lambda _config: (_ for _ in ()).throw(
            AssertionError("Salt coverage RCA must not call an LLM")
        ),
    )
    result = asyncio.run(investigate(anomaly, {}, {}))

    assert result.conclusion is AnalysisConclusion.CONFIRMED
    assert "Salt cannot provide trustworthy inspection results" in result.root_cause
    assert result.supporting_evidence_ids == ["E2"]
