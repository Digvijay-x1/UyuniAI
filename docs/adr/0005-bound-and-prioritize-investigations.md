# ADR-0005: Bound and prioritize asynchronous investigations

- Status: Accepted
- Date: 2026-08-19

## Context

Polling must continue while investigations perform comparatively slow Salt and
LLM work. An unbounded task-per-anomaly design can exhaust memory, overload
dependencies, investigate obsolete snapshots, and delay critical incidents
behind low-priority work.

## Decision

Use a bounded priority queue with a fixed worker pool. Coalesce duplicate
incidents, permit critical work to displace lower-priority pending work, expire
stale jobs, and never acknowledge rejected or evicted work.

## Consequences

Positive:

- predictable memory and dependency load;
- severity-aware response under pressure;
- continued detection while investigations run; and
- safe retry of work that was never processed.

Negative:

- overload can delay or repeatedly reject lower-severity incidents;
- queue sizing requires capacity tuning; and
- shutdown may abandon in-flight work after the grace period.

## Alternatives considered

- Investigate synchronously inside the poll loop.
- Spawn an unbounded asynchronous task for every anomaly.
- Drop new work silently when capacity is reached.
