# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Privacy-preserving LangSmith spans for non-LLM investigation paths."""

from __future__ import annotations

import re

from langsmith import traceable

_SAFE_FIELDS = frozenset(
    {
        "anomaly_type",
        "analyzer",
        "evidence_categories",
        "evidence_count",
        "conclusion",
        "confidence",
        "urgency",
        "llm_used",
    }
)
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_EVIDENCE_CATEGORIES = {
    "apache_dependency_snapshot": "apache_dependency",
    "apache_overload_snapshot": "apache",
    "cpu_pressure_snapshot": "cpu",
    "detector": "detector",
    "disk_usage": "disk",
    "largest_files": "filesystem",
    "listening_tcp_ports": "network_listener",
    "memory_pressure_snapshot": "memory",
    "postgres_blocking_activity": "postgres_locks",
    "postgres_connection_activity": "postgres_connections",
    "postgres_health": "postgres_health",
    "service_details": "service_state",
    "service_logs": "service_logs",
}
_SAFE_CATEGORY_VALUES = frozenset(
    {
        *_EVIDENCE_CATEGORIES.values(),
        "nfs_dependency",
        "ssh_dependency",
        "tls_dependency",
    }
)


def _sanitize_identifier(value: object) -> str:
    text = str(value).strip().lower()
    return text if _SAFE_IDENTIFIER.fullmatch(text) else "other"


def evidence_categories(records) -> list[str]:
    """Map evidence checks to controlled categories without IDs or targets."""
    categories = set()
    for record in records:
        check = str(getattr(record, "check", ""))
        prefix, _, suffix = check.partition(":")
        if prefix == "dependency_inspection" and suffix:
            protocol = suffix.partition(":")[0]
            if protocol in {"ssh", "tls", "nfs"}:
                categories.add(f"{protocol}_dependency")
            continue
        category = _EVIDENCE_CATEGORIES.get(prefix)
        if category is not None:
            categories.add(category)
    return sorted(categories)


def _allowlisted_payload(payload: dict) -> dict:
    """Return only normalized values that are safe to upload to LangSmith."""
    sanitized = {}
    for field in ("anomaly_type", "analyzer", "conclusion", "urgency"):
        if field in payload:
            sanitized[field] = _sanitize_identifier(payload[field])
    if "evidence_categories" in payload:
        values = payload["evidence_categories"]
        if not isinstance(values, (list, tuple, set, frozenset)):
            values = []
        sanitized["evidence_categories"] = sorted(
            {str(value) for value in values if str(value) in _SAFE_CATEGORY_VALUES}
        )
    if "evidence_count" in payload:
        try:
            sanitized["evidence_count"] = max(
                0, min(int(payload["evidence_count"]), 10_000)
            )
        except (TypeError, ValueError):
            sanitized["evidence_count"] = 0
    if "confidence" in payload:
        try:
            sanitized["confidence"] = max(0.0, min(float(payload["confidence"]), 1.0))
        except (TypeError, ValueError):
            sanitized["confidence"] = 0.0
    if "llm_used" in payload:
        sanitized["llm_used"] = bool(payload["llm_used"])
    return {key: sanitized[key] for key in _SAFE_FIELDS if key in sanitized}


def _process_inputs(inputs: dict) -> dict:
    return _allowlisted_payload(inputs)


def _process_outputs(outputs: dict) -> dict:
    return _allowlisted_payload(outputs)


@traceable(
    name="deterministic_rca",
    run_type="chain",
    tags=["deterministic", "no-llm", "sanitized"],
    metadata={"data_policy": "allowlisted-metadata-only"},
    process_inputs=_process_inputs,
    process_outputs=_process_outputs,
    dangerously_allow_filesystem=False,
)
def record_deterministic_rca(
    *,
    anomaly_type: str,
    analyzer: str,
    evidence_categories: list[str],
    evidence_count: int,
    conclusion: str,
    confidence: float,
    urgency: str,
    llm_used: bool = False,
) -> dict:
    """Emit one sanitized span and return exactly the recorded metadata."""
    return _allowlisted_payload(
        {
            "anomaly_type": anomaly_type,
            "analyzer": analyzer,
            "evidence_categories": evidence_categories,
            "evidence_count": evidence_count,
            "conclusion": conclusion,
            "confidence": confidence,
            "urgency": urgency,
            "llm_used": llm_used,
        }
    )
