"""Safe command construction and parsing for disk RCA evidence."""

import posixpath
import re
import shlex


def validate_absolute_path(path: str) -> str:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or "\x00" in path
        or len(path) > 512
        or not re.fullmatch(r"/[A-Za-z0-9_./@:+ =,-]*", path)
        or ".." in path.split("/")
    ):
        raise ValueError("path must be a valid absolute path")
    return posixpath.normpath(path)


def build_large_files_command(path: str, min_size: str = "10M", limit: int = 20):
    path = validate_absolute_path(path)
    if not re.fullmatch(r"[1-9][0-9]*[KMGT]?", str(min_size).upper()):
        raise ValueError("min_size must look like 10M, 1G, or 500K")
    min_size = str(min_size).upper()
    limit = max(1, min(int(limit), 50))
    return (
        f"find {shlex.quote(path)} -xdev -type f "
        f"-size +{min_size} -printf '%s\\t%p\\n' 2>/dev/null "
        f"| sort -nr | head -n {limit} | numfmt --field=1 --to=iec"
    )


def build_service_references_command(path: str):
    path = validate_absolute_path(path)
    return (
        f"grep -RFl -- {shlex.quote(path)} "
        "/etc/systemd/system /usr/lib/systemd/system /lib/systemd/system "
        "2>/dev/null | head -20"
    )


def parse_service_unit_references(output):
    """Extract unique service unit names from grep output."""
    if not isinstance(output, str):
        return []
    units = []
    for line in output.splitlines():
        unit = posixpath.basename(line.strip())
        if unit.endswith(".service") and unit not in units:
            units.append(unit)
    return units
