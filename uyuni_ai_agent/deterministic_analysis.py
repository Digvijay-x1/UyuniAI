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
from dataclasses import dataclass

from uyuni_ai_agent.evidence import EvidenceLedger, EvidenceStatus
from uyuni_ai_agent.models import (
    AnalysisConclusion,
    RootCauseAnalysis,
    Urgency,
)


@dataclass(frozen=True)
class DeterministicAnalysisResult:
    """A proven RCA plus its controlled, non-customer-specific analyzer ID."""

    analysis: RootCauseAnalysis
    analyzer: str


def try_deterministic_analysis_with_metadata(
    anomaly, ledger: EvidenceLedger
) -> DeterministicAnalysisResult | None:
    """Return a proven RCA and safe analyzer metadata, or ``None``."""
    if anomaly.metric_name == "service_down":
        analyzers = (
            ("ssh_host_key_mismatch", _ssh_host_key_mismatch),
            ("tls_identity_mismatch", _tls_identity_mismatch),
            ("nfs_identity_drift", _nfs_identity_drift),
            ("service_port_conflict", _service_port_conflict),
        )
    else:
        configured = {
            "disk": ("disk_crash_loop", _disk_crash_loop),
            "postgres_blocked_transaction": (
                "postgres_blocked_transaction",
                _postgres_blocked_transaction,
            ),
            "memory_pressure": ("memory_pressure", _memory_pressure),
            "memory": ("memory_pressure", _memory_pressure),
        }.get(anomaly.metric_name)
        analyzers = (configured,) if configured is not None else ()

    for analyzer_name, analyzer in analyzers:
        analysis = analyzer(anomaly, ledger)
        if analysis is not None:
            return DeterministicAnalysisResult(analysis, analyzer_name)
    return None


def try_deterministic_analysis(anomaly, ledger: EvidenceLedger):
    """Return only the RCA for backward-compatible callers and tests."""
    result = try_deterministic_analysis_with_metadata(anomaly, ledger)
    return result.analysis if result is not None else None


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


def _dependency_record(ledger, kind):
    return next(iter(_records(ledger, f"dependency_inspection:{kind}:")), None)


def _service_log_record(ledger):
    return next(iter(_records(ledger, "service_logs:")), None)


def _ssh_host_key_mismatch(anomaly, ledger):
    logs = _service_log_record(ledger)
    snapshot = _dependency_record(ledger, "ssh")
    if not logs or not snapshot or not re.search(
        r"remote host identification has changed|host key verification failed",
        logs.details,
        re.I,
    ):
        return None
    source_text, separator, target_text = snapshot.details.partition(
        "--- TARGET ---"
    )
    if not separator:
        return None
    pinned = set(re.findall(r"SHA256:[A-Za-z0-9+/=]+", source_text))
    presented = set(re.findall(r"SHA256:[A-Za-z0-9+/=]+", target_text))
    if not pinned or not presented or pinned & presented:
        return None
    pinned_label = ", ".join(sorted(pinned))
    presented_label = ", ".join(sorted(presented))
    service = anomaly.service_name or "SSH client job"
    return RootCauseAnalysis(
        summary=f"{service} rejected a changed SSH host key",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component="SSH host-key trust",
        root_cause=(
            f"{service} rejected the remote endpoint because its pinned host "
            f"key set {pinned_label} differs from the currently presented key "
            f"set {presented_label} [{snapshot.id}], producing strict host-key "
            f"verification failure [{logs.id}]."
        ),
        supporting_evidence_ids=[logs.id, snapshot.id],
        key_evidence=[
            f"[{logs.id}] The client reports a changed host identity and refuses the connection.",
            f"[{snapshot.id}] Pinned fingerprint set {pinned_label} differs from presented fingerprint set {presented_label}.",
        ],
        remediation=[
            "Verify the new presented fingerprint through a trusted out-of-band channel or the server console before changing trust.",
            "If the rotation is authorized, replace only this configured host-and-port entry with the verified fingerprint; preserve the previous entry for rollback.",
            "Run the job again with strict host-key checking still enabled.",
        ],
        urgency=_urgency(anomaly),
        confidence=0.99,
    )


