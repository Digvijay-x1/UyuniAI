"""Shared systemd unit-name validation."""

import re

_SYSTEMD_SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.service$")
_SYSTEMD_BARE_SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+$")


def validate_systemd_service(service: str) -> str:
    """Return a normalized, safe systemd service name.

    Investigation models sometimes return a service's common name (for
    example, ``apache2``) instead of its full systemd unit name. Accept that
    safe shorthand and normalize it to ``apache2.service`` while continuing
    to reject whitespace, paths, and shell metacharacters.
    """
    if not isinstance(service, str) or not _SYSTEMD_BARE_SERVICE_RE.fullmatch(
        service
    ):
        raise ValueError(f"Invalid systemd service name: {service!r}")

    normalized = service if service.endswith(".service") else f"{service}.service"
    if not _SYSTEMD_SERVICE_RE.fullmatch(normalized):
        raise ValueError(f"Invalid systemd service name: {service!r}")
    return normalized
