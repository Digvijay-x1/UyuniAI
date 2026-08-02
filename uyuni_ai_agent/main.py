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

import logging
import argparse
import os
import asyncio
import signal
import time
from dataclasses import dataclass

import httpx

from uyuni_ai_agent.config import load_config
from uyuni_ai_agent.incident_store import IncidentStore
from uyuni_ai_agent.investigation_queue import (
    CancelStatus,
    EnqueueStatus,
    InvestigationQueue,
)
from uyuni_ai_agent.observability import AgentObservability, ObservabilityServer
from uyuni_ai_agent.logging_config import setup_logging
from uyuni_ai_agent.prometheus_client import get_all_metrics
from uyuni_ai_agent.anomaly_detector import (
    check_all_metrics,
    check_failed_services,
    check_postgres_blocked_transactions,
    DependencyCorrelationWindow,
)
from uyuni_ai_agent.react_agent import investigate
from uyuni_ai_agent.alert_manager import (
    alert_delivery_succeeded,
    build_alert_payload,
    build_resolved_payload,
    send_alert_payload,
)
from uyuni_ai_agent.salt_api import SaltAPIClient, set_salt_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InvestigationWork:
    firing: object
    metrics: dict
    detected_at: float


def _metric_text(value, suffix="%"):
    """Render absent telemetry honestly in operator logs."""
    if value is None:
        return "unavailable"
    return f"{float(value):.1f}{suffix}"


async def _send_observed_alert(
    http_client,
    config,
    payload,
    observability,
    *,
    state,
):
    """Deliver an alert and record the actual result without parsing logs."""
    started = time.monotonic()
    result = await send_alert_payload(http_client, config, payload)
    if observability is not None:
        observability.record_alert_delivery(
            state=state,
            result=result,
            duration_seconds=time.monotonic() - started,
        )
    return result


async def detect_minion(
    minion,
    http_client,
    config,
    minion_sem,
    salt_client,
):
    """Ingest and detect one minion, returning a cycle snapshot.

    Detection is intentionally separated from investigation so anomalies from
    every minion can be correlated before any alert is emitted.
    """
    try:
        instance = minion["instance"]
        minion_id = minion["id"]
        apache_instance = minion.get("apache_instance")
        postgres_instance = minion.get("postgres_instance")

        async with minion_sem:
            logger.info("--- Checking %s (%s) ---", minion_id, instance)

            # Step 1: INGEST
            logger.debug("Step 1: querying Prometheus...")
            try:
                metrics = await get_all_metrics(
                    instance, http_client, config,
                    apache_instance=apache_instance,
                    postgres_instance=postgres_instance,
                )
                logger.info(
                    (
                        "Metrics: mem=%s, swap=%s, "
                        "swap_activity=%s, cpu=%s, disk=%s"
                    ),
                    _metric_text(metrics["memory_percent"]),
                    _metric_text(
                        metrics.get("memory_pressure", {}).get(
                            "swap_usage_percent"
                        )
                    ),
                    _metric_text(
                        metrics.get("memory_pressure", {}).get(
                            "swap_activity_pages_per_second"
                        ),
                        " pages/s",
                    ),
                    _metric_text(metrics["cpu_percent"]),
                    _metric_text(metrics["disk_percent"]),
                )
                if apache_instance:
                    logger.info(
                        "Apache: busy_workers=%s, req/s=%s",
                        _metric_text(
                            metrics.get("apache_busy_workers_percent")
                        ),
                        _metric_text(
                            metrics.get("apache_requests_per_sec"), ""
                        ),
                    )
                if postgres_instance:
                    logger.info(
                        "PostgreSQL: connections=%s, deadlocks/min=%s",
                        _metric_text(
                            metrics.get("postgres_active_connections_percent")
                        ),
                        _metric_text(
                            metrics.get("postgres_deadlocks_per_min"),
                            "",
                        ),
                    )
            except Exception as e:
                logger.error("Prometheus query failed: %s", e, exc_info=True)
                return

            # Step 2: DETECT
            logger.debug("Step 2: checking metrics and systemd services...")
            try:
                metric_anomalies = await check_all_metrics(
                    instance, minion_id, http_client, config,
                    apache_instance=apache_instance,
                    postgres_instance=postgres_instance,
                    metrics=metrics,
                )
                service_anomalies = await check_failed_services(
                    minion_id, salt_client, config
                )
                postgres_lock_anomalies = []
                if postgres_instance:
                    postgres_lock_anomalies = (
                        await check_postgres_blocked_transactions(
                            minion_id, salt_client, config
                        )
                    )
                detected_anomalies = (
                    metric_anomalies
                    + service_anomalies
                    + postgres_lock_anomalies
                )
                restarting_services = [
                    anomaly.service_name
                    for anomaly in service_anomalies
                    if anomaly.service_name
                ]
                for anomaly in metric_anomalies:
                    if anomaly.metric_name == "disk":
                        anomaly.context["related_unhealthy_services"] = (
                            restarting_services
                        )
                logger.debug(
                    "Found %d metric, %d service, and %d PostgreSQL lock anomalies",
                    len(metric_anomalies),
                    len(service_anomalies),
                    len(postgres_lock_anomalies),
                )
            except Exception as e:
                logger.error("Anomaly detection failed: %s", e, exc_info=True)
                return None

            return {
                "minion": minion,
                "metrics": metrics,
                "anomalies": detected_anomalies,
            }
    except Exception as e:
        failed_id = minion.get("id", "<unknown>") if isinstance(minion, dict) else "<unknown>"
        logger.error("Minion %s processing failed: %s", failed_id, e, exc_info=True)
        return None


