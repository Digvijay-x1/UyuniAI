from pathlib import Path

from uyuni_ai_agent.evaluation import (
    evaluate_analysis_file,
    load_scenarios,
    score_analysis,
)
from uyuni_ai_agent.models import (
    AnalysisConclusion,
    RootCauseAnalysis,
    Urgency,
)

SCENARIOS = Path(__file__).parents[1] / "evaluation" / "scenarios.yaml"


def analysis(**overrides):
    values = {
        "summary": "PostgreSQL lock blocks web requests",
        "conclusion": AnalysisConclusion.CONFIRMED,
        "affected_component": "postgresql",
        "root_cause": (
            "PostgreSQL is accepting queries [E1], but an idle in transaction "
            "session holds a lock that leaves another query blocked [E2]."
        ),
        "supporting_evidence_ids": ["E1", "E2"],
        "key_evidence": [
            "[E1] PostgreSQL is available",
            "[E2] session 22 is blocked by session 11",
        ],
        "remediation": [
            "Fix the application transaction path to commit or roll back."
        ],
        "urgency": Urgency.CRITICAL,
        "confidence": 0.95,
    }
    values.update(overrides)
    return RootCauseAnalysis(**values)


def test_scenario_catalog_is_unique_and_covers_all_evaluation_levels():
    scenarios = load_scenarios(SCENARIOS)

    assert len(scenarios) >= 9
    assert len({scenario.id for scenario in scenarios}) == len(scenarios)
    assert {scenario.level for scenario in scenarios} == {
        "baseline",
        "correlation",
        "root_cause_chain",
        "adversarial",
    }
    assert all(scenario.expected_alerts for scenario in scenarios)


def test_evidence_based_postgres_rca_passes_its_golden_scenario():
    scenario = next(
        item for item in load_scenarios(SCENARIOS)
        if item.id == "postgres_blocked_transaction"
    )

    result = score_analysis(analysis(), scenario)

    assert result.passed is True
    assert result.score == 1
    assert all(item.passed for item in result.criteria)


def test_generic_symptom_report_fails_causal_and_evidence_criteria():
    scenario = next(
        item for item in load_scenarios(SCENARIOS)
        if item.id == "disk_crash_loop"
    )
    generic = analysis(
        summary="Disk full",
        affected_component="/mnt/data",
        root_cause="The partition is simply full.",
        supporting_evidence_ids=[],
        key_evidence=[],
        remediation=["Delete files"],
        confidence=0.4,
    )

    result = score_analysis(generic, scenario)

    assert result.passed is False
    failed = {item.name for item in result.criteria if not item.passed}
    assert "evidence" in failed
    assert "forbidden_phrases" in failed
    assert any(name.startswith("root_cause_concept_") for name in failed)


def test_blind_restart_recommendation_fails_postgres_scenario():
    scenario = next(
        item for item in load_scenarios(SCENARIOS)
        if item.id == "postgres_blocked_transaction"
    )
    unsafe = analysis(remediation=["Restart PostgreSQL immediately"])

    result = score_analysis(unsafe, scenario)

    assert result.passed is False
    forbidden = next(
        item for item in result.criteria if item.name == "forbidden_phrases"
    )
    assert forbidden.passed is False


def test_structured_analysis_file_can_be_scored(tmp_path):
    path = tmp_path / "analysis.json"
    path.write_text(analysis().model_dump_json(), encoding="utf-8")

    result = evaluate_analysis_file(
        SCENARIOS,
        "postgres_blocked_transaction",
        path,
    )

    assert result.passed is True
