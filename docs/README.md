# Documentation

This directory contains the operating and engineering documentation for the
Uyuni AI Agent. The repository root [README](../README.md) is the project entry
point; use this index when you need the detailed contract for a specific task.

## Start here

| Audience | Document | Purpose |
|---|---|---|
| Evaluators and new users | [Project README](../README.md) | Capabilities, prerequisites, and safe first steps |
| GSoC evaluators and future maintainers | [GSoC 2026 final report](gsoc-final-report.md) | Accomplishments, code cutoff, validation, and remaining work |
| Developers and reviewers | [Architecture](architecture.md) | Components, data flow, lifecycle, and failure behavior |
| Deployers | [Operations](operations.md) | Production deployment, health checks, upgrade, and rollback |
| Config owners | [Configuration](configuration.md) | Settings, environment variables, defaults, and tuning guidance |
| Contributors | [Development](development.md) | Local setup, tests, repository layout, and extension workflow |
| Security reviewers | [Security model](security.md) | Trust boundaries, permissions, sensitive data, and mitigations |
| Notification owners | [Alert contract](alert-contract.md) | Alertmanager labels, annotations, identity, firing, and resolution |
| AI quality owners | [Evaluation](evaluation.md) | Scenario catalog and evidence-based acceptance criteria |
| Operators | [Runbooks](runbooks/README.md) | Symptom-driven response procedures for agent alerts |
| Maintainers | [Architecture decisions](adr/README.md) | Decisions that constrain future changes |

Project-wide contribution and vulnerability-reporting policies live in
[CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md).

## Documentation conventions

- Commands state which host they are intended to run on.
- Examples use placeholder hostnames and never contain production secrets.
- Configuration names match `config/settings.yaml` and
  `uyuni_ai_agent/config_schema.py`.
- Alert fields match `uyuni_ai_agent/alert_manager.py`.
- A behavior change is incomplete until the affected document is updated in
  the same pull request.
