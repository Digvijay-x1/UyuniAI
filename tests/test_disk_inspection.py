import pytest

from uyuni_ai_agent.disk_inspection import (
    build_large_files_command,
    build_service_references_command,
    parse_service_unit_references,
    validate_absolute_path,
)


def test_service_reference_parser_extracts_and_deduplicates_units():
    output = """\
/etc/systemd/system/my-crashloop.service
/etc/systemd/system/multi-user.target.wants/my-crashloop.service
/etc/systemd/system/not-a-service.timer
"""
    assert parse_service_unit_references(output) == ["my-crashloop.service"]


def test_disk_commands_are_bounded_and_shell_quote_paths():
    command = build_large_files_command("/mnt/path with spaces", "10M", 500)
    references = build_service_references_command("/mnt/path with spaces")

    assert "'/mnt/path with spaces'" in command
    assert "head -n 50" in command
    assert "'/mnt/path with spaces'" in references


@pytest.mark.parametrize(
    "path",
    ["relative/path", "/tmp/x; reboot", "/tmp/x\nwhoami", ""],
)
def test_path_validation_rejects_unsafe_paths(path):
    if path.startswith("/") and ";" not in path and "\n" not in path:
        pytest.fail("test case is not unsafe")
    with pytest.raises(ValueError):
        validate_absolute_path(path)
