"""Low-cardinality runtime metrics and local health endpoints.

The monitoring agent must itself be observable without leaking investigation
text, commands, SQL, credentials, or arbitrary resource names.  This module
therefore exposes only fixed metric names and bounded label values.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)

logger = logging.getLogger(__name__)

_QUEUE_COUNTER_FIELDS = (
    "enqueued",
    "coalesced",
    "completed",
    "failed",
    "rejected",
    "evicted",
    "cancelled",
)
_HTTP_READ_TIMEOUT_SECONDS = 2.0
_HTTP_MAX_HEADER_BYTES = 8192
_DEPENDENCIES = ("salt", "prometheus", "llm", "alertmanager")
_DEPENDENCY_OUTCOMES = ("success", "error", "timeout", "circuit_open")
_CIRCUIT_STATES = ("closed", "open", "half_open")
_TIMEOUT_SCOPES = (
    "salt",
    "prometheus",
    "minion",
    "poll_cycle",
    "llm",
    "investigation",
    "alertmanager",
)


class AgentObservability:
    """Own one isolated Prometheus registry and agent readiness state."""

    def __init__(
        self,
        *,
        readiness_max_age_seconds: float,
        clock: Callable[[], float] = time.time,
        include_runtime_collectors: bool = True,
        required_dependencies: set[str] | None = None,
    ):
        if readiness_max_age_seconds <= 0:
            raise ValueError("readiness_max_age_seconds must be greater than 0")
        self.readiness_max_age_seconds = float(readiness_max_age_seconds)
        self._clock = clock
        self._last_successful_poll_at: float | None = None
        self._required_dependencies = frozenset(required_dependencies or ())
        unknown = self._required_dependencies - set(_DEPENDENCIES)
        if unknown:
            raise ValueError(f"unknown required dependencies: {sorted(unknown)}")
        self._dependency_available = {
            dependency: False for dependency in _DEPENDENCIES
        }
        self._last_queue_totals = {
            field: 0 for field in _QUEUE_COUNTER_FIELDS
        }
        self.registry = CollectorRegistry(auto_describe=True)

        if include_runtime_collectors:
            GCCollector(registry=self.registry)
            PlatformCollector(registry=self.registry)
            ProcessCollector(registry=self.registry)

        self.up = Gauge(
            "uyuni_ai_agent_up",
            "Whether the monitoring agent process is running.",
            registry=self.registry,
        )
        self.ready_metric = Gauge(
            "uyuni_ai_agent_ready",
            "Whether a successful polling cycle occurred recently.",
            registry=self.registry,
        )
        self.start_time = Gauge(
            "uyuni_ai_agent_start_time_seconds",
            "Unix timestamp when this agent instance started.",
            registry=self.registry,
        )
        self.last_successful_poll = Gauge(
            "uyuni_ai_agent_last_successful_poll_timestamp_seconds",
            "Unix timestamp of the last poll that reached at least one minion.",
            registry=self.registry,
        )
        self.poll_cycles = Counter(
            "uyuni_ai_agent_poll_cycles_total",
            "Polling cycles by outcome.",
            ("outcome",),
            registry=self.registry,
        )
        self.poll_duration = Histogram(
            "uyuni_ai_agent_poll_duration_seconds",
            "End-to-end duration of one polling cycle.",
            buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )
        self.minion_polls = Counter(
            "uyuni_ai_agent_minion_polls_total",
            "Minion polling attempts by outcome.",
            ("outcome",),
            registry=self.registry,
        )
        self.anomaly_observations = Counter(
            "uyuni_ai_agent_anomaly_observations_total",
            "Anomalies observed during polling, by severity.",
            ("severity",),
            registry=self.registry,
        )
        self.queue_pending = Gauge(
            "uyuni_ai_agent_investigation_queue_pending",
            "Investigations waiting in the bounded queue.",
            registry=self.registry,
        )
        self.queue_in_flight = Gauge(
            "uyuni_ai_agent_investigations_in_flight",
            "Investigations currently executing.",
            registry=self.registry,
        )
        self.queue_events = Counter(
            "uyuni_ai_agent_investigation_queue_events_total",
            "Investigation queue lifecycle events.",
            ("event",),
            registry=self.registry,
        )
        self.investigations = Counter(
            "uyuni_ai_agent_investigations_total",
            "Completed investigation attempts by severity and outcome.",
            ("severity", "outcome"),
            registry=self.registry,
        )
        self.investigation_duration = Histogram(
            "uyuni_ai_agent_investigation_duration_seconds",
            "Investigation duration by outcome.",
            ("outcome",),
            buckets=(1, 2.5, 5, 10, 30, 60, 120, 300, 600),
            registry=self.registry,
        )
        self.incidents = Gauge(
            "uyuni_ai_agent_incidents",
            "Durable incidents by lifecycle status.",
            ("status",),
            registry=self.registry,
        )
        self.alert_deliveries = Counter(
            "uyuni_ai_agent_alertmanager_deliveries_total",
            "Alertmanager deliveries by alert state and outcome.",
            ("state", "outcome"),
            registry=self.registry,
        )
        self.alert_delivery_duration = Histogram(
            "uyuni_ai_agent_alertmanager_delivery_duration_seconds",
            "Alertmanager delivery duration by alert state.",
            ("state",),
            buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
            registry=self.registry,
        )
        self.dependency_up = Gauge(
            "uyuni_ai_agent_dependency_up",
            "Whether an external dependency's last operation succeeded.",
            ("dependency",),
            registry=self.registry,
        )
        self.dependency_operations = Counter(
            "uyuni_ai_agent_dependency_operations_total",
            "Dependency operations by bounded outcome.",
            ("dependency", "outcome"),
            registry=self.registry,
        )
        self.dependency_duration = Histogram(
            "uyuni_ai_agent_dependency_operation_duration_seconds",
            "Dependency operation duration.",
            ("dependency",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
            registry=self.registry,
        )
        self.dependency_circuit = Gauge(
            "uyuni_ai_agent_dependency_circuit_state",
            "One-hot dependency circuit state.",
            ("dependency", "state"),
            registry=self.registry,
        )
        self.dependency_failures = Gauge(
            "uyuni_ai_agent_dependency_consecutive_failures",
            "Consecutive failures recorded by the dependency circuit.",
            ("dependency",),
            registry=self.registry,
        )
        self.timeouts = Counter(
            "uyuni_ai_agent_timeouts_total",
            "Runtime timeouts by bounded operation scope.",
            ("scope",),
            registry=self.registry,
        )

        now = self._clock()
        self.up.set(1)
        self.ready_metric.set(0)
        self.start_time.set(now)
        self.last_successful_poll.set(0)
        for outcome in ("success", "partial", "failed"):
            self.poll_cycles.labels(outcome=outcome).inc(0)
        for outcome in ("success", "failed"):
            self.minion_polls.labels(outcome=outcome).inc(0)
        for event in _QUEUE_COUNTER_FIELDS:
            self.queue_events.labels(event=event).inc(0)
        for status in ("active", "resolved"):
            self.incidents.labels(status=status).set(0)
        for dependency in _DEPENDENCIES:
            self.dependency_up.labels(dependency=dependency).set(0)
            self.dependency_failures.labels(dependency=dependency).set(0)
            for outcome in _DEPENDENCY_OUTCOMES:
                self.dependency_operations.labels(
                    dependency=dependency, outcome=outcome
                ).inc(0)
            for state in _CIRCUIT_STATES:
                self.dependency_circuit.labels(
                    dependency=dependency, state=state
                ).set(1 if state == "closed" else 0)
        for scope in _TIMEOUT_SCOPES:
            self.timeouts.labels(scope=scope).inc(0)

    @property
    def ready(self) -> bool:
        if self._last_successful_poll_at is None:
            return False
        age = self._clock() - self._last_successful_poll_at
        dependencies_ready = all(
            self._dependency_available[name]
            for name in self._required_dependencies
        )
        return (
            0 <= age <= self.readiness_max_age_seconds
            and dependencies_ready
        )

    def mark_stopping(self) -> None:
        self.ready_metric.set(0)
        self.up.set(0)

    def record_poll(
        self,
        *,
        duration_seconds: float,
        total_minions: int,
        successful_minions: int,
    ) -> str:
        total = max(0, int(total_minions))
        successful = min(total, max(0, int(successful_minions)))
        failed = total - successful
        if total > 0 and successful == total:
            outcome = "success"
        elif successful > 0:
            outcome = "partial"
        else:
            outcome = "failed"

        self.poll_cycles.labels(outcome=outcome).inc()
        self.poll_duration.observe(max(0.0, float(duration_seconds)))
        if successful:
            self.minion_polls.labels(outcome="success").inc(successful)
            now = self._clock()
            self._last_successful_poll_at = now
            self.last_successful_poll.set(now)
        if failed:
            self.minion_polls.labels(outcome="failed").inc(failed)
        self._refresh_readiness()
        return outcome

    def record_anomaly_observations(self, anomalies: list[Any]) -> None:
        for anomaly in anomalies:
            raw = getattr(anomaly, "severity", "unknown")
            severity = str(getattr(raw, "value", raw)).lower()
            if severity not in {"info", "warning", "critical"}:
                severity = "unknown"
            self.anomaly_observations.labels(severity=severity).inc()

    def observe_queue(self, stats: Any) -> None:
        """Update gauges and derive monotonic event counters from queue stats."""
        self.queue_pending.set(max(0, int(stats.pending)))
        self.queue_in_flight.set(max(0, int(stats.in_flight)))
        for field in _QUEUE_COUNTER_FIELDS:
            current = max(0, int(getattr(stats, field)))
            previous = self._last_queue_totals[field]
            if current > previous:
                self.queue_events.labels(event=field).inc(current - previous)
            self._last_queue_totals[field] = current

    def record_investigation(
        self,
        *,
        severity: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        normalized_severity = str(severity).lower()
        if normalized_severity not in {"info", "warning", "critical"}:
            normalized_severity = "unknown"
        normalized_outcome = str(outcome).lower()
        self.investigations.labels(
            severity=normalized_severity,
            outcome=normalized_outcome,
        ).inc()
        self.investigation_duration.labels(
            outcome=normalized_outcome
        ).observe(max(0.0, float(duration_seconds)))

    def record_incident_counts(self, counts: dict[str, int]) -> None:
        for status in ("active", "resolved"):
            self.incidents.labels(status=status).set(
                max(0, int(counts.get(status, 0)))
            )

    def record_alert_delivery(
        self,
        *,
        state: str,
        result: str,
        duration_seconds: float,
    ) -> str:
        if str(result).startswith("Success:"):
            outcome = "success"
        elif str(result).startswith("Error: 4"):
            outcome = "rejected"
        elif str(result).startswith("Error: 5"):
            outcome = "server_error"
        elif "Connection failed:" in str(result):
            outcome = "network_error"
        else:
            outcome = "error"
        normalized_state = "resolved" if state == "resolved" else "firing"
        self.alert_deliveries.labels(
            state=normalized_state, outcome=outcome
        ).inc()
        self.alert_delivery_duration.labels(
            state=normalized_state
        ).observe(max(0.0, float(duration_seconds)))
        return outcome

    def record_dry_run_delivery(self, *, state: str) -> None:
        normalized_state = "resolved" if state == "resolved" else "firing"
        self.alert_deliveries.labels(
            state=normalized_state, outcome="dry_run"
        ).inc()

    def record_dependency(
        self,
        dependency: str,
        outcome: str,
        duration_seconds: float,
        circuit_snapshot: Any,
    ) -> None:
        if dependency not in _DEPENDENCIES:
            raise ValueError(f"unknown dependency {dependency!r}")
        normalized_outcome = str(outcome).lower()
        if normalized_outcome not in _DEPENDENCY_OUTCOMES:
            normalized_outcome = "error"
        state_value = getattr(circuit_snapshot, "state", "open")
        state = str(getattr(state_value, "value", state_value)).lower()
        if state not in _CIRCUIT_STATES:
            state = "open"
        available = normalized_outcome == "success"
        self._dependency_available[dependency] = available
        self.dependency_up.labels(dependency=dependency).set(
            1 if available else 0
        )
        self.dependency_operations.labels(
            dependency=dependency, outcome=normalized_outcome
        ).inc()
        self.dependency_duration.labels(dependency=dependency).observe(
            max(0.0, float(duration_seconds))
        )
        failures = max(
            0, int(getattr(circuit_snapshot, "consecutive_failures", 0))
        )
        self.dependency_failures.labels(dependency=dependency).set(failures)
        for candidate in _CIRCUIT_STATES:
            self.dependency_circuit.labels(
                dependency=dependency, state=candidate
            ).set(1 if candidate == state else 0)
        self._refresh_readiness()

    def record_timeout(self, scope: str) -> None:
        normalized = str(scope).lower()
        if normalized not in _TIMEOUT_SCOPES:
            raise ValueError(f"unknown timeout scope {scope!r}")
        self.timeouts.labels(scope=normalized).inc()

    def render_metrics(self) -> bytes:
        self._refresh_readiness()
        return generate_latest(self.registry)

    def _refresh_readiness(self) -> None:
        self.ready_metric.set(1 if self.ready else 0)


class ObservabilityServer:
    """Minimal read-only HTTP server for metrics and health probes."""

    def __init__(self, observability: AgentObservability, host: str, port: int):
        self.observability = observability
        self.host = str(host)
        self.port = int(port)
        self._server: asyncio.AbstractServer | None = None

    @property
    def bound_port(self) -> int | None:
        if self._server is None or not self._server.sockets:
            return None
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("observability server is already started")
        self._server = await asyncio.start_server(
            self._handle,
            self.host,
            self.port,
            limit=_HTTP_MAX_HEADER_BYTES,
        )
        logger.info(
            "Agent observability listening on http://%s:%d",
            self.host,
            self.bound_port,
        )

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            header = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"),
                timeout=_HTTP_READ_TIMEOUT_SECONDS,
            )
            if len(header) > _HTTP_MAX_HEADER_BYTES:
                await self._respond(writer, 431, b"request headers too large\n")
                return
            request_line = header.split(b"\r\n", 1)[0]
            parts = request_line.decode("ascii", errors="replace").split()
            if len(parts) != 3:
                await self._respond(writer, 400, b"bad request\n")
                return
            method, raw_path, _version = parts
            if method not in {"GET", "HEAD"}:
                await self._respond(writer, 405, b"method not allowed\n")
                return
            path = raw_path.split("?", 1)[0]
            if path == "/metrics":
                body = self.observability.render_metrics()
                content_type = CONTENT_TYPE_LATEST
                status = 200
            elif path == "/healthz":
                body = _json_status("ok")
                content_type = "application/json; charset=utf-8"
                status = 200
            elif path == "/readyz":
                ready = self.observability.ready
                body = _json_status("ready" if ready else "not_ready")
                content_type = "application/json; charset=utf-8"
                status = 200 if ready else 503
            else:
                body = b"not found\n"
                content_type = "text/plain; charset=utf-8"
                status = 404
            await self._respond(
                writer,
                status,
                body,
                content_type=content_type,
                head_only=method == "HEAD",
            )
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            await self._respond(writer, 400, b"bad request\n")
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception:
            logger.exception("Observability HTTP request failed")
            try:
                await self._respond(writer, 500, b"internal error\n")
            except (ConnectionError, BrokenPipeError):
                pass

    @staticmethod
    async def _respond(
        writer: asyncio.StreamWriter,
        status: int,
        body: bytes,
        *,
        content_type: str = "text/plain; charset=utf-8",
        head_only: bool = False,
    ) -> None:
        reason = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            431: "Request Header Fields Too Large",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }.get(status, "Unknown")
        header = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        try:
            writer.write(header)
            if not head_only:
                writer.write(body)
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, BrokenPipeError):
                pass


def _json_status(status: str) -> bytes:
    return (json.dumps({"status": status}, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
