# Architecture Decision Records

Architecture Decision Records (ADRs) preserve the context behind choices that
constrain implementation, operations, security, or compatibility.

## Index

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-use-uyuni-salt-api-for-inspection.md) | Accepted | Use Uyuni's Salt REST API for minion inspection |
| [0002](0002-use-sqlite-for-incident-state.md) | Accepted | Persist incident lifecycle in local SQLite |
| [0003](0003-expose-only-bounded-read-only-tools.md) | Accepted | Expose only bounded read-only tools to the investigation agent |
| [0004](0004-prefer-deterministic-analysis.md) | Accepted | Prefer deterministic analysis when evidence directly proves a cause |
| [0005](0005-bound-and-prioritize-investigations.md) | Accepted | Bound and prioritize asynchronous investigations |
| [0006](0006-gate-cross-minion-correlation-by-topology.md) | Accepted | Correlate cross-minion incidents only across declared topology |

## Format

Each ADR records a status, date, context, decision, consequences, and considered
alternatives. Accepted ADRs are historical records. If a decision changes, add
a new ADR and mark the previous one `Superseded by ADR-NNNN` rather than
rewriting its rationale.
