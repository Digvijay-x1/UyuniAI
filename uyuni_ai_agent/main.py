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

import httpx

from uyuni_ai_agent.config import load_config
from uyuni_ai_agent.deduplication import AnomalyDeduplicator
from uyuni_ai_agent.logging_config import setup_logging
from uyuni_ai_agent.prometheus_client import get_all_metrics
from uyuni_ai_agent.anomaly_detector import (
    check_all_metrics,
    check_failed_services,
    check_postgres_blocked_transactions,
    DependencyCorrelationWindow,
)
from uyuni_ai_agent.react_agent import investigate
from uyuni_ai_agent.alert_manager import send_to_alertmanager
from uyuni_ai_agent.salt_api import SaltAPIClient, set_salt_client

logger = logging.getLogger(__name__)


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
                        "Metrics: mem=%.1f%%, swap=%.1f%%, "
                        "swap_activity=%.1f pages/s, cpu=%.1f%%, disk=%.1f%%"
                    ),
                    metrics['memory_percent'],
                    metrics.get("memory_pressure", {}).get(
                        "swap_usage_percent", 0
                    ),
                    metrics.get("memory_pressure", {}).get(
                        "swap_activity_pages_per_second", 0
                    ),
                    metrics['cpu_percent'],
                    metrics['disk_percent'],
                )
                if apache_instance:
                    logger.info(
                        "Apache: busy_workers=%.1f%%, req/s=%.1f",
                        metrics.get('apache_busy_workers_percent', 0),
                        metrics.get('apache_requests_per_sec', 0),
                    )
                if postgres_instance:
                    logger.info(
                        "PostgreSQL: connections=%.1f%%, deadlocks/min=%.1f",
                        metrics.get('postgres_active_connections_percent', 0),
                        metrics.get('postgres_deadlocks_per_min', 0),
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


async def process_minion_anomalies(
    snapshot,
    all_cycle_anomalies,
    http_client,
    config,
    dry_run,
    llm_sem,
    deduplicator,
):
    """Investigate and alert for one minion after global correlation."""
    minion_id = snapshot["minion"]["id"]
    metrics = snapshot["metrics"]
    detected_anomalies = [
        anomaly
        for anomaly in all_cycle_anomalies
        if anomaly.minion_id == minion_id
    ]

    try:
        anomalies = deduplicator.filter(minion_id, detected_anomalies)
        if not detected_anomalies:
            logger.info(
                "%s: all metrics, systemd services, and PostgreSQL locks "
                "within normal range.",
                minion_id,
            )
            return
        if not anomalies:
            logger.info(
                "%s: detected anomalies are unchanged and inside the "
                "deduplication cooldown.",
                minion_id,
            )
            return

        for anomaly in anomalies:
            logger.warning(
                "ANOMALY: %s [%s]", anomaly.description, anomaly.severity.value
            )

            logger.debug("Step 3: running ReAct agent...")
            analysis = None
            try:
                async with llm_sem:
                    analysis = await investigate(anomaly, metrics, config)
                logger.info("Analysis:\n%s", analysis.to_text())
            except Exception as e:
                logger.error("ReAct agent failed: %s", e, exc_info=True)

            if analysis is None:
                logger.error(
                    "Skipping alert for %s: investigation produced no analysis.",
                    anomaly.description,
                )
            elif dry_run:
                logger.info("[DRY RUN] Would send alert: %s", anomaly.description)
                logger.info("[DRY RUN] Analysis:\n%s", analysis.to_text())
            else:
                logger.debug("Step 4: sending to AlertManager...")
                result = await send_to_alertmanager(
                    http_client,
                    config,
                    analysis,
                    severity=anomaly.severity.value,
                    minion_id=anomaly.minion_id,
                    metric_name=anomaly.metric_name,
                    service_name=anomaly.service_name or "",
                    resource=anomaly.resource or "",
                )
                logger.info("AlertManager: %s", result)
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

    minion_sem = asyncio.Semaphore(max_minions)
    llm_sem = asyncio.Semaphore(max_llm_calls)
    deduplicator = AnomalyDeduplicator(
        config.get("deduplication", {}).get("cooldown_seconds", 900)
    )
    correlation_cfg = config.get("dependency_correlation", {})
    dependency_correlator = DependencyCorrelationWindow(
        correlation_cfg.get("grace_seconds", 90)
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
        await salt.start()
        while not stop.is_set():
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
                    llm_sem,
                    deduplicator,
                )
                for snapshot in snapshots
            ))

            logger.info("Sleeping %ds...", interval)
            # Sleep for the interval, but wake promptly if asked to stop.
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass  # interval elapsed normally; loop again
    finally:
        await http_client.aclose()
        await salt.aclose()
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