async def _process_firing_investigation(
    work,
    http_client,
    config,
    dry_run,
    llm_sem,
    incident_store,
    max_job_age_seconds,
    observability,
):
    """Investigate and deliver one queued incident when it is still current."""
    firing = work.firing
    anomaly = firing.anomaly
    age = time.time() - work.detected_at
    if age > max_job_age_seconds:
        logger.warning(
            "Skipping stale investigation %s (age %.0fs > %.0fs); a fresh "
            "poll can enqueue it again.",
            firing.fingerprint,
            age,
            max_job_age_seconds,
        )
        return "stale"
    if not incident_store.is_actionable(
        firing.fingerprint, firing.starts_at
    ):
        logger.info(
            "Skipping investigation %s because that incident generation is "
            "no longer active.",
            firing.fingerprint,
        )
        return "obsolete"

    logger.warning(
        "INVESTIGATING: %s [%s] incident=%s",
        anomaly.description,
        anomaly.severity.value,
        firing.fingerprint,
    )
    analysis = None
    try:
        async with llm_sem:
            analysis = await investigate(anomaly, work.metrics, config)
        logger.info("Analysis:\n%s", analysis.to_text())
    except Exception as e:
        logger.error("ReAct agent failed: %s", e, exc_info=True)

    if analysis is None:
        logger.error(
            "Skipping alert for %s: investigation produced no analysis.",
            anomaly.description,
        )
        return "investigation_failed"
    if not incident_store.is_actionable(
        firing.fingerprint, firing.starts_at
    ):
        logger.info(
            "Discarding completed investigation %s because the incident "
            "recovered or was replaced while evidence was collected.",
            firing.fingerprint,
        )
        return "recovered"

    payload = build_alert_payload(
        analysis,
        severity=anomaly.severity.value,
        minion_id=anomaly.minion_id,
        metric_name=anomaly.metric_name,
        service_name=anomaly.service_name or "",
        resource=anomaly.resource or "",
        incident_id=firing.fingerprint,
        starts_at=firing.starts_at,
    )

    # Severity is a routing label in Alertmanager. Resolve the prior label
    # set before emitting an escalation with a new label set.
    previous_payload = firing.previous_payload
    labels_changed = (
        previous_payload is not None
        and previous_payload.get("labels") != payload.get("labels")
    )
    if labels_changed and not dry_run:
        transition_result = await _send_observed_alert(
            http_client,
            config,
            build_resolved_payload(previous_payload),
            observability,
            state="resolved",
        )
        logger.info(
            "AlertManager label-transition resolution: %s",
            transition_result,
        )
        if not alert_delivery_succeeded(transition_result):
            logger.error(
                "Skipping replacement alert for %s because its prior "
                "Alertmanager identity could not be resolved.",
                firing.fingerprint,
            )
            return "transition_failed"
        if not incident_store.is_actionable(
            firing.fingerprint, firing.starts_at
        ):
            logger.info(
                "Skipping replacement alert %s because it recovered during "
                "the label transition.",
                firing.fingerprint,
            )
            return "recovered"

    if dry_run:
        logger.info("[DRY RUN] Would send alert: %s", anomaly.description)
        logger.info("[DRY RUN] Analysis:\n%s", analysis.to_text())
        incident_store.mark_emitted(
            firing.fingerprint,
            payload,
            starts_at=firing.starts_at,
        )
        if observability is not None:
            observability.record_dry_run_delivery(state="firing")
        return "dry_run"
    else:
        logger.debug("Step 4: sending to AlertManager...")
        result = await _send_observed_alert(
            http_client,
            config,
            payload,
            observability,
            state="firing",
        )
        logger.info("AlertManager: %s", result)
        if alert_delivery_succeeded(result):
            incident_store.mark_emitted(
                firing.fingerprint,
                payload,
                starts_at=firing.starts_at,
            )
            return "delivered"
        return "delivery_failed"


