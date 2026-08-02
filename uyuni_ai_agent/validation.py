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

"""Validation helpers for values that can reach diagnostic commands."""

from __future__ import annotations

import ipaddress
import re
import shlex
from collections.abc import Collection

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def bounded_int(value, *, name: str, minimum: int, maximum: int) -> int:
    """Return an integer inside an inclusive range or raise ``ValueError``."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def validate_network_target(target: str) -> str:
    """Allow only an IP address or RFC-style DNS hostname as a ping target."""
    if not isinstance(target, str):
        raise ValueError("target must be a hostname or IP address")
    target = target.strip().rstrip(".")
    if not target or len(target) > 253:
        raise ValueError("target must be a hostname or IP address")

    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass

    labels = target.split(".")
    if not all(_HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("target must be a hostname or IP address")
    return target


def build_ping_command(target: str, count: int = 3) -> str:
    """Build a bounded ping command from a validated network target."""
    target = validate_network_target(target)
    count = bounded_int(count, name="count", minimum=1, maximum=5)
    return f"ping -c {count} -- {shlex.quote(target)}"


def build_process_list_command(sort_field: str, top_n: int = 10) -> str:
    """Build a bounded process listing for one of the approved sort fields."""
    if sort_field not in {"%cpu", "%mem"}:
        raise ValueError("unsupported process sort field")
    top_n = bounded_int(top_n, name="top_n", minimum=1, maximum=50)
    return f"ps aux --sort=-{sort_field} | head -n {top_n + 1}"


def validate_configured_minion(
    minion_id: str,
    allowed_minions: Collection[str],
) -> str:
    """Require an exact configured minion ID; Salt glob targets are rejected."""
    if not isinstance(minion_id, str) or minion_id not in allowed_minions:
        raise ValueError(f"minion {minion_id!r} is not configured for this agent")
    return minion_id
