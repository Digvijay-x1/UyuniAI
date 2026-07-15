"""Bounded Apache overload evidence collection."""

from __future__ import annotations

import shlex


def build_apache_overload_command() -> str:
    """Return a fixed command that distinguishes load from slow dependencies."""
    script = r"""
set -u

echo '=== APACHE STATUS AUTO ==='
curl --fail --silent --show-error --max-time 5 \
    'http://127.0.0.1/server-status?auto' 2>&1 |
    sed -n '1,100p'

echo '=== METRIC SEMANTICS ==='
echo 'Prometheus apache request rate is a recent 5-minute counter rate.'
echo 'mod_status ReqPerSec and DurationPerReq are lifetime averages since RestartTime.'
echo 'A low lifetime ReqPerSec cannot disprove a recent burst.'
echo 'Completed bursts may leave no currently established client connections.'

echo '=== RECENT ACCESS WINDOW AGGREGATE (QUERY STRINGS REMOVED) ==='
python3 - <<'PYTHON'
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
pattern = re.compile(
    rb'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) ([^ ]+) [^"]*" '
    rb'(\d{3}) '
)
counts = Counter()
parsed = 0
files = sorted(
    Path("/var/log/apache2").glob("*access*.log"),
    key=lambda path: path.stat().st_mtime,
    reverse=True,
)[:10]
for path in files:
    size = path.stat().st_size
    read_size = min(size, 8 * 1024 * 1024)
    with path.open("rb") as stream:
        if size > read_size:
            stream.seek(-read_size, 2)
            stream.readline()
        data = stream.read()
    recent_in_tail = 0
    for line in data.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        try:
            timestamp = datetime.strptime(
                match.group(2).decode("ascii"),
                "%d/%b/%Y:%H:%M:%S %z",
            )
        except (UnicodeDecodeError, ValueError):
            continue
        if timestamp < cutoff:
            continue
        client = match.group(1).decode("utf-8", "replace")
        method = match.group(3).decode("utf-8", "replace")
        path_only = (
            match.group(4).decode("utf-8", "replace").split("?", 1)[0]
        )
        status = match.group(5).decode("ascii")
        counts[(client, method, path_only, status)] += 1
        parsed += 1
        recent_in_tail += 1
    print(
        f"file={path} size_bytes={size} bytes_read={len(data)} "
        f"recent_records_in_tail={recent_in_tail} "
        f"tail_truncated={str(size > read_size).lower()}"
    )
print(f"window_seconds=600 parsed_recent_records={parsed}")
for (client, method, path, status), count in counts.most_common(25):
    print(
        f"count={count} client={client} method={method} "
        f"path={path} status={status}"
    )
PYTHON

echo '=== APACHE/BACKEND ESTABLISHED TCP CONNECTIONS ==='
ss -Htnp state established 2>/dev/null |
    grep -E 'apache2|httpd|python3|psql|postgres|php|gunicorn|:80 |:443 ' |
    head -n 300 || true

echo '=== APACHE/BACKEND LISTENERS ==='
ss -Hltnp 2>/dev/null |
    grep -E 'apache2|httpd|python3|php|gunicorn|:80 |:443 ' |
    head -n 120 || true

echo '=== APACHE AND LIKELY BACKEND PROCESSES ==='
ps -eo pid,ppid,comm,%cpu,%mem,rss,etimes --sort=-rss |
    awk 'NR == 1 || $3 ~ /^(apache2|httpd|python3|php|php-fpm|curl|ab)$/ {
        print
    }' |
    head -n 80

echo '=== PROCESS SYSTEMD OWNERSHIP ==='
for pid in $(pgrep -x apache2; pgrep -x httpd; pgrep -x python3; \
    pgrep -x php-fpm; pgrep -x curl; pgrep -x ab) 2>/dev/null; do
    unit=$(
        sed -nE \
            's#^[^:]*:[^:]*:.*/([^/]+\.(service|scope))(/.*)?$#\1#p' \
            "/proc/${pid}/cgroup" 2>/dev/null |
            head -n 1
    )
    printf 'pid=%s comm=' "${pid}"
    cat "/proc/${pid}/comm" 2>/dev/null || printf 'unknown\n'
    printf ' unit=%s\n' "${unit:-none}"
done

echo '=== APACHE CONFIGURATION SUMMARY ==='
apachectl -t 2>&1
apachectl -M 2>&1 |
    grep -E 'mpm_|status_module|proxy|cgi|php' || true
grep -RhsE \
    '^[[:space:]]*(Listen|ProxyPass|ProxyPassReverse|ScriptAlias|SetHandler|MaxRequestWorkers|ServerLimit)' \
    /etc/apache2/apache2.conf /etc/apache2/conf-enabled \
    /etc/apache2/mods-enabled /etc/apache2/sites-enabled 2>/dev/null |
    sed -E 's#(https?://)[^/@[:space:]]+@#\1REDACTED@#g' |
    head -n 120

echo '=== RECENT APACHE ERRORS ==='
find /var/log/apache2 -maxdepth 1 -type f -name '*error*.log' \
    -mmin -10 -print0 2>/dev/null |
    xargs -0 -r tail -q -n 80 2>/dev/null |
    tail -n 120
""".strip()
    return f"timeout 15s bash -c {shlex.quote(script)}"
