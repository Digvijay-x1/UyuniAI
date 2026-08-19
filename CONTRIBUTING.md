# Contributing

Thank you for improving the Uyuni AI Agent. Changes to this project can affect
production monitoring, remote inspection, external data processing, and
incident routing, so contributions should preserve conservative failure and
evidence behavior.

## Before opening a change

Read the relevant documents:

- [Development](docs/development.md) for setup and repository workflow;
- [Architecture](docs/architecture.md) for lifecycle and failure semantics;
- [Security model](docs/security.md) for trust and tool boundaries;
- [Evaluation](docs/evaluation.md) for RCA acceptance criteria; and
- [Architecture decisions](docs/adr/README.md) for constraints that should not
  be changed accidentally.

For vulnerabilities, do not open a public issue. Follow [SECURITY.md](SECURITY.md).

## Pull requests

Keep each pull request focused on one coherent behavior. Include:

1. the problem and operational impact;
2. the approach and important alternatives considered;
3. tests covering success, failure, timeout, stale-data, and restart behavior
   where applicable;
4. documentation updates for externally visible behavior;
5. evaluation changes for detector, evidence, prompt, or model behavior; and
6. upgrade or rollback notes for configuration, alert identity, persistence, or
   deployment changes.

Do not include credentials, production logs, raw incident evidence, customer
hostnames, or generated environment files.

## Required checks

Run locally before requesting review:

```bash
ruff check .
pytest -q -p no:cacheprovider
pip-audit --require-hashes -r requirements.lock
```

CI also builds the container, verifies its non-root runtime identity, and
generates an SBOM.

## Definition of done

A change is complete when:

- startup configuration is validated and unknown keys still fail closed;
- remote inspection remains bounded and read-only;
- no new secret or sensitive-data path is introduced without review;
- confirmed conclusions require fresh, usable, cited evidence;
- unsupported conclusions remain inconclusive;
- transient dependency or delivery failures remain retryable;
- queue rejection does not acknowledge unprocessed work;
- firing and resolution preserve Alertmanager identity;
- metrics use bounded labels and do not expose incident content;
- tests and evaluation criteria cover the behavior; and
- architecture, configuration, alert, security, operations, and runbook docs
  are updated where applicable.

## Review focus by change type

| Change | Required review focus |
|---|---|
| Detector or threshold | False positives, freshness, identity, cooldown, evaluation |
| Salt tool or command | Injection, authorization, output bounds, timeouts, sensitive data |
| Prompt or model | Structured output, citations, adversarial evidence, cost and latency |
| Alert label | Alertmanager identity, prior-label resolution, routes, templates |
| SQLite schema | Migration, backup, forward/rollback compatibility |
| Queue or concurrency | Backpressure, starvation, retry, shutdown |
| Metrics | Cardinality, data leakage, alert rule impact |
| Deployment | Non-root execution, secrets, networking, state persistence, rollback |

## Architectural decisions

If a change introduces a durable constraint or reverses an existing design
choice, add an Architecture Decision Record under `docs/adr/`. Do not rewrite
accepted ADR history; add a new ADR that supersedes the old one.

## Changelog

Add user-visible, operator-visible, security-relevant, or compatibility-relevant
changes to the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md). Pure test or
internal refactoring changes do not need an entry unless they alter observable
behavior.
