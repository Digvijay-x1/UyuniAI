from pathlib import Path


def test_apache_prompt_requires_differential_evidence():
    prompt = (
        Path(__file__).parents[1] / "prompts" / "apache_overload.md"
    ).read_text(encoding="utf-8")

    assert "get_apache_overload_snapshot" in prompt
    assert "Traffic spike" in prompt
    assert "Slow internal backend" in prompt
    assert "not call it malicious or a DDoS without evidence" in prompt
    assert "many established Apache-to-backend connections" in prompt
    assert "workers are busy versus failing" in prompt
    assert "lifetime averages since Apache's RestartTime" in prompt
    assert "Never use a low lifetime average" in prompt
    assert "follow the dependency one layer further" in prompt
    assert "blocked queries and an identifiable blocker" in prompt
