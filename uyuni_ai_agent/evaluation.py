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

"""Machine-readable RCA evaluation scenarios and transparent scoring."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from uyuni_ai_agent.models import AnalysisConclusion, RootCauseAnalysis


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RCAExpectation(_StrictModel):
    conclusion: AnalysisConclusion
    component_pattern: str = ".+"
    required_concept_groups: list[list[str]] = Field(default_factory=list)
    forbidden_phrases: list[str] = Field(default_factory=list)
    remediation_concept_groups: list[list[str]] = Field(default_factory=list)
    minimum_evidence_records: int = Field(default=1, ge=0)
    minimum_confidence: float = Field(default=0, ge=0, le=1)
    minimum_score: float = Field(default=0.8, ge=0, le=1)

    @model_validator(mode="after")
    def validate_concept_groups(self):
        groups = self.required_concept_groups + self.remediation_concept_groups
        if any(not group or any(not item.strip() for item in group) for group in groups):
            raise ValueError("concept groups must contain non-empty phrases")
        re.compile(self.component_pattern)
        return self


class EvaluationScenario(_StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    level: Literal["baseline", "correlation", "root_cause_chain", "adversarial"]
    injected_failure: str = Field(min_length=1)
    expected_alerts: list[str] = Field(min_length=1)
    expected_tools: list[str] = Field(default_factory=list)
    expectation: RCAExpectation


class CriterionResult(_StrictModel):
    name: str
    passed: bool
    detail: str


class EvaluationResult(_StrictModel):
    scenario_id: str
    score: float
    passed: bool
    criteria: list[CriterionResult]


def load_scenarios(path: str | Path) -> list[EvaluationScenario]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("evaluation scenario file must contain a YAML list")
    scenarios = [EvaluationScenario.model_validate(item) for item in raw]
    ids = [scenario.id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation scenario ids must be unique")
    return scenarios


def score_analysis(
    analysis: RootCauseAnalysis,
    scenario: EvaluationScenario,
) -> EvaluationResult:
    """Score an RCA using visible, deterministic pass/fail criteria."""
    expected = scenario.expectation
    all_text = " ".join([
        analysis.summary,
        analysis.root_cause,
        analysis.affected_component,
        *analysis.key_evidence,
        *analysis.remediation,
    ]).lower()
    remediation_text = " ".join(analysis.remediation).lower()
    criteria = []

    _criterion(
        criteria,
        "conclusion",
        analysis.conclusion is expected.conclusion,
        f"expected={expected.conclusion.value} actual={analysis.conclusion.value}",
    )
    _criterion(
        criteria,
        "component",
        bool(re.search(expected.component_pattern, analysis.affected_component, re.I)),
        f"component={analysis.affected_component!r}",
    )
    for index, group in enumerate(expected.required_concept_groups, 1):
        matched = next((phrase for phrase in group if phrase.lower() in all_text), None)
        _criterion(
            criteria,
            f"root_cause_concept_{index}",
            matched is not None,
            f"accepted={group!r} matched={matched!r}",
        )
    forbidden = [
        phrase for phrase in expected.forbidden_phrases
        if phrase.lower() in all_text
    ]
    _criterion(
        criteria,
        "forbidden_phrases",
        not forbidden,
        f"matched={forbidden!r}",
    )
    for index, group in enumerate(expected.remediation_concept_groups, 1):
        matched = next(
            (phrase for phrase in group if phrase.lower() in remediation_text),
            None,
        )
        _criterion(
            criteria,
            f"remediation_concept_{index}",
            matched is not None,
            f"accepted={group!r} matched={matched!r}",
        )
    cited = set(analysis.supporting_evidence_ids)
    cited_in_root = {
        token for token in re.findall(r"\bE[1-9][0-9]*\b", analysis.root_cause)
    }
    evidence_ok = (
        len(cited) >= expected.minimum_evidence_records
        and cited_in_root <= cited
        and (expected.minimum_evidence_records == 0 or bool(cited_in_root))
    )
    _criterion(
        criteria,
        "evidence",
        evidence_ok,
        f"declared={sorted(cited)!r} root_citations={sorted(cited_in_root)!r}",
    )
    _criterion(
        criteria,
        "confidence",
        analysis.confidence >= expected.minimum_confidence,
        f"minimum={expected.minimum_confidence:.2f} actual={analysis.confidence:.2f}",
    )

    score = sum(item.passed for item in criteria) / max(1, len(criteria))
    critical_names = {"conclusion", "forbidden_phrases", "evidence"}
    critical_ok = all(
        item.passed for item in criteria if item.name in critical_names
    )
    return EvaluationResult(
        scenario_id=scenario.id,
        score=round(score, 4),
        passed=critical_ok and score >= expected.minimum_score,
        criteria=criteria,
    )


def _criterion(criteria, name, passed, detail):
    criteria.append(CriterionResult(name=name, passed=bool(passed), detail=detail))


def evaluate_analysis_file(catalog_path, scenario_id, analysis_path):
    """Load one structured RCA and score it against a named scenario."""
    scenarios = {
        scenario.id: scenario for scenario in load_scenarios(catalog_path)
    }
    try:
        scenario = scenarios[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown evaluation scenario {scenario_id!r}") from exc
    raw = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
    analysis = RootCauseAnalysis.model_validate(raw)
    return score_analysis(analysis, scenario)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Score one structured RCA against the evaluation catalog."
    )
    parser.add_argument("--catalog", default="evaluation/scenarios.yaml")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--analysis", required=True)
    args = parser.parse_args(argv)

    result = evaluate_analysis_file(
        args.catalog,
        args.scenario,
        args.analysis,
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
