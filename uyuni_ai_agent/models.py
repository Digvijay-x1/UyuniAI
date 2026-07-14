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

"""Pydantic schemas for structured LLM output.

The ReAct agent investigates an anomaly using Salt tools and produces free-form
reasoning. A final structuring pass converts that reasoning into
``RootCauseAnalysis`` via ``llm.with_structured_output(...)`` so the payload sent
to AlertManager has stable, machine-readable fields (instead of one opaque text
blob). The field layout mirrors the Slack-oriented format in
``prompts/system_prompt.md`` (Root Cause / Key Evidence / Remediation / Urgency).

Only use an LLM/model that advertises native ``json_schema`` structured output
(see ``structured-output-models.md``); JSON-mode-only models do not guarantee the
schema and should be avoided.
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class Urgency(str, Enum):
    """Operator-facing urgency, distinct from the raw Prometheus severity.

    Severity is threshold-derived (warning/critical); urgency is the agent's
    judgement after investigating (a critical metric may be low urgency if it is
    a known transient, and vice-versa).
    """

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class RootCauseAnalysis(BaseModel):
    """Structured root-cause analysis produced by the investigation agent."""

    summary: str = Field(
        description="One-line summary of the issue, suitable for an alert title.",
    )
    affected_component: str = Field(
        description=(
            "The specific component identified as the source of the problem "
            "(e.g. 'PostgreSQL', 'apache2 service', '/var partition', a process "
            "name). Use 'unknown' if the investigation was inconclusive."
        ),
    )
    root_cause: str = Field(
        description=(
            "One or two sentences identifying the root cause, grounded in the "
            "evidence gathered from the Salt tool outputs."
        ),
    )
    key_evidence: List[str] = Field(
        default_factory=list,
        description=(
            "2-3 concrete data points from tool outputs that support the root "
            "cause (e.g. 'postgres using 14.2GB RSS', 'disk /var at 98%')."
        ),
    )
    remediation: List[str] = Field(
        default_factory=list,
        description=(
            "Ordered, concrete remediation steps an operator can take. Most "
            "important first."
        ),
    )
    urgency: Urgency = Field(
        default=Urgency.MEDIUM,
        description="How urgently a human should act on this alert.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "The agent's confidence (0.0-1.0) that the stated root cause is "
            "correct, based on how conclusive the tool evidence was."
        ),
    )

    def to_text(self) -> str:
        """Render a human-readable Slack/email-friendly block.

        Used as the ``description`` annotation fallback and for dry-run logging,
        so a readable form is always available even if a notification template
        only consumes ``description``.
        """
        evidence = "\n".join(f"- {e}" for e in self.key_evidence) or "- (none)"
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(self.remediation, 1)) or "1. (none)"
        return (
            f"*Root Cause:* {self.root_cause}\n\n"
            f"*Affected Component:* {self.affected_component}\n\n"
            f"*Key Evidence:*\n{evidence}\n\n"
            f"*Remediation:*\n{steps}\n\n"
            f"*Urgency:* {self.urgency.value}  |  *Confidence:* {self.confidence:.0%}"
        )