async def process_firing_investigation(
    work,
    http_client,
    config,
    dry_run,
    llm_sem,
    incident_store,
    max_job_age_seconds,
    observability=None,
):
    """Measure one investigation while preserving queue retry semantics."""
    started = time.monotonic()
    outcome = "worker_error"
    severity = str(
        getattr(work.firing.anomaly.severity, "value", "unknown")
    )
    try:
        outcome = await _process_firing_investigation(
            work,
            http_client,
            config,
            dry_run,
            llm_sem,
            incident_store,
            max_job_age_seconds,
            observability,
        )
        return outcome
    finally:
        if observability is not None:
            observability.record_investigation(
                severity=severity,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
            )


async def process_minion_anomalies(
    snapshot,
    all_cycle_anomalies,
    http_client,
    config,
    dry_run,
    incident_store,
    investigation_queue,
    observability=None,
):
    """Reconcile one minion and queue only actionable firing work."""
    minion_id = snapshot["minion"]["id"]
    metrics = snapshot["metrics"]
    detected_anomalies = [
        anomaly
        for anomaly in all_cycle_anomalies
        if anomaly.minion_id == minion_id
    ]

    try:
        changes = incident_store.reconcile(minion_id, detected_anomalies)

        for incident in changes.resolved:
            cancel_status = await investigation_queue.cancel(
                incident.fingerprint
            )
            if cancel_status is CancelStatus.IN_FLIGHT:
                logger.info(
                    "Deferring resolution for incident %s until its in-flight "
                    "investigation finishes.",
                    incident.fingerprint,
                )
                continue
            if incident.payload is None:
                incident_store.mark_resolved(incident.fingerprint)
                logger.info(
                    "RESOLVED locally: %s/%s had no delivered firing alert.",
                    incident.minion_id,
                    incident.metric_name,
                )
                continue

            resolved_payload = build_resolved_payload(incident.payload)
            if dry_run:
                logger.info(
                    "[DRY RUN] Would resolve incident %s: %s/%s",
                    incident.fingerprint,
                    incident.minion_id,
                    incident.metric_name,
                )
                incident_store.mark_resolved(incident.fingerprint)
                if observability is not None:
                    observability.record_dry_run_delivery(state="resolved")
                continue

            result = await _send_observed_alert(
                http_client,
                config,
                resolved_payload,
                observability,
                state="resolved",
            )
            logger.info("AlertManager resolution: %s", result)
            if alert_delivery_succeeded(result):
                incident_store.mark_resolved(incident.fingerprint)

        if not detected_anomalies:
            logger.info(
                "%s: all metrics, systemd services, and PostgreSQL locks "
                "within normal range.",
                minion_id,
            )
            return
        if not changes.firing:
            logger.info(
                "%s: detected anomalies are unchanged and inside the "
                "deduplication cooldown.",
                minion_id,
            )
            return

        for firing in changes.firing:
            anomaly = firing.anomaly
            enqueue_result = await investigation_queue.enqueue(
                firing.fingerprint,
                anomaly.severity,
                InvestigationWork(
                    firing=firing,
                    metrics=metrics,
                    detected_at=time.time(),
                ),
            )
            if enqueue_result.status is EnqueueStatus.ENQUEUED:
                logger.warning(
                    "ANOMALY queued: %s [%s] incident=%s pending=%d",
                    anomaly.description,
                    anomaly.severity.value,
                    firing.fingerprint,
                    enqueue_result.pending,
                )
                if enqueue_result.evicted_fingerprint:
                    logger.warning(
                        "Investigation queue evicted lower-priority incident "
                        "%s for critical incident %s; it remains unacknowledged "
                        "and will retry on a later poll.",
                        enqueue_result.evicted_fingerprint,
                        firing.fingerprint,
                    )
            elif enqueue_result.status is EnqueueStatus.COALESCED:
                logger.info(
                    "Refreshed pending investigation %s with the newest "
                    "snapshot (pending=%d).",
                    firing.fingerprint,
                    enqueue_result.pending,
                )
            elif enqueue_result.status is EnqueueStatus.IN_FLIGHT:
                logger.debug(
                    "Incident %s is already being investigated.",
                    firing.fingerprint,
                )
            else:
                logger.warning(
                    "Investigation backpressure: incident %s was not queued "
                    "(%s, pending=%d, in_flight=%d). It remains "
                    "unacknowledged and will retry on the next poll.",
                    firing.fingerprint,
                    enqueue_result.status.value,
                    enqueue_result.pending,
                    enqueue_result.in_flight,
                )
    except Exception as e:
        logger.error(
            "Minion %s investigation failed: %s",
            minion_id,
            e,
            exc_info=True,
        )