def _tls_identity_mismatch(anomaly, ledger):
    logs = _service_log_record(ledger)
    snapshot = _dependency_record(ledger, "tls")
    if not logs or not snapshot:
        return None
    combined = f"{logs.details}\n{snapshot.details}"
    if not re.search(
        r"no alternative certificate subject name matches|hostname mismatch|verify error:num=62",
        combined,
        re.I,
    ):
        return None
    san_match = re.search(
        r"Subject Alternative Name:\s*\n?\s*DNS:([^,\s]+)",
        snapshot.details,
        re.I,
    )
    expected_match = re.search(
        r"Verification error: hostname mismatch|verify error:num=62",
        snapshot.details,
        re.I,
    )
    if san_match is None or expected_match is None:
        return None
    service = anomaly.service_name or "TLS client job"
    wrong_name = san_match.group(1)
    return RootCauseAnalysis(
        summary=f"{service} rejected the server certificate identity",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component="TLS certificate identity",
        root_cause=(
            f"The configured endpoint presents a trusted certificate whose "
            f"SAN is {wrong_name}, which does not match the requested hostname "
            f"[{snapshot.id}]; the client therefore rejects the connection "
            f"during hostname verification [{logs.id}]."
        ),
        supporting_evidence_ids=[logs.id, snapshot.id],
        key_evidence=[
            f"[{logs.id}] The client fails certificate hostname verification.",
            f"[{snapshot.id}] The live certificate SAN is {wrong_name} and OpenSSL reports hostname mismatch.",
        ],
        remediation=[
            "Confirm the intended service hostname and certificate issuance record.",
            "Install a certificate whose SAN contains the intended hostname, or correct the endpoint only if configuration is wrong; retain the current certificate for rollback.",
            "Re-run chain and hostname verification without disabling TLS verification before restarting the job.",
        ],
        urgency=_urgency(anomaly),
        confidence=0.99,
    )


def _nfs_identity_drift(anomaly, ledger):
    logs = _service_log_record(ledger)
    snapshot = _dependency_record(ledger, "nfs")
    if not logs or not snapshot or not re.search(
        r"permission denied", logs.details, re.I
    ):
        return None
    expected = re.search(
        r"expected_uid=(\d+) expected_gid=(\d+)", snapshot.details
    )
    client = re.search(
        r"mount=.*? uid=(\d+) gid=(\d+) mode=(\d+)", snapshot.details
    )
    server = re.search(
        r"export=.*? uid=(\d+) gid=(\d+) mode=(\d+)", snapshot.details
    )
    if not expected or not client or not server:
        return None
    expected_ids = expected.group(1, 2)
    client_ids = client.group(1, 2)
    server_ids = server.group(1, 2)
    if client_ids != server_ids or server_ids == expected_ids:
        return None
    service = anomaly.service_name or "NFS client job"
    actual = f"{server_ids[0]}:{server_ids[1]}"
    intended = f"{expected_ids[0]}:{expected_ids[1]}"
    return RootCauseAnalysis(
        summary=f"{service} is blocked by NFS numeric identity drift",
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component="NFS export ownership mapping",
        root_cause=(
            f"The mounted export and server directory both resolve to numeric "
            f"owner {actual}, but the configured backup identity is {intended} "
            f"[{snapshot.id}]. The client job consequently receives Permission "
            f"denied while writing [{logs.id}]."
        ),
        supporting_evidence_ids=[logs.id, snapshot.id],
        key_evidence=[
            f"[{logs.id}] The backup process receives Permission denied on the mounted path.",
            f"[{snapshot.id}] Client mount and server export show owner {actual}, not intended backup UID/GID {intended}.",
        ],
        remediation=[
            "Confirm the intended numeric backup UID/GID and review the export identity-mapping policy on both nodes.",
            f"Restore the export ownership mapping to {intended} only after validating that identity; record current owner {actual} for rollback.",
            "Re-test a write as the backup service account without weakening export policy or applying world-writable permissions.",
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
