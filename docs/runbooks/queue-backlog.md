# Investigation queue backlog

**Alert:** `UyuniAIAgentQueueBacklog`

## Symptoms

More than ten investigations remain queued for ten minutes. Detection may still
be working, but investigation and notification latency is increasing.

## Checks

```promql
uyuni_ai_agent_investigation_queue_pending{job="uyuni-ai-agent"}
uyuni_ai_agent_investigations_in_flight{job="uyuni-ai-agent"}
rate(uyuni_ai_agent_investigation_queue_events_total{job="uyuni-ai-agent"}[10m])
```

Inspect dependency circuits, timeout scopes, LLM latency, and the current
incident volume. Check whether duplicate coalescing is functioning.

## Safe actions

- Repair slow dependencies.
- Reduce upstream alert fan-out or temporarily lower non-critical thresholds
  only through the normal change process.
- Confirm `max_pending`, worker count, and concurrency limits are intentional.

## Recovery verification

Pending depth trends down and remains below the configured alert threshold.
Critical incidents complete within the investigation objective.

## Escalate when

The queue grows while workers are idle, or rejected/evicted work increases
without corresponding dependency failures.

## Do not

Do not remove the queue bound or delete queue state to make the metric reset.