async def run(dry_run=False):
    """Main polling loop that executes all 4 steps each iteration:
    1. INGEST  -- query Prometheus for metrics
    2. DETECT  -- check thresholds for anomalies
    3. INTELLIGENCE -- ReAct agent investigates via Salt + LLM
    4. ACTION  -- push enriched alert to AlertManager

    Minions are processed in parallel (bounded by max_minions); within a
    minion everything is sequential. Salt and LLM calls are throttled by
    semaphores so the Salt Master / LLM API are not overwhelmed during
    alert storms.
    """
    logger.debug("run() called, dry_run=%s", dry_run)

    try:
        config = load_config()
        logger.debug("config loaded successfully")
        logger.debug("config keys: %s", list(config.keys()))
    except Exception as e:
        logger.error("Failed to load config: %s", e, exc_info=True)
        return

    interval = config["polling"]["interval_seconds"]
    concurrency_cfg = config.get("concurrency", {})
    max_minions = concurrency_cfg.get("max_minions", 8)
    max_llm_calls = concurrency_cfg.get("max_llm_calls", 5)
    queue_cfg = config.get("investigation_queue", {})
    max_job_age_seconds = queue_cfg.get("max_job_age_seconds", 300)
    observability_cfg = config.get("observability", {})
    observability = AgentObservability(
        readiness_max_age_seconds=observability_cfg.get(
            "readiness_max_age_seconds", max(60, interval * 3)
        )
    )
    observability_server = None
    if observability_cfg.get("enabled", True):
        observability_server = ObservabilityServer(
            observability,
            observability_cfg.get("host", "127.0.0.1"),
            observability_cfg.get("port", 9898),
        )

    minion_sem = asyncio.Semaphore(max_minions)
    llm_sem = asyncio.Semaphore(max_llm_calls)
    incident_cfg = config.get("incident_store", {})
    state_path = incident_cfg.get(
        "path", "/var/lib/uyuni-ai-agent/incidents.db"
    )
    if dry_run and state_path != ":memory:":
        state_path = f"{state_path}.dry-run"
    incident_store = IncidentStore(
        state_path,
        cooldown_seconds=config.get("deduplication", {}).get(
            "cooldown_seconds", 900
        ),
        resolve_after_healthy_cycles=incident_cfg.get(
            "resolve_after_healthy_cycles", 2
        ),
    )
    investigation_queue = InvestigationQueue(
        max_pending=queue_cfg.get("max_pending", 50),
        workers=queue_cfg.get("workers", 3),
        observer=observability.observe_queue,
    )
    correlation_cfg = config.get("dependency_correlation", {})
    apache_traffic_threshold = (
        config["thresholds"]["apache"]["requests_per_sec"]["warning"]
    )
    dependency_correlator = DependencyCorrelationWindow(
        correlation_cfg.get("grace_seconds", 90),
        apache_traffic_threshold=apache_traffic_threshold,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if os.name != "nt":
        loop.add_signal_handler(signal.SIGTERM, stop.set)

    logger.info("AI Monitoring Agent started. Polling every %ds.", interval)
    if dry_run:
        logger.info("DRY RUN mode: alerts will be printed, not sent.")

    http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    salt = SaltAPIClient(config)
    set_salt_client(salt)
    try:
        if observability_server is not None:
            await observability_server.start()
        await salt.start()
        await investigation_queue.start(
            lambda work: process_firing_investigation(
                work,
                http_client,
                config,
                dry_run,
                llm_sem,
                incident_store,
                max_job_age_seconds,
                observability,
            )
        )
        while not stop.is_set():
            poll_started = time.monotonic()
            snapshots = await asyncio.gather(*(
                detect_minion(
                    minion,
                    http_client,
                    config,
                    minion_sem,
                    salt,
                )
                for minion in config["minions"]
            ))
            successful_minions = sum(
                1 for snapshot in snapshots if snapshot is not None
            )
            snapshots = [snapshot for snapshot in snapshots if snapshot]

            cycle_anomalies = [
                anomaly
                for snapshot in snapshots
                for anomaly in snapshot["anomalies"]
            ]
            cycle_anomalies = dependency_correlator.correlate(
                cycle_anomalies,
                correlation_cfg.get("postgres_apache", []),
            )
            observability.record_anomaly_observations(cycle_anomalies)
            if dependency_correlator.last_held_count:
                logger.info(
                    "Holding %d dependency-correlation candidate(s) for "
                    "up to %.0fs to absorb scrape skew.",
                    dependency_correlator.last_held_count,
                    dependency_correlator.grace_seconds,
                )

            await asyncio.gather(*(
                process_minion_anomalies(
                    snapshot,
                    cycle_anomalies,
                    http_client,
                    config,
                    dry_run,
                    incident_store,
                    investigation_queue,
                    observability,
                )
                for snapshot in snapshots
            ))

            observability.record_incident_counts(
                incident_store.count_by_status()
            )
            poll_outcome = observability.record_poll(
                duration_seconds=time.monotonic() - poll_started,
                total_minions=len(config["minions"]),
                successful_minions=successful_minions,
            )

            queue_stats = investigation_queue.stats
            logger.info(
                "Investigation queue: pending=%d in_flight=%d completed=%d "
                "rejected=%d evicted=%d",
                queue_stats.pending,
                queue_stats.in_flight,
                queue_stats.completed,
                queue_stats.rejected,
                queue_stats.evicted,
            )
            logger.info(
                "Agent poll outcome=%s successful_minions=%d/%d",
                poll_outcome,
                successful_minions,
                len(config["minions"]),
            )
            logger.info("Sleeping %ds...", interval)
            # Sleep for the interval, but wake promptly if asked to stop.
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass  # interval elapsed normally; loop again
    finally:
        observability.mark_stopping()
        if observability_server is not None:
            await observability_server.close()
        shutdown = await investigation_queue.close(
            queue_cfg.get("shutdown_grace_seconds", 30)
        )
        if not shutdown.drained:
            logger.warning(
                "Investigation shutdown grace expired with %d job(s) "
                "unfinished; durable incident state will retry them after "
                "restart.",
                shutdown.abandoned,
            )
        await http_client.aclose()
        await salt.aclose()
        incident_store.close()
        logger.info("AI Monitoring Agent stopped.")


if __name__ == "__main__":
    # Setup logging
    default_level = os.environ.get("LOG_LEVEL", "INFO")
    setup_logging(level=default_level)

    try:
        config = load_config()
        config_level = config.get("logging", {}).get("level", None)
        if config_level and config_level.upper() != default_level.upper():
            setup_logging(level=config_level)
            logger.debug("Reconfigured logging to %s from settings.yaml", config_level)
    except Exception:
        logger.warning("Failed to load config, using default log level")

    logger.debug("__main__ entry point")
    parser = argparse.ArgumentParser(
        description="AI-Powered Monitoring Agent for Uyuni"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print alerts instead of sending to AlertManager"
    )
    args = parser.parse_args()
    logger.debug("args parsed: dry_run=%s", args.dry_run)
    try:
        asyncio.run(run(dry_run=args.dry_run))
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting.")
    except Exception:
        logger.critical("Unhandled exception", exc_info=True)
