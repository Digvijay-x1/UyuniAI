from uyuni_ai_agent.react_agent import append_required_evidence


def test_required_evidence_is_appended_once_in_a_consistent_section():
    prompt = append_required_evidence("Investigate this anomaly.", "fact=42")

    assert prompt.count("## Pre-collected mandatory evidence") == 1
    assert "fact=42" in prompt
    assert prompt.endswith(
        "Use this evidence in the RCA. You may call tools for clarification."
    )


def test_empty_required_evidence_does_not_modify_the_prompt():
    assert append_required_evidence("original", "") == "original"
