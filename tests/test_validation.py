import pytest

from uyuni_ai_agent.validation import (
    bounded_int,
    build_ping_command,
    build_process_list_command,
    validate_configured_minion,
    validate_network_target,
)


@pytest.mark.parametrize(
    "target",
    ["localhost", "client.example.com", "192.0.2.10", "2001:db8::10"],
)
def test_network_targets_accept_only_hostnames_and_ip_addresses(target):
    assert validate_network_target(target) == target


@pytest.mark.parametrize(
    "target",
    [
        "client.example; id",
        "$(id)",
        "-c 100 attacker.example",
        "client_name.example",
        "",
    ],
)
def test_network_targets_reject_shell_syntax(target):
    with pytest.raises(ValueError, match="hostname or IP address"):
        validate_network_target(target)


def test_ping_command_uses_an_option_separator_and_bounded_count():
    assert build_ping_command("client.example", 3) == (
        "ping -c 3 -- client.example"
    )
    with pytest.raises(ValueError, match="between 1 and 5"):
        build_ping_command("client.example", 100)


def test_process_listing_is_bounded_and_has_a_fixed_sort_field():
    assert build_process_list_command("%mem", 10).endswith("head -n 11")
    with pytest.raises(ValueError, match="between 1 and 50"):
        build_process_list_command("%cpu", 1000)
    with pytest.raises(ValueError, match="unsupported"):
        build_process_list_command("command;id", 10)


def test_bounded_int_rejects_booleans_and_fractional_values():
    with pytest.raises(ValueError, match="must be an integer"):
        bounded_int(True, name="lines", minimum=1, maximum=200)
    with pytest.raises(ValueError, match="must be an integer"):
        bounded_int(1.5, name="lines", minimum=1, maximum=200)


def test_minion_validation_requires_an_exact_configured_target():
    allowed = {"client", "client2"}

    assert validate_configured_minion("client", allowed) == "client"
    for target in ("*", "client*", "missing"):
        with pytest.raises(ValueError, match="not configured"):
            validate_configured_minion(target, allowed)
