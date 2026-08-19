# Agent not ready

**Alert:** `UyuniAIAgentNotReady`

## Symptoms

`/healthz` is available, but `uyuni_ai_agent_ready == 0` for five minutes.
The process is alive, but no recent usable poll and/or a required dependency is
available.

## Checks

```bash
curl -fsS http://127.0.0.1:19898/healthz
curl -i http://127.0.0.1:19898/readyz
curl -fsS http://127.0.0.1:19898/metrics
podman logs --since 15m ai-agent
```

Inspect dependency and poll metrics:

```promql
uyuni_ai_agent_dependency_up{job="uyuni-ai-agent"}
uyuni_ai_agent_dependency_circuit_state{job="uyuni-ai-agent",state="open"}
time() - uyuni_ai_agent_last_successful_poll_timestamp_seconds{job="uyuni-ai-agent"}
```

## Safe actions

- Repair an unavailable dependency according to its owner runbook.
- Verify the configured endpoints and credentials in the root-readable
  environment file without printing its contents.
- Restart the service once after correcting configuration:

  ```bash
  systemctl restart uyuni-ai-agent.service
  ```

## Recovery verification

After at least one successful poll, `/readyz` returns HTTP 200,
`uyuni_ai_agent_ready` is 1, and the alert resolves.

## Escalate when

Readiness remains false after Salt and Prometheus recover, or the last poll is
successful but the endpoint reports an unexpected dependency requirement.

## Do not

Do not disable readiness alerts to hide a dependency outage.
