# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project intends to use [Semantic Versioning](https://semver.org/) when
versioned releases begin.

## [Unreleased]

### Added

- Automatic trusted-minion discovery from the Uyuni Manager API.
- Topology-gated, read-only SSH, TLS, and NFS dependency inspection.
- Privacy-preserving LangSmith spans for deterministic RCA decisions.
- Structured-output schema repair retry and protocol-specific remediation
  safety policies.
- Production documentation index and audience map.
- Architecture, configuration, development, security, and Alertmanager
  contract documentation.
- Contribution and vulnerability-reporting policies.
- Operational runbooks for the agent's self-monitoring alerts.
- Architecture Decision Records for Salt inspection, durable SQLite state,
  bounded tools, deterministic analysis, queue backpressure, and topology-gated
  correlation.

### Changed

- The root README is now a concise project entry point that links to detailed
  task-oriented documentation.

## Release process

When cutting a release:

1. move applicable `Unreleased` entries into a dated version section;
2. document configuration, alert-label, persistence, and deployment migrations;
3. record tested Python, Uyuni, Prometheus, Alertmanager, and model compatibility;
4. attach or retain the generated SBOM;
5. publish upgrade and rollback verification; and
6. tag the exact reviewed commit.
