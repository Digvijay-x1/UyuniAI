from pathlib import Path


def test_apache_and_postgres_prompts_require_one_causal_chain():
    root = Path(__file__).parents[1] / "prompts"
    apache = (root / "apache_overload.md").read_text(encoding="utf-8")
    postgres = (
        root / "postgres_blocked_transaction.md"
    ).read_text(encoding="utf-8")
    chain = (root / "postgres_apache_chain.md").read_text(encoding="utf-8")

    assert "PostgreSQL lock contention" in apache
    assert "Apache BusyWorkers as downstream effects" in apache
    assert "uncommitted PostgreSQL transaction -> blocked application" in (
        postgres
    )
    assert "Do not report independent" in postgres
    assert "most recently observed statement" in postgres
    assert "attribute retained locks to the open transaction" in apache
    assert "Apache/application minion" in chain
    assert "PostgreSQL minion" in chain
