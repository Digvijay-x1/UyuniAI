# Polling stalled

**Alert:** `UyuniAIAgentPollStalled`

## Symptoms

No complete successful minion poll has been recorded for more than four
minutes. The process may still answer health checks.

## Checks

```bash
curl -fsS http://127.0.0.1:19898/metrics
podman logs --since 15m ai-agent
```

```promql
time() - uyuni_ai_agent_last_successful_poll_timestamp_seconds{job="uyuni-ai-agent"}
rate(uyuni_ai_agent_poll_cycles_total{job="uyuni-ai-agent"}[10m])
uyuni_ai_agent_minion_polls_total{job="uyuni-ai-agent"}
```

Look for poll-cycle, minion, Salt, Prometheus, and timeout errors. One failed
minion should not prevent a fresh partial snapshot, so inspect whether all
configured minions or a shared dependency are failing.

## Safe actions

- Restore the failing dependency or minion connectivity.
- Check that `timeouts.poll_cycle_seconds` is not shorter than the configured
  per-minion work.
- Restart once if the process is wedged and logs show no external dependency
  fault:

  ```bash
  systemctl restart uyuni-ai-agent.service
  ```

## Recovery verification

Confirm the successful-poll timestamp advances, readiness returns, and the
alert resolves after the configured `for` period.

## Escalate when

Polls repeatedly exceed their deadline, queue workers never drain, or the
process consumes excessive CPU or memory.

## Do not

Do not increase all concurrency and timeout values at once during an incident;
that can amplify dependency load and hide the bottleneck.
