"""Durable incident lifecycle and notification state.

The polling loop must not forget active incidents when its process restarts.
SQLite keeps the lifecycle local to the agent while avoiding another service
or a change to the monitoring topology.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterable

from uyuni_ai_agent.anomaly_detector import Anomaly


_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def _rfc3339(timestamp: float) -> str:
    return (
        datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def incident_fingerprint(anomaly: Anomaly) -> str:
    """Return a deterministic, restart-safe identity for an anomaly."""
    encoded = json.dumps(
        list(anomaly.identity_key()),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


@dataclass(frozen=True)
class IncidentRecord:
    fingerprint: str
    minion_id: str
    metric_name: str
    service_name: str
    resource: str
    severity: str
    starts_at: str
    first_seen: float
    last_seen: float
    last_emitted: float | None
    consecutive_absent: int
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class FiringIncident:
    anomaly: Anomaly
    fingerprint: str
    starts_at: str
    previous_payload: dict[str, Any] | None


@dataclass(frozen=True)
class IncidentChanges:
    firing: list[FiringIncident]
    resolved: list[IncidentRecord]


class IncidentStore:
    """Reconcile detected anomalies with durable incident state.

    Notification state is only advanced by :meth:`mark_emitted` after an
    investigation and Alertmanager delivery succeed. A transient LLM or HTTP
    failure is therefore retried on the next polling cycle instead of being
    hidden for the full cooldown.
    """

    def __init__(
        self,
        path: str,
        *,
        cooldown_seconds: int = 900,
        resolve_after_healthy_cycles: int = 2,
    ):
        self.path = path
        self.cooldown_seconds = max(0, int(cooldown_seconds))
        self.resolve_after_healthy_cycles = max(
            1, int(resolve_after_healthy_cycles)
        )
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._connection = sqlite3.connect(path, timeout=5)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._configure()
        self._create_schema()

    def _configure(self) -> None:
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                fingerprint TEXT PRIMARY KEY,
                minion_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                service_name TEXT NOT NULL,
                resource TEXT NOT NULL,
                severity TEXT NOT NULL,
                last_emitted_severity TEXT,
                status TEXT NOT NULL CHECK (status IN ('active', 'resolved')),
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                last_emitted REAL,
                consecutive_absent INTEGER NOT NULL DEFAULT 0,
                starts_at TEXT NOT NULL,
                payload_json TEXT,
                resolved_at REAL
            );
            CREATE INDEX IF NOT EXISTS incidents_minion_status
                ON incidents (minion_id, status);
            """
        )
        self._connection.commit()

    @staticmethod
    def _severity(anomaly: Anomaly) -> str:
        return str(getattr(anomaly.severity, "value", anomaly.severity)).lower()

    @staticmethod
    def _decode_payload(raw_payload: str | None) -> dict[str, Any] | None:
        if not raw_payload:
            return None
        payload = json.loads(raw_payload)
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _record(cls, row: sqlite3.Row, *, absent: int | None = None):
        return IncidentRecord(
            fingerprint=row["fingerprint"],
            minion_id=row["minion_id"],
            metric_name=row["metric_name"],
            service_name=row["service_name"],
            resource=row["resource"],
            severity=row["severity"],
            starts_at=row["starts_at"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            last_emitted=row["last_emitted"],
            consecutive_absent=(
                row["consecutive_absent"] if absent is None else absent
            ),
            payload=cls._decode_payload(row["payload_json"]),
        )

    @staticmethod
    def _prefer_more_severe(anomalies: Iterable[Anomaly]) -> dict[str, Anomaly]:
        selected: dict[str, Anomaly] = {}
        for anomaly in anomalies:
            fingerprint = incident_fingerprint(anomaly)
            existing = selected.get(fingerprint)
            current = _SEVERITY_RANK.get(
                IncidentStore._severity(anomaly), -1
            )
            previous = (
                _SEVERITY_RANK.get(IncidentStore._severity(existing), -1)
                if existing is not None
                else -1
            )
            if existing is None or current > previous:
                selected[fingerprint] = anomaly
        return selected

    def reconcile(
        self,
        minion_id: str,
        anomalies: Iterable[Anomaly],
        *,
        now: float | None = None,
    ) -> IncidentChanges:
        """Return notification work without claiming it was delivered."""
        observed_at = time.time() if now is None else float(now)
        current = self._prefer_more_severe(anomalies)
        firing: list[FiringIncident] = []
        resolved: list[IncidentRecord] = []

        with self._lock, self._connection:
            active_rows = self._connection.execute(
                "SELECT * FROM incidents WHERE minion_id = ? AND status = 'active'",
                (minion_id,),
            ).fetchall()
            active = {row["fingerprint"]: row for row in active_rows}

            for fingerprint, anomaly in current.items():
                severity = self._severity(anomaly)
                row = active.get(fingerprint)
                if row is None:
                    starts_at = _rfc3339(observed_at)
                    self._connection.execute(
                        """
                        INSERT INTO incidents (
                            fingerprint, minion_id, metric_name, service_name,
                            resource, severity, last_emitted_severity, status,
                            first_seen, last_seen, last_emitted,
                            consecutive_absent, starts_at, payload_json,
                            resolved_at
                        ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?, NULL,
                                  0, ?, NULL, NULL)
                        ON CONFLICT(fingerprint) DO UPDATE SET
                            severity = excluded.severity,
                            last_emitted_severity = NULL,
                            status = 'active',
                            first_seen = excluded.first_seen,
                            last_seen = excluded.last_seen,
                            last_emitted = NULL,
                            consecutive_absent = 0,
                            starts_at = excluded.starts_at,
                            payload_json = NULL,
                            resolved_at = NULL
                        """,
                        (
                            fingerprint,
                            minion_id,
                            anomaly.metric_name,
                            anomaly.service_name or "",
                            anomaly.resource or "",
                            severity,
                            observed_at,
                            observed_at,
                            starts_at,
                        ),
                    )
                    firing.append(
                        FiringIncident(anomaly, fingerprint, starts_at, None)
                    )
                    continue

                emitted_severity = row["last_emitted_severity"]
                escalated = _SEVERITY_RANK.get(severity, -1) > _SEVERITY_RANK.get(
                    emitted_severity or "", -1
                )
                last_emitted = row["last_emitted"]
                cooldown_elapsed = (
                    last_emitted is None
                    or observed_at - last_emitted >= self.cooldown_seconds
                )
                self._connection.execute(
                    """
                    UPDATE incidents
                    SET severity = ?, last_seen = ?, consecutive_absent = 0
                    WHERE fingerprint = ?
                    """,
                    (severity, observed_at, fingerprint),
                )
                if escalated or cooldown_elapsed:
                    firing.append(
                        FiringIncident(
                            anomaly,
                            fingerprint,
                            row["starts_at"],
                            self._decode_payload(row["payload_json"]),
                        )
                    )

            for fingerprint, row in active.items():
                if fingerprint in current:
                    continue
                absent = row["consecutive_absent"] + 1
                self._connection.execute(
                    """
                    UPDATE incidents SET consecutive_absent = ?
                    WHERE fingerprint = ?
                    """,
                    (absent, fingerprint),
                )
                if absent >= self.resolve_after_healthy_cycles:
                    resolved.append(self._record(row, absent=absent))

        return IncidentChanges(firing=firing, resolved=resolved)

    def mark_emitted(
        self,
        fingerprint: str,
        payload: dict[str, Any],
        *,
        now: float | None = None,
        starts_at: str | None = None,
    ) -> None:
        emitted_at = time.time() if now is None else float(now)
        delivered_severity = str(
            (payload.get("labels") or {}).get("severity", "")
        ).lower()
        encoded_payload = json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        with self._lock, self._connection:
            query = """
                UPDATE incidents
                SET last_emitted = ?,
                    last_emitted_severity = CASE
                        WHEN ? = '' THEN severity ELSE ? END,
                    payload_json = ?
                WHERE fingerprint = ? AND status = 'active'
            """
            parameters: list[Any] = [
                emitted_at,
                delivered_severity,
                delivered_severity,
                encoded_payload,
                fingerprint,
            ]
            if starts_at is not None:
                query += " AND starts_at = ?"
                parameters.append(starts_at)
            self._connection.execute(query, parameters)

    def is_actionable(self, fingerprint: str, starts_at: str) -> bool:
        """Return whether this exact incident generation still needs work."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT 1 FROM incidents
                WHERE fingerprint = ? AND starts_at = ?
                  AND status = 'active' AND consecutive_absent = 0
                """,
                (fingerprint, starts_at),
            ).fetchone()
        return row is not None

    def mark_resolved(
        self, fingerprint: str, *, now: float | None = None
    ) -> None:
        resolved_at = time.time() if now is None else float(now)
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE incidents
                SET status = 'resolved', resolved_at = ?
                WHERE fingerprint = ? AND status = 'active'
                """,
                (resolved_at, fingerprint),
            )

    def count_by_status(self) -> dict[str, int]:
        """Return bounded lifecycle counts for agent self-observability."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS count FROM incidents GROUP BY status"
            ).fetchall()
        counts = {"active": 0, "resolved": 0}
        counts.update({str(row["status"]): int(row["count"]) for row in rows})
        return counts

    def close(self) -> None:
        with self._lock:
            self._connection.close()
