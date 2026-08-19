# Development

## Supported environment

CI tests Python 3.11 and 3.12 on Linux. The production image currently uses
Python 3.11. Development is possible on Windows or Linux; production deployment
uses Podman, systemd, and Quadlet on Linux.

## Set up a development environment

On PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

On a POSIX shell:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Do not commit `.env`. It is ignored because it can contain LLM, Salt, and
tracing credentials.

## Run quality checks

PowerShell:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

POSIX:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -p no:cacheprovider
```

The CI pipeline additionally audits hash-locked dependencies, creates a
CycloneDX SBOM, builds the container, and verifies that its runtime user is
`10001:10001`.

## Run the agent

The agent always loads `config/settings.yaml` relative to the repository or
installed application root. Before a live development run, configure reachable
development endpoints and minion IDs, set `incident_store.path` to a writable
development location, and provide credentials in `.env`.

Use dry-run mode first:

```powershell
.\.venv\Scripts\python.exe -m uyuni_ai_agent.main --dry-run
```

Dry-run prints alerts instead of delivering them. It still queries configured
dependencies and writes lifecycle state to the configured path with a dry-run
suffix, so it must not be pointed at production systems casually.

## Repository layout

| Path | Purpose |
|---|---|
| `uyuni_ai_agent/` | Runtime package |
| `uyuni_ai_agent/tools/` | Bounded tools available to LLM-assisted investigations |
| `prompts/` | System and incident-specific prompt contracts |
| `config/` | Validated runtime configuration example |
| `tests/` | Unit and contract tests |
| `evaluation/` | Scenario-based RCA quality catalog |
| `deploy/agent/` | Container host deployment assets |
| `deploy/monitoring/` | Scrape, firewall, socket proxy, and self-alert assets |
| `deploy/alertmanager/` | Alertmanager routing and notification template examples |
| `docs/` | Architecture, operations, security, development, and runbooks |

## Change workflow

### Add or change configuration

1. Update the Pydantic model in `config_schema.py`.
2. Update `config/settings.yaml` with a safe example and comments.
3. Add valid and invalid cases to `tests/test_config_schema.py`.
4. Update [Configuration](configuration.md).
5. Note compatibility-impacting changes in `CHANGELOG.md`.

Unknown keys are intentionally rejected, so renamed settings require a clear
migration rather than silently accepting a typo.

### Add an anomaly or investigation type

1. Define detection and stable identity semantics.
2. Add bounded evidence collection with explicit input validation and output
   limits.
3. Decide whether a deterministic pattern can prove the root cause.
4. Add or update the incident-specific prompt only for ambiguous cases.
5. Verify evidence freshness, citation grounding, contradiction handling, and
   safe remediation.
6. Add unit tests for detection, prompts, evidence, delivery, retries, and
   recovery.
7. Add an evaluation scenario with required and forbidden conclusions.
8. Update architecture, security, configuration, alert, and runbook docs where
   the external behavior changes.

### Add a tool

A tool is an operational capability, not just a helper function. It must:

- have a narrow diagnostic purpose;
- validate minion IDs and user-controlled arguments;
- avoid allowing the model to supply arbitrary shell or SQL text;
- bound line counts, output size, time, and concurrency;
- redact secrets, statement literals, and process arguments where applicable;
- return inspectable evidence rather than perform remediation; and
- include negative tests for malformed or adversarial inputs.

### Change alert labels or incident identity

Treat these changes as compatibility-sensitive. Alertmanager resolves alerts by
label identity, so a label change can leave the previous alert firing. Update
the alert contract, notification templates, incident lifecycle tests, changelog,
and upgrade instructions together.

## Dependencies

Runtime dependencies are declared in `requirements.txt` and deployed from the
hash-locked `requirements.lock`. Development tools are pinned in
`requirements-dev.txt`.

When dependencies change:

1. update the input requirement;
2. regenerate the complete hash-locked file using the project's approved
   dependency-locking workflow;
3. run unit tests and lint;
4. run `pip-audit --require-hashes -r requirements.lock`; and
5. build the container.

Do not hand-edit hashes in `requirements.lock`.

## Documentation expectations

Documentation follows a docs-as-code workflow. Update the document that owns
the behavior in the same pull request as the code. Commands and examples should
be safe to copy, and operational procedures should include a recovery check and
an explicit warning for unsafe actions.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the review checklist.
