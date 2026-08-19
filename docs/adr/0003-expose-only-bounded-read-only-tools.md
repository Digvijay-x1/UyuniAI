# ADR-0003: Expose only bounded read-only investigation tools

- Status: Accepted
- Date: 2026-08-19

## Context

An LLM-assisted investigator needs host evidence, but a generic shell, SQL, or
service-management tool would allow untrusted model output or prompt-injected
text to trigger arbitrary production actions.

## Decision

Expose named diagnostic tools with fixed purposes. Validate targets and
arguments, construct commands in application code, bound output and deadlines,
and do not expose remediation or arbitrary command execution to the model.

## Consequences

Positive:

- sharply limits the impact of hallucination and prompt injection;
- makes evidence collection testable and reviewable;
- supports data minimization; and
- keeps production changes under human control.

Negative:

- every new incident family may require a new tool or inspection path;
- fixed tools can miss unusual evidence; and
- underlying Salt permissions can still be broader than application behavior.

## Alternatives considered

- Give the model a generic shell tool.
- Run model-generated SQL directly.
- Remove host inspection and use telemetry only.
