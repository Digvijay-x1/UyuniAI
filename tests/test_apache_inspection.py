from uyuni_ai_agent.apache_inspection import build_apache_overload_command


def test_apache_probe_is_bounded_aggregated_and_redacts_query_strings():
    command = build_apache_overload_command()

    assert command.startswith("timeout 15s bash -c ")
    assert "server-status?auto" in command
    assert "head -n 300" in command
    assert "RECENT ACCESS WINDOW AGGREGATE" in command
    assert "timedelta(minutes=10)" in command
    assert '.split("?", 1)[0]' in command
    assert "parsed_recent_records" in command
    assert "A low lifetime ReqPerSec cannot disprove a recent burst" in command
    assert "PROCESS SYSTEMD OWNERSHIP" in command
    assert "ProxyPass" in command
    assert "8 * 1024 * 1024" in command
