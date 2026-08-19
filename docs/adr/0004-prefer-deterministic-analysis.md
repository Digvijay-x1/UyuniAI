# ADR-0004: Prefer deterministic analysis when evidence proves a cause

- Status: Accepted
- Date: 2026-08-19

## Context

Some incident patterns, such as a demonstrated port conflict or a directly
observed PostgreSQL blocker, can be proven from structured evidence. Sending
every case to an LLM adds latency, cost, variability, and another failure path.

## Decision

Use deterministic analysis for recognized evidence patterns when the collected
records directly satisfy the pattern. Use the LLM for ambiguous cases, then
apply the same evidence-grounding quality gates to the structured result.

## Consequences

Positive:

- repeatable conclusions for known patterns;
- lower model cost and latency;
- continued partial operation during model outages; and
- reduced hallucination exposure.

Negative:

- deterministic patterns require ongoing code and test maintenance;
- overly broad patterns could create false certainty; and
- new incident types initially rely on the model or remain inconclusive.

## Alternatives considered

- Always use an LLM.
- Use only static rules and never use an LLM.
- Accept model output without evidence grounding.
