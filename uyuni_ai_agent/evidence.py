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

from datetime import datetime, timezone
from enum import Enum
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from uyuni_ai_agent.models import AnalysisConclusion, RootCauseAnalysis


class EvidenceStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    STALE = "stale"
    ERROR = "error"


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
        default_factory=lambda: datetime.now(timezone.utc)
    )


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
    )
    if confirmed:
        return analysis.model_copy(
            update={
                "supporting_evidence_ids": supporting,
                "key_evidence": grounded_bullets[:3],
            }
        )

    failed_records = [
        record for record in ledger.records
        if record.status is not EvidenceStatus.OK
    ]
    reason = (
        "; ".join(
            f"[{record.id}] {record.summary}" for record in failed_records[:3]
        )
        or "the proposed cause did not cite the collected evidence"
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
            "confidence": min(analysis.confidence, 0.3),
        }
    )
