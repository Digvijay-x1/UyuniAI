import logging
import time
import argparse
import os

from uyuni_ai_agent.config import load_config
from uyuni_ai_agent.logging_config import setup_logging
from uyuni_ai_agent.prometheus_client import get_all_metrics
from uyuni_ai_agent.anomaly_detector import check_all_metrics
from uyuni_ai_agent.react_agent import investigate
from uyuni_ai_agent.alert_manager import send_to_alertmanager

logger = logging.getLogger(__name__)


def run(dry_run=False):
    """Main polling loop that executes all 4 steps each iteration:
    1. INGEST  -- query Prometheus for metrics
    2. DETECT  -- check thresholds for anomalies
    3. INTELLIGENCE -- ReAct agent investigates via Salt + LLM
    4. ACTION  -- push enriched alert to AlertManager
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

    logger.info("AI Monitoring Agent started. Polling every %ds.", interval)
    if dry_run:
        logger.info("DRY RUN mode: alerts will be printed, not sent.")

    while True:
        for minion in config["minions"]:
            instance = minion["instance"]
            minion_id = minion["id"]
            apache_instance = minion.get("apache_instance")
            postgres_instance = minion.get("postgres_instance")

            logger.info("--- Checking %s (%s) ---", minion_id, instance)

            # Step 1: INGEST
            logger.debug("Step 1: querying Prometheus...")
            try:
                metrics = get_all_metrics(
                    instance,
                    apache_instance=apache_instance,
                    postgres_instance=postgres_instance,
                )
                logger.info(
                    "Metrics: mem=%.1f%%, cpu=%.1f%%, disk=%.1f%%",
                    metrics['memory_percent'],
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
                continue

            # Step 2: DETECT
            logger.debug("Step 2: checking thresholds...")
            try:
                anomalies = check_all_metrics(
                    instance, minion_id,
                    apache_instance=apache_instance,
                    postgres_instance=postgres_instance,
                )
                logger.debug("Found %d anomalies", len(anomalies))
            except Exception as e:
                logger.error("Anomaly detection failed: %s", e, exc_info=True)
                continue

            if not anomalies:
                logger.info("All metrics within normal range.")
                continue

            for anomaly in anomalies:
                logger.warning(
                    "ANOMALY: %s [%s]", anomaly.description, anomaly.severity.value
                )

                # Step 3: INTELLIGENCE
                logger.debug("Step 3: running ReAct agent...")
                try:
                    analysis = investigate(anomaly, metrics)
                    logger.info("Analysis:\n%s", analysis)
                except Exception as e:
                    logger.error("ReAct agent failed: %s", e, exc_info=True)
                    analysis = f"Agent error: {e}"

                # Step 4: ACTION
                if dry_run:
                    logger.info("[DRY RUN] Would send alert: %s", anomaly.description)
                    logger.info("[DRY RUN] Analysis: %s", analysis)
                else:
                    logger.debug("Step 4: sending to AlertManager...")
                    summary = f"{anomaly.metric_name} issue on {anomaly.minion_id}"
                    result = send_to_alertmanager(
                        summary=summary,
                        description=analysis,
                        severity=anomaly.severity.value,
                        minion_id=anomaly.minion_id,
                        metric_name=anomaly.metric_name,
                    )
                    logger.info("AlertManager: %s", result)

        logger.info("Sleeping %ds...", interval)
        time.sleep(interval)


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
        run(dry_run=args.dry_run)
    except Exception as e:
        logger.critical("Unhandled exception", exc_info=True)
