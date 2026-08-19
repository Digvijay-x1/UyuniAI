# ADR-0002: Use SQLite for durable incident state

- Status: Accepted
- Date: 2026-08-19

## Context

The process must preserve incident identity, cooldown, delivery state, and the
last firing payload across restarts. In-memory state would duplicate active
alerts after every restart and could not create exact-identity resolutions.

Adding an external database would increase deployment and failure complexity
for state owned by one agent instance.

## Decision

Store lifecycle state in a local SQLite database on a persistent named volume.
Use WAL mode and retain the last successfully delivered firing payload for
resolution.

## Consequences

Positive:

- restart-safe identity and deduplication;
- no additional network service;
- transactional updates; and
- straightforward backup with the deployment state volume.

Negative:

- the deployment is single-writer and not active-active;
- schema changes require migration and rollback planning; and
- state-volume loss can duplicate alerts or prevent old alerts from resolving.

## Alternatives considered

- In-memory dictionaries.
- Alertmanager as the only state store.
- PostgreSQL or another external database.
