# Operation timeouts

**Alert:** `UyuniAIAgentTimeouts`

## Symptoms

More than two bounded operations exceeded their deadline in ten minutes. The
alert includes a `scope` label such as `salt`, `minion`, `poll_cycle`, `llm`, or
`investigation`.

## Checks

```promql
increase(uyuni_ai_agent_timeouts_total{job="uyuni-ai-agent"}[10m])
histogram_quantile(0.95, rate(uyuni_ai_agent_poll_duration_seconds_bucket{job="uyuni-ai-agent"}[10m]))
histogram_quantile(0.95, rate(uyuni_ai_agent_investigation_duration_seconds_bucket{job="uyuni-ai-agent"}[10m]))
```

Correlate the scope with dependency circuits, queue depth, host resource
pressure, and recent deployment or topology changes.

## Safe actions

- Restore slow or failing dependencies.
- Reduce incoming incident fan-out at the source if an alert storm is active.
- Confirm queue and concurrency values match available capacity.
- Use dry-run evaluation before changing timeout values.

## Recovery verification

Timeout growth stops, latency returns to the expected range, and the alert is
quiet after the rule's evaluation window.

## Escalate when

Timeouts continue with healthy dependencies and low queue depth, indicating a
possible code regression or host resource problem.

## Do not

Do not raise deadlines beyond evidence freshness and polling objectives merely
to silence this alert.
