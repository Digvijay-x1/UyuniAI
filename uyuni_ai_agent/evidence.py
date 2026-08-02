# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Typed, bounded evidence collected before an RCA is synthesized."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from uyuni_ai_agent.models import AnalysisConclusion, RootCauseAnalysis


class EvidenceStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    STALE = "stale"
    ERROR = "error"
    CONTRADICTORY = "contradictory"


class EvidenceRecord(BaseModel):
    """One inspectable fact or bounded command/query result."""

    id: str = Field(pattern=r"^E[1-9][0-9]*$")
    source: str
    target: str
    check: str
    status: EvidenceStatus
    summary: str
    details: str = ""
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    contradicts: list[str] = Field(default_factory=list)


def evidence_status_for(value: Any) -> EvidenceStatus:
    """Classify expected Salt failures without throwing evidence away."""
    if value is False:
        return EvidenceStatus.ERROR
    if value is None:
        return EvidenceStatus.MISSING
    text = str(value).strip()
    if not text:
        return EvidenceStatus.MISSING
    if (
        text.startswith("Salt API call failed:")
        or "minion did not return" in text.lower()
        or "no response from any minions" in text.lower()
    ):
        return EvidenceStatus.ERROR
    return EvidenceStatus.OK


class EvidenceLedger:
    """An ordered evidence collection with stable IDs inside an incident."""

    def __init__(self, target: str):
        self.target = target
        self.records: list[EvidenceRecord] = []

    def add(
        self,
        *,
        source: str,
        check: str,
        status: EvidenceStatus,
        summary: str,
        details: Any = "",
        target: str | None = None,
        detail_limit: int = 12_000,
        contradicts: list[str] | None = None,
    ) -> EvidenceRecord:
        if isinstance(details, str):
            rendered = details
        else:
            rendered = json.dumps(details, default=str, sort_keys=True)
        if len(rendered) > detail_limit:
            rendered = rendered[:detail_limit] + "\n...[truncated]"
        record = EvidenceRecord(
            id=f"E{len(self.records) + 1}",
            source=source,
            target=target or self.target,
            check=check,
            status=status,
            summary=summary,
            details=rendered,
            contradicts=list(contradicts or []),
        )
        self.records.append(record)
        return record

    @property
    def ids(self) -> set[str]:
        return {record.id for record in self.records}

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return next(
            (record for record in self.records if record.id == evidence_id),
            None,
        )

    def to_prompt(self) -> str:
        sections = []
        for record in self.records:
            header = (
                f"[{record.id}] source={record.source} target={record.target} "
                f"check={record.check} status={record.status.value}"
            )
            section = f"{header}\nSUMMARY: {record.summary}"
            if record.details:
                section += f"\nDETAILS:\n{record.details}"
            sections.append(section)
        return "\n\n".join(sections)


_EVIDENCE_ID_RE = re.compile(r"\bE[1-9][0-9]*\b")


def cited_evidence_ids(text: str) -> set[str]:
    return set(_EVIDENCE_ID_RE.findall(text or ""))


