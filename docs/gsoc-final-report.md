# Google Summer of Code 2026 Final Report

## AI-Powered Intelligent Monitoring and Root Cause Analysis for Uyuni

**Contributor:** Digvijay Rawat  
**Organization:** [openSUSE](https://www.opensuse.org/)  
**Project issue:** [openSUSE/mentoring#251](https://github.com/openSUSE/mentoring/issues/251)  
**Code repository:** [github.com/Digvijay-x1/UyuniAI](https://github.com/Digvijay-x1/UyuniAI)  
**Mentors:** Jordi Massaguer and Oscar Barrios

This document is the GSoC-specific final report for my openSUSE Google Summer
of Code 2026 project.

## Project summary

Uyuni already collects useful infrastructure telemetry through Prometheus and
can inspect managed systems through Salt, but a raw alert such as "high CPU"
does not explain the cause or provide enough context for an operator. The goal
of this project was to build an isolated AI monitoring agent that combines
Prometheus anomalies with bounded, read-only Salt evidence and sends an
evidence-grounded root-cause analysis (RCA) through Alertmanager.

The resulting service is a Python application designed to run as a non-root
Podman/Quadlet container in the Uyuni environment. It supports deterministic
analysis for proven patterns and uses a configured LLM only for ambiguous
investigations. Missing, stale, failed, contradictory, or insufficient
evidence produces an inconclusive result rather than an unsupported diagnosis.

## Relation to the original proposal

The project follows the five deliverables in issue #251:

1. containerized AI monitoring service;
2. Salt API integration for read-only client inspection;
3. enriched Alertmanager alerts and routing templates;
4. documentation for configuration, operation, security, and extension; and
5. automated tests that exercise failure and RCA behavior.

The implementation also adds durable incident state, bounded asynchronous
investigations, conservative evidence quality gates, topology-gated
cross-node correlation, protected observability endpoints, and production
deployment guidance.

## Work completed

### 1. Prometheus anomaly detection

The agent executes bounded PromQL requests and rejects stale, missing,
non-finite, or failed samples instead of turning telemetry failures into zero
values. It detects:

- CPU saturation and process pressure;
- memory pressure, including current swap activity;
- filesystem utilization and resource-specific disk anomalies;
- failed or restarting systemd services;
- Apache busy workers and request overload;
- PostgreSQL connection pressure, deadlocks, and blocked transactions; and
- telemetry/dependency failures such as stale Prometheus data or unavailable
  Salt inspection.

Uyuni inventory discovery is authoritative for Salt targets. Prometheus active
targets are joined only to add exporter endpoints, so an exporter cannot create
an untrusted Salt target.

### 2. Bounded Salt inspection

`uyuni_ai_agent/salt_api.py` authenticates to Uyuni's Salt REST API and exposes
validated, read-only inspection calls. The inspection modules collect bounded
evidence for CPU, memory, disk, services, Apache, PostgreSQL, and configured
SSH/TLS/NFS dependency edges. The LLM is not given a general shell tool;
commands, services, paths, targets, and database queries are fixed or strictly
validated by the application.

### 3. Evidence-grounded RCA

Every collected fact receives an incident-local evidence ID. A conclusion can
be confirmed only when its citations refer to records that were actually
collected, are fresh, have an acceptable status, meet the minimum evidence
threshold, and are not contradicted by another record. Destructive remediation
and protocol bypass suggestions are removed by the safety policy. Proven
patterns, such as a service port conflict or a PostgreSQL blocker, can be
resolved deterministically without an LLM.

Ambiguous cases use a LangGraph ReAct workflow with the configured provider.
The provider adapter supports OpenAI-compatible models, Google Gemini,
Hugging Face endpoints, and TokenRouter, with an optional process-wide request
limiter and bounded deadlines.

### 4. Incident lifecycle and resilience

The agent persists incident fingerprints, alert identity, delivery state,
cooldowns, and resolution state in SQLite. It sends firing and exact-identity
resolved notifications to Alertmanager. Failed delivery, Salt/API failures,
LLM timeouts, stale queued snapshots, and process restarts remain retryable.

The investigation queue has a fixed capacity, severity-aware priority,
duplicate coalescing, worker limits, job-age limits, retry behavior, and a
graceful shutdown budget. Circuit breakers and jittered backoff prevent a
temporary dependency failure from causing a restart loop or retry storm.

### 5. Cross-node correlation

The project implements topology-gated correlation for related PostgreSQL and
Apache incidents. A correlation is allowed only when the configured dependency
edge and exporter capabilities prove that the systems participate in a known
traffic path. Simultaneous alerts on unrelated systems remain separate and
inconclusive rather than being merged by time alone.

### 6. Observability and secure deployment

The service exposes `/healthz`, `/readyz`, and low-cardinality Prometheus
metrics. The production deployment uses a non-root container, a persistent
SQLite volume, root-readable environment secrets, and a Quadlet systemd unit.
The metrics endpoint is published through a socket-activated, source-restricted
proxy rather than directly to the public network. Alertmanager templates,
Prometheus scrape/rule installation, host firewall configuration, and
operational runbooks are included under `deploy/` and `docs/`.

### 7. Documentation and engineering quality

The repository now includes documentation for architecture, configuration,
development, operations, security, alert contracts, evaluation scenarios,
runbooks, and architecture decisions. The CI workflow runs linting, unit tests,
dependency auditing, SBOM generation, and a non-root container check.

## Validation and results

The test suite covers configuration validation, Prometheus truthfulness, Salt
target and command boundaries, CPU/memory/disk/service/Apache/PostgreSQL
inspection, evidence citation and freshness, deterministic RCA, LLM fallback,
incident lifecycle, Alertmanager delivery, queue backpressure, resilience,
observability, monitoring configuration, documentation links, and adversarial
scenarios.

At report preparation, the local CI-equivalent checks completed successfully:
`ruff check .` passed and `pytest -q -p no:cacheprovider` passed all 194 tests.
The repository CI additionally audits dependencies, generates an SBOM, builds
the container, and verifies its non-root runtime user.

The scenario catalog in [`evaluation/scenarios.yaml`](../evaluation/scenarios.yaml)
covers:

- isolated CPU saturation;
- service port conflict;
- disk-induced crash loop;
- PostgreSQL blocked transaction;
- memory swap thrashing;
- a PostgreSQL-to-Apache cross-node causal chain;
- Salt dependency outage;
- stale Prometheus samples;
- unrelated cross-node alerts; and
- investigation queue backpressure.

The repository provides deterministic and unit-level validation for these
contracts. Live fault injection remains environment-specific and requires a
running Uyuni server, managed clients, Prometheus, Alertmanager, exporters,
and a selected model endpoint. The live validation artifacts to retain are
documented in [`docs/evaluation.md`](evaluation.md): injection/cleanup times,
raw alerts and samples, bounded evidence, structured RCA, scenario score, and
recovery/resolution metrics.

## Current state

The GSoC implementation is complete and usable as a production-shaped service.
It can be built as a non-root container, started in dry-run mode, exercised
with the included test suite and scenario catalog, and extended using the
tracked architecture, configuration, security, operations, and development
documentation. Enabling notifications and removing dry-run mode still require
deployment-specific endpoints, credentials, permissions, thresholds, and
Alertmanager routing; those are environment release steps, not unfinished GSoC
implementation deliverables.

## Code contributions and upstream status

The implementation code, tests, deployment assets, and documentation are in
the `main` history of the [project repository](https://github.com/Digvijay-x1/UyuniAI).
The complete GSoC code contribution is the repository history through the
cutoff commit identified below. The later report, README, and documentation
index changes only package that work for evaluation. This project repository is
the submitted code location. No separate upstream pull request is part of this
submission; an evaluator can review the implementation directly here without
reconstructing it from another repository.

The principal implementation areas are the `uyuni_ai_agent/` runtime package,
`tests/`, `config/`, `prompts/`, `evaluation/`, `deploy/`, and the tracked
engineering documentation under `docs/`.

For direct review at the implementation cutoff, see the
[`uyuni_ai_agent/`](https://github.com/Digvijay-x1/UyuniAI/tree/f54151277dc0f303f6272def572f152e7ffe1448/uyuni_ai_agent),
[`tests/`](https://github.com/Digvijay-x1/UyuniAI/tree/f54151277dc0f303f6272def572f152e7ffe1448/tests),
[`deploy/`](https://github.com/Digvijay-x1/UyuniAI/tree/f54151277dc0f303f6272def572f152e7ffe1448/deploy),
and [`docs/`](https://github.com/Digvijay-x1/UyuniAI/tree/f54151277dc0f303f6272def572f152e7ffe1448/docs)
directories.

## Challenges and lessons learned

Several engineering constraints shaped the final design:

- Missing, stale, failed, or contradictory telemetry cannot safely be treated
  as normal values. Evidence freshness, citation, and contradiction gates were
  therefore made part of the RCA contract.
- LLM output must not become an unrestricted operations interface. Bounded
  read-only tools, deterministic analysis for proven patterns, and explicit
  safety filtering keep investigation separate from remediation.
- Alert storms and dependency outages can overwhelm an otherwise healthy
  service. Durable incident state, queue bounds, retries, circuit breakers, and
  graceful shutdown make failure behavior predictable.
- Time-based correlation alone creates false cross-node diagnoses. Correlation
  is consequently gated by configured topology and exporter capabilities.

These lessons are reflected in the architecture decisions, tests, runbooks,
and security documentation linked from the repository index.

## Code cutoff and scope

The GSoC implementation is the complete repository state through commit:

[f54151277dc0f303f6272def572f152e7ffe1448](https://github.com/Digvijay-x1/UyuniAI/commit/f54151277dc0f303f6272def572f152e7ffe1448)

Commit message: `docs: add production operations guidance`  
Date: 19 August 2026 (author date)

This is the final implementation commit immediately before this GSoC report
was added. All files and repository history through this commit are part of my
GSoC work. The report and the accompanying README link are documentation
updates made to package that work for evaluation; they do not change the
implementation cutoff.

## Remaining work / TODO for future maintainers

The GSoC implementation is complete; there are no unfinished implementation
deliverables for this contribution. The following are concrete follow-on tasks
for someone who continues the project:

1. Run the live fault-injection scenarios against a real Uyuni deployment and
   retain the raw alerts, Prometheus samples, bounded evidence, structured RCA,
   scenario scores, and recovery/resolution timings described in
   [`docs/evaluation.md`](evaluation.md).
2. Validate the production-shaped deployment on the target topology, then tune
   thresholds, exporter labels, Salt permissions, model/provider settings, and
   Alertmanager routes for that environment.
3. Re-run the test, dependency-audit, SBOM, and non-root-container checks when
   dependencies, model providers, or deployment images are upgraded.
4. Add new collectors, RCA patterns, or topology relationships only when
   operational requirements introduce a new supported incident class; preserve
   the existing evidence, freshness, and safety gates.

## How to continue the work

Start with [`docs/development.md`](development.md), then review
[`docs/architecture.md`](architecture.md),
[`docs/configuration.md`](configuration.md), and
[`docs/operations.md`](operations.md). Run:

```bash
pytest -q -p no:cacheprovider
ruff check .
```

For a deployment-shaped test, follow [`docs/operations.md`](operations.md) and
keep credentials, activation keys, webhook URLs, and model keys outside the
repository.

## Acknowledgements

I thank my openSUSE mentors Jordi Massaguer and Oscar Barrios, the Uyuni and
openSUSE communities, and the Google Summer of Code program for the guidance,
review, and opportunity to work on this project.
