# ADR-0001: Use Uyuni's Salt REST API for minion inspection

- Status: Accepted
- Date: 2026-08-19

## Context

The agent needs current diagnostic evidence from Uyuni-managed systems. Direct
SSH would require distributing another credential and maintaining independent
target inventory, connectivity, authorization, and auditing.

Uyuni already manages the targets through Salt and exposes an authenticated
REST API.

## Decision

Use Uyuni's Salt REST API for bounded minion inspection. Authenticate with a
dedicated external-auth identity and restrict it to intended targets and
necessary functions.

## Consequences

Positive:

- reuses Uyuni's existing target identity and connectivity;
- avoids distributing SSH keys to the agent;
- centralizes remote-call auditing and policy; and
- works with minions that are not directly reachable from the agent host.

Negative:

- Salt becomes a runtime dependency;
- `cmd.run` remains a high-impact permission even when application commands are
  fixed; and
- Salt API availability and credential rotation become operating concerns.

## Alternatives considered

- Direct SSH to each minion.
- Installing a separate diagnostic agent on every node.
- Diagnosing only from Prometheus without host evidence.