def ground_analysis(
    analysis: RootCauseAnalysis,
    ledger: EvidenceLedger,
    *,
    allow_failed_evidence: bool = False,
    max_evidence_age_seconds: float = 300,
    minimum_supporting_records: int = 1,
    now: datetime | None = None,
) -> RootCauseAnalysis:
    """Reject unsupported LLM conclusions and retain only cited evidence.

    This is deliberately structural rather than semantic: the model must cite
    an existing ledger record in both the conclusion and each evidence bullet.
    A future claim verifier can additionally compare the prose to the record.
    """
    allowed = ledger.ids
    supporting = [
        evidence_id
        for evidence_id in dict.fromkeys(analysis.supporting_evidence_ids)
        if evidence_id in allowed
    ]
    supporting_set = set(supporting)
    root_refs = cited_evidence_ids(analysis.root_cause) & allowed
    grounded_bullets = [
        item
        for item in analysis.key_evidence
        if cited_evidence_ids(item) & supporting_set
    ]

    supporting_records = [
        ledger.get(evidence_id) for evidence_id in supporting
    ]
    observed_now = now or datetime.now(UTC)
    if observed_now.tzinfo is None:
        observed_now = observed_now.replace(tzinfo=UTC)
    stale_support = []
    for record in supporting_records:
        if record is None:
            continue
        observed_at = record.observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        age = (observed_now - observed_at).total_seconds()
        if age < 0 or age > max_evidence_age_seconds:
            stale_support.append(record.id)
    contradicted_support = {
        evidence_id
        for record in ledger.records
        for evidence_id in record.contradicts
        if evidence_id in supporting_set
    }
    statuses_are_usable = allow_failed_evidence or all(
        record is not None and record.status is EvidenceStatus.OK
        for record in supporting_records
    )
    confirmed = (
        analysis.conclusion is AnalysisConclusion.CONFIRMED
        and bool(supporting)
        and bool(root_refs & supporting_set)
        and root_refs <= supporting_set
        and bool(grounded_bullets)
        and statuses_are_usable
        and len(supporting) >= max(1, int(minimum_supporting_records))
        and not stale_support
        and not contradicted_support
    )
    if confirmed:
        return analysis.model_copy(
            update={
                "supporting_evidence_ids": supporting,
                "key_evidence": grounded_bullets[:3],
                "remediation": _sanitize_remediation(
                    analysis.remediation, inconclusive=False
                ),
            }
        )

    failed_records = [
        record for record in ledger.records
        if record.status is not EvidenceStatus.OK
    ]
    reasons = [
        f"[{record.id}] {record.summary}" for record in failed_records[:3]
    ]
    if stale_support:
        reasons.append(
            "supporting evidence is stale: "
            + ", ".join(f"[{item}]" for item in stale_support)
        )
    if contradicted_support:
        reasons.append(
            "collected evidence contradicts "
            + ", ".join(f"[{item}]" for item in sorted(contradicted_support))
        )
    if len(supporting) < max(1, int(minimum_supporting_records)):
        reasons.append("too few independent supporting records were cited")
    reason = "; ".join(reasons) or (
        "the proposed cause did not cite the collected evidence"
    )
    fallback_evidence = [
        f"[{record.id}] {record.summary}"
        for record in (failed_records or ledger.records)[:3]
    ]
    return analysis.model_copy(
        update={
            "conclusion": AnalysisConclusion.INCONCLUSIVE,
            "affected_component": "unknown",
            "root_cause": (
                "The investigation is inconclusive because " + reason + "."
            ),
            "supporting_evidence_ids": [
                record.id for record in (failed_records or ledger.records)[:3]
            ],
            "key_evidence": fallback_evidence,
            "remediation": _sanitize_remediation(
                analysis.remediation, inconclusive=True
            ),
            "confidence": min(analysis.confidence, 0.3),
        }
    )


_HIGH_RISK_REMEDIATION = re.compile(
    r"(?i)(?:\brm\s+-rf\b|\bkill\s+-9\b|\bmkfs(?:\.|\s)|"
    r"\bdd\s+if=|\bdrop\s+(?:database|table)\b|\btruncate\s+table\b|"
    r"\b(?:reboot|shutdown)\b)"
)


def _sanitize_remediation(steps: list[str], *, inconclusive: bool) -> list[str]:
    """Remove destructive suggestions and avoid action on unproven causes."""
    safe = [
        step.strip()
        for step in steps
        if step.strip() and not _HIGH_RISK_REMEDIATION.search(step)
    ]
    if inconclusive:
        return [
            "Restore or refresh the missing evidence and repeat the investigation.",
            "Have an operator validate the affected component before changing service state or data.",
        ]
    if len(safe) != len([step for step in steps if step.strip()]):
        safe.append(
            "Escalate destructive recovery actions for explicit operator approval."
        )
    return safe or [
        "Have an operator validate a safe remediation from the cited evidence."
    ]
