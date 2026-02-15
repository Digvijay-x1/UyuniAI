import time
import sys
import traceback
import argparse

from uyuni_ai_agent.config import load_config
from uyuni_ai_agent.prometheus_client import get_all_metrics
from uyuni_ai_agent.anomaly_detector import check_all_metrics
from uyuni_ai_agent.react_agent import investigate
from uyuni_ai_agent.alert_manager import send_to_alertmanager


print("[DEBUG] main.py module loaded")  #LOGS REM


def run(dry_run=False):
    """Main polling loop. Loops all 4 steps together:
    1. INGEST  -- query Prometheus for metrics
    2. DETECT  -- check thresholds for anomalies
    3. INTELLIGENCE -- ReAct agent investigates via Salt + LLM
    4. ACTION  -- push enriched alert to AlertManager
    """
    print("[DEBUG] run() called, dry_run=%s" % dry_run)  #LOGS REM

    try:
        config = load_config()
        print("[DEBUG] config loaded successfully")  #LOGS REM
        print("[DEBUG] config keys: %s" % list(config.keys()))  #LOGS REM
    except Exception as e:
        print("[ERROR] Failed to load config: %s" % e)  #LOGS REM
        traceback.print_exc()  #LOGS REM
        return

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
            print("[DEBUG] Step 1: querying Prometheus...")  #LOGS REM
            try:
                metrics = get_all_metrics(instance)
                print(f"Metrics: mem={metrics['memory_percent']:.1f}%, "
                      f"cpu={metrics['cpu_percent']:.1f}%, "
                      f"disk={metrics['disk_percent']:.1f}%")
            except Exception as e:
                print("[ERROR] Prometheus query failed: %s" % e)  #LOGS REM
                traceback.print_exc()  #LOGS REM
                continue

            # Step 2: DETECT
            print("[DEBUG] Step 2: checking thresholds...")  #LOGS REM
            try:
                anomalies = check_all_metrics(instance, minion_id)
                print("[DEBUG] Found %d anomalies" % len(anomalies))  #LOGS REM
            except Exception as e:
                print("[ERROR] Anomaly detection failed: %s" % e)  #LOGS REM
                traceback.print_exc()  #LOGS REM
                continue

            if not anomalies:
                print("All metrics within normal range.")
                continue

            for anomaly in anomalies:
                print(f"ANOMALY: {anomaly.description} "
                      f"[{anomaly.severity.value}]")

                # Step 3: INTELLIGENCE
                print("[DEBUG] Step 3: running ReAct agent...")  #LOGS REM
                try:
                    analysis = investigate(anomaly, metrics)
                    print(f"Analysis:\n{analysis}\n")
                except Exception as e:
                    print("[ERROR] ReAct agent failed: %s" % e)  #LOGS REM
                    traceback.print_exc()  #LOGS REM
                    analysis = f"Agent error: {e}"

                # Step 4: ACTION
                if dry_run:
                    print(f"[DRY RUN] Would send alert: {anomaly.description}")
                    print(f"[DRY RUN] Analysis: {analysis}")
                else:
                    print("[DEBUG] Step 4: sending to AlertManager...")  #LOGS REM
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
        sys.stdout.flush()  #LOGS REM
        time.sleep(interval)


if __name__ == "__main__":
    print("[DEBUG] __main__ entry point")  #LOGS REM
    parser = argparse.ArgumentParser(
        description="AI-Powered Monitoring Agent for Uyuni"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print alerts instead of sending to AlertManager"
    )
    args = parser.parse_args()
    print("[DEBUG] args parsed: dry_run=%s" % args.dry_run)  #LOGS REM
    try:
        run(dry_run=args.dry_run)
    except Exception as e:
        print("[FATAL] Unhandled exception: %s" % e)  #LOGS REM
        traceback.print_exc()  #LOGS REM
