from uyuni_ai_agent.evidence import EvidenceLedger, EvidenceStatus
from uyuni_ai_agent.langsmith_tracing import (
    _process_inputs,
    evidence_categories,
    record_deterministic_rca,
)


def test_evidence_categories_remove_targets_paths_and_dependency_ids():
    ledger = EvidenceLedger("customer-host.example")
    ledger.add(
        source="salt",
        target="customer-host.example",
        check="service_logs:secret-backup.service",
        status=EvidenceStatus.OK,
        summary="contains customer data",
        details="raw journal must not be traced",
    )
    ledger.add(
        source="salt",
        target="source->target",
        check="dependency_inspection:ssh:customer-edge-id",
        status=EvidenceStatus.OK,
        summary="fingerprints",
        details="SHA256:sensitive",
    )

    assert evidence_categories(ledger.records) == [
        "service_logs",
        "ssh_dependency",
    ]


def test_trace_processors_allowlist_only_safe_metadata():
    processed = _process_inputs({
        "analyzer": "ssh_host_key_mismatch",
        "evidence_count": 2,
        "config": {"password": "must-not-leave-process"},
        "raw_evidence": "must-not-leave-process",
        "hostname": "customer-host.example",
        "fingerprint": "SHA256:sensitive",
    })

    assert processed == {
        "analyzer": "ssh_host_key_mismatch",
        "evidence_count": 2,
    }


def test_trace_input_processor_normalizes_allowlisted_fields():
    processed = _process_inputs({
        "anomaly_type": "customer-host.example",
        "analyzer": "tls_identity_mismatch",
        "evidence_categories": ["tls_dependency", "customer-secret"],
        "evidence_count": "not-a-number",
        "conclusion": "fingerprint SHA256:sensitive",
        "confidence": 12,
        "urgency": "High Priority",
        "llm_used": False,
    })

    assert processed == {
        "anomaly_type": "other",
        "analyzer": "tls_identity_mismatch",
        "evidence_categories": ["tls_dependency"],
        "evidence_count": 0,
        "conclusion": "other",
        "confidence": 1.0,
        "urgency": "other",
        "llm_used": False,
    }


def test_deterministic_span_payload_is_bounded_and_sanitized(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    payload = record_deterministic_rca(
        anomaly_type="SERVICE_DOWN",
        analyzer="ssh_host_key_mismatch",
        evidence_categories=["ssh_dependency", "service_logs", "service_logs"],
        evidence_count=2,
        conclusion="confirmed",
        confidence=1.5,
        urgency="Critical",
    )

    assert payload == {
        "anomaly_type": "service_down",
        "analyzer": "ssh_host_key_mismatch",
        "evidence_categories": ["service_logs", "ssh_dependency"],
        "evidence_count": 2,
        "conclusion": "confirmed",
        "confidence": 1.0,
        "urgency": "critical",
        "llm_used": False,
    }
