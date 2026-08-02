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

"""Conservative deterministic RCAs for evidence patterns that prove a cause."""

from __future__ import annotations

import re

from uyuni_ai_agent.evidence import EvidenceLedger, EvidenceStatus
from uyuni_ai_agent.models import (
    AnalysisConclusion,
    RootCauseAnalysis,
    Urgency,
)


def try_deterministic_analysis(anomaly, ledger: EvidenceLedger):
    """Return an RCA only for strict, directly testable evidence patterns."""
    analyzers = {
        "service_down": _service_port_conflict,
        "disk": _disk_crash_loop,
        "postgres_blocked_transaction": _postgres_blocked_transaction,
        "memory_pressure": _memory_pressure,
        "memory": _memory_pressure,
    }
    analyzer = analyzers.get(anomaly.metric_name)
    return analyzer(anomaly, ledger) if analyzer is not None else None


def _records(ledger, prefix):
    return [
        record
        for record in ledger.records
        if record.check.startswith(prefix) and record.status is EvidenceStatus.OK
    ]


def _urgency(anomaly):
    severity = str(getattr(anomaly.severity, "value", anomaly.severity)).lower()
    return Urgency.CRITICAL if severity == "critical" else Urgency.HIGH


def _service_port_conflict(anomaly, ledger):
    details = next(iter(_records(ledger, "service_details:")), None)
    logs = next(iter(_records(ledger, "service_logs:")), None)
    listeners = next(iter(_records(ledger, "listening_tcp_ports")), None)
    if not details or not logs or not listeners:
        return None
    if not re.search(r"address already in use|eaddrinuse", logs.details, re.I):
        return None
    port_match = re.search(
        r"(?:http\.server\s+|--port(?:=|\s+)|port(?:=|\s+))(\d{2,5})",
        details.details,
        re.I,
    )
    if port_match is None:
        return None
    port = int(port_match.group(1))
    if not 1 <= port <= 65535:
        return None
    listener_line = next(
        (
            line.strip()
            for line in listeners.details.splitlines()
            if re.search(rf":{port}\b", line)
        ),
        None,
    )
    if listener_line is None:
        return None
    process_match = re.search(r'users:\(\("([^"]+)"', listener_line)
    process = process_match.group(1) if process_match else "another process"
    service = anomaly.service_name or "the configured service"
    return RootCauseAnalysis(
        summary=f"{service} cannot bind TCP port {port}",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component=service,
        root_cause=(
            f"{service} fails with an address-in-use error [{logs.id}] while "
            f"{process} is already listening on TCP port {port} "
            f"[{listeners.id}]."
        ),
        supporting_evidence_ids=[details.id, logs.id, listeners.id],
        key_evidence=[
            f"[{details.id}] The service is configured to use TCP port {port}.",
            f"[{logs.id}] The service reports that its address is already in use.",
            f"[{listeners.id}] {process} owns a listener on TCP port {port}.",
        ],
        remediation=[
            f"Confirm whether {process} or {service} should own TCP port {port}.",
            "Stop or reconfigure only the unintended listener, then start the affected service.",
        ],
        urgency=_urgency(anomaly),
        confidence=0.99,
    )


def _disk_crash_loop(anomaly, ledger):
    usage = next(iter(_records(ledger, "disk_usage")), None)
    largest = next(iter(_records(ledger, "largest_files")), None)
    if not usage or not largest:
        return None
    first_file = next(
        (line.strip() for line in largest.details.splitlines() if line.strip()),
        "",
    )
    path_match = re.search(r"(/[^\t ]+)$", first_file)
    if path_match is None:
        return None
    large_path = path_match.group(1)
    for details in _records(ledger, "service_details:"):
        restart_match = re.search(r"(?m)^NRestarts=(\d+)$", details.details)
        restart_policy = re.search(
            r"(?m)^Restart=(on-failure|always|on-abnormal|on-watchdog)$",
            details.details,
        )
        if (
            restart_match is None
            or int(restart_match.group(1)) < 2
            or restart_policy is None
            or large_path not in details.details
        ):
            continue
        service = details.check.split(":", 1)[1]
        log_record = next(
            iter(_records(ledger, f"service_logs:{service}")), None
        )
        evidence_ids = [usage.id, largest.id, details.id]
        key_evidence = [
            f"[{usage.id}] The affected filesystem is at or above its alert threshold.",
            f"[{largest.id}] {large_path} is the largest discovered file.",
            f"[{details.id}] {service} references that file and has restarted {restart_match.group(1)} times.",
        ]
        if log_record is not None:
            evidence_ids.append(log_record.id)
        return RootCauseAnalysis(
            summary=f"{service} crash loop filled the filesystem",
            conclusion=AnalysisConclusion.CONFIRMED,
            affected_component=service,
            root_cause=(
                f"{service} repeatedly restarts and writes {large_path} "
                f"[{details.id}], which became the largest file on the full "
                f"filesystem [{largest.id}]."
            ),
            supporting_evidence_ids=evidence_ids,
            key_evidence=key_evidence,
            remediation=[
                f"Stop {service} to halt further growth while preserving evidence.",
                f"Fix the failing execution path and configure bounded rotation for {large_path}.",
                "Reclaim space only after retaining any logs required for diagnosis.",
            ],
            urgency=_urgency(anomaly),
            confidence=0.98,
        )
    return None


