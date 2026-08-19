# ADR-0006: Gate cross-minion correlation by declared topology

- Status: Accepted
- Date: 2026-08-19

## Context

Alerts on different hosts can occur close together without sharing a cause.
Temporal proximity alone can make an RCA incorrectly merge unrelated incidents,
especially in larger fleets.

## Decision

Allow cross-minion PostgreSQL-to-Apache correlation only across explicitly
declared dependency edges. Retain a one-sided candidate for a bounded grace
period to accommodate independent scrape timing.

## Consequences

Positive:

- prevents unrelated hosts from being merged solely by time;
- makes correlation assumptions reviewable configuration; and
- supports repeatable cross-layer evaluation.

Negative:

- topology must be maintained manually;
- undeclared real dependencies cannot be correlated; and
- incorrect edges can still create misleading candidates.

## Alternatives considered

- Correlate any simultaneous PostgreSQL and Apache anomalies.
- Infer topology automatically from hostnames.
- Disable all cross-minion correlation.
