import time
import argparse

from uyuni_ai_agent.config import load_config
from uyuni_ai_agent.prometheus_client import get_all_metrics
from uyuni_ai_agent.anomaly_detector import check_all_metrics
from uyuni_ai_agent.react_agent import investigate
from uyuni_ai_agent.alert_manager import send_to_alertmanager


def run(dry_run=False):
    """Main polling loop. Ties all 4 steps together:
    1. INGEST  -- query Prometheus for metrics
    2. DETECT  -- check thresholds for anomalies
    3. INTELLIGENCE -- ReAct agent investigates via Salt + LLM
    4. ACTION  -- push enriched alert to AlertManager
    """
    config = load_config()
    interval = config["polling"]["interval_seconds"]

    print(f"AI Monitoring Agent started. Polling every {interval}s.")
    if dry_run:
        print("DRY RUN mode: alerts will be printed, not sent.")

    while True:
        for minion in config["minions"]:
            instance = minion["instance"]
            minion_id = minion["id"]

            print(f"\n--- Checking {minion_id} ({instance}) ---")

            # Step 1: INGEST
            metrics = get_all_metrics(instance)
            print(f"Metrics: mem={metrics['memory_percent']:.1f}%, "
                  f"cpu={metrics['cpu_percent']:.1f}%, "
                  f"disk={metrics['disk_percent']:.1f}%")

            # Step 2: DETECT
            anomalies = check_all_metrics(instance, minion_id)

            if not anomalies:
                print("All metrics within normal range.")
                continue

            for anomaly in anomalies:
                print(f"ANOMALY: {anomaly.description} "
                      f"[{anomaly.severity.value}]")

                # Step 3: INTELLIGENCE
                print("Running ReAct agent investigation...")
                analysis = investigate(anomaly, metrics)
                print(f"Analysis:\n{analysis}\n")

                # Step 4: ACTION
                if dry_run:
                    print(f"[DRY RUN] Would send alert: {anomaly.description}")
                    print(f"[DRY RUN] Analysis: {analysis}")
                else:
                    summary = f"{anomaly.metric_name} issue on {anomaly.minion_id}"
                    result = send_to_alertmanager(
                        summary=summary,
                        description=analysis,
                        severity=anomaly.severity.value,
                        minion_id=anomaly.minion_id,
                        metric_name=anomaly.metric_name,
                    )
                    print(f"AlertManager: {result}")

        print(f"\nSleeping {interval}s...")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AI-Powered Monitoring Agent for Uyuni"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print alerts instead of sending to AlertManager"
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