def _postgres_blocked_transaction(anomaly, ledger):
    health = next(iter(_records(ledger, "postgres_health")), None)
    locks = next(iter(_records(ledger, "postgres_blocking_activity")), None)
    blocked = anomaly.context.get("blocked_pids", [])
    blockers = anomaly.context.get("blocker_pids", [])
    database = anomaly.context.get("database", "unknown")
    if not health or not locks or not blocked or not blockers:
        return None
    health_text = health.details.lower()
    lock_text = locks.details.lower()
    if (
        not re.search(r'"available"\s*:\s*true|available\s*[=:]\s*true', health_text)
        or "idle in transaction" not in lock_text
        or not any(str(pid) in locks.details for pid in blockers)
    ):
        return None
    blocker_text = ", ".join(str(pid) for pid in blockers[:5])
    blocked_text = ", ".join(str(pid) for pid in blocked[:5])
    return RootCauseAnalysis(
        summary=f"PostgreSQL work in {database} is blocked by an open transaction",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component="postgresql",
        root_cause=(
            f"PostgreSQL is accepting queries [{health.id}], but idle-in-transaction "
            f"session(s) {blocker_text} hold locks needed by session(s) "
            f"{blocked_text} [{locks.id}]."
        ),
        supporting_evidence_ids=[health.id, locks.id],
        key_evidence=[
            f"[{health.id}] PostgreSQL is available and accepting SQL.",
            f"[{locks.id}] Blocked session(s) {blocked_text} wait on blocker(s) {blocker_text}.",
        ],
        remediation=[
            "Identify the application path that left the transaction open and make it commit or roll back.",
            "After assessing impact, terminate only the offending backend if graceful closure is impossible.",
            "Configure idle_in_transaction_session_timeout as a safety bound.",
        ],
        urgency=_urgency(anomaly),
        confidence=0.99,
    )


def _memory_pressure(anomaly, ledger):
    if not anomaly.context.get("active_swapping"):
        return None
    snapshot = next(iter(_records(ledger, "memory_pressure_snapshot")), None)
    detector = next(iter(_records(ledger, anomaly.metric_name)), None)
    if not snapshot or not detector:
        return None
    section_match = re.search(
        r"=== TOP_RSS_KIB ===\s*\n([^=]+)", snapshot.details, re.S
    )
    if section_match is None:
        return None
    lines = [
        line.strip() for line in section_match.group(1).splitlines()
        if line.strip()
    ]
    if len(lines) < 2:
        return None
    header = lines[0].split()
    values = lines[1].split()
    try:
        process = values[header.index("COMMAND")]
        rss_kib = int(values[header.index("RSS")])
    except (ValueError, IndexError):
        return None
    return RootCauseAnalysis(
        summary="Memory pressure is causing active swapping",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component=process,
        root_cause=(
            f"The host is under memory pressure with active swap I/O "
            f"[{detector.id}], and {process} is the largest RSS consumer at "
            f"{rss_kib} KiB [{snapshot.id}]."
        ),
        supporting_evidence_ids=[detector.id, snapshot.id],
        key_evidence=[
            f"[{detector.id}] Memory usage crossed the threshold with current swap activity.",
            f"[{snapshot.id}] {process} has the largest resident set ({rss_kib} KiB).",
        ],
        remediation=[
            f"Inspect why {process} is retaining memory and apply a bounded application-level limit.",
            "Reduce load or restart only the affected workload after assessing user impact.",
            "Keep swap activity and memory pressure stalls under observation during recovery.",
        ],
        urgency=_urgency(anomaly),
        confidence=0.95,
    )
