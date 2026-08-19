# Investigation queue saturated

**Alert:** `UyuniAIAgentQueueSaturated`

## Symptoms

The pending queue is at least 80 percent full for two minutes. Lower-priority
work may be rejected or evicted to make room for critical work.

## Checks

```promql
uyuni_ai_agent_investigation_queue_pending{job="uyuni-ai-agent"}
increase(uyuni_ai_agent_investigation_queue_events_total{job="uyuni-ai-agent",event=~"rejected|evicted"}[10m])
```

Check whether the incident rate is genuine, whether investigations are timing
out, and whether an external dependency is failing.

## Safe actions

- Restore the slow dependency.
- Stop an alert storm at its source using the owning service's incident process.
- Validate worker and concurrency capacity before a controlled change.
- Preserve queue and incident metrics for post-incident analysis.

## Recovery verification

Queue depth declines, rejection/eviction rates stop increasing, and critical
work completes. Confirm that previously unprocessed incidents remain eligible
for retry.

## Escalate when

Critical work is repeatedly evicted, the queue never drains, or the agent host
cannot support the configured workers.

## Do not

Do not acknowledge, delete, or manually mark incidents that the agent did not
actually investigate and deliver.
