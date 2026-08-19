# Alert delivery failures

**Alert:** `UyuniAIAgentAlertDeliveryFailures`

## Symptoms

At least one firing or resolved notification failed to reach Alertmanager in
the last ten minutes.

## Checks

```promql
increase(uyuni_ai_agent_alertmanager_deliveries_total{job="uyuni-ai-agent",outcome="failure"}[10m])
rate(uyuni_ai_agent_alertmanager_delivery_duration_seconds_bucket{job="uyuni-ai-agent"}[10m])
```

```bash
podman logs --since 15m ai-agent
```

Check Alertmanager health, the configured `ALERTMANAGER_URL`, network policy,
TLS, and HTTP response status. HTTP 4xx generally means a rejected payload;
HTTP 5xx and connection errors are transient candidates.

## Safe actions

- Restore Alertmanager availability or correct the endpoint and certificate.
- Validate the payload contract and route configuration in a non-production
  environment for 4xx responses.
- Allow later polls to retry after a transient failure.

## Recovery verification

Successful delivery counters increase, Alertmanager shows the expected firing
or resolved alert, and the failure alert resolves.

## Escalate when

Alertmanager accepts requests but notifications do not reach receivers, or a
label/annotation change causes a persistent 4xx rejection.

## Do not

Do not manually resolve an Alertmanager alert unless the incident process
explicitly accepts the loss of the agent's durable identity and audit trail.
