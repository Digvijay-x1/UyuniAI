# Configuration reference

The agent loads `config/settings.yaml`, overlays selected environment values,
and validates the resulting object before opening external connections. Unknown
keys are rejected to catch misspellings and obsolete configuration.

All YAML and environment changes require a process restart. When Uyuni
inventory discovery is enabled, the client list itself refreshes at runtime.

## Precedence

From highest to lowest precedence:

1. an existing process environment variable;
2. a value loaded from the repository-root `.env` file; and
3. `config/settings.yaml`.

Only documented environment variables override YAML. `python-dotenv` does not
replace variables that are already present in the process environment.

## Environment variables

| Variable | Secret | Required | Purpose |
|---|---:|---:|---|
| `LLM_API_KEY` | Yes | Provider-dependent | Injected as `llm.api_key` |
| `SALT_API_PASSWORD` | Yes | Yes in production | Injected as `salt_api.password` |
| `UYUNI_API_PASSWORD` | Yes | With Uyuni inventory | Injected as `uyuni_api.password` |
| `PROMETHEUS_URL` | No | No | Overrides `prometheus.url` for immutable images |
| `ALERTMANAGER_URL` | No | No | Overrides `alertmanager.url` |
| `SALT_API_URL` | No | No | Overrides `salt_api.url` |
| `UYUNI_API_URL` | No | No | Overrides `uyuni_api.url` |
| `OPENAI_API_BASE` | Usually no | No | Base URL consumed by OpenAI-compatible client deployments |
| `LOG_LEVEL` | No | No | Startup log level; validated YAML logging can reconfigure it after load |
| `LANGSMITH_TRACING` | No | No | Enables LangSmith tracing when true |
| `LANGSMITH_API_KEY` | Yes | Only with tracing | LangSmith credential |
| `LANGSMITH_PROJECT` | No | No | LangSmith project name |
| `LANGSMITH_ENDPOINT` | No | No | LangSmith API endpoint |

Legacy `LANGCHAIN_*` tracing variables are accepted by the underlying LangChain
integration, but new deployments should use `LANGSMITH_*` names.

LLM investigations use LangChain's normal LangSmith tracing. Deterministic
investigations emit only an allowlisted metadata span: anomaly category,
controlled analyzer ID, evidence categories/count, conclusion, confidence,
urgency, and `llm_used=false`. Raw evidence, configuration, hosts, services,
paths, commands, fingerprints, prompts, credentials, and RCA text are never
included in that span.

Store production secrets in the root-readable environment file referenced by
the Quadlet. Do not put them in YAML, the image, shell history, command-line
arguments, or version control.

## Endpoints

| Setting | Type | Required | Default | Description |
|---|---|---:|---|---|
| `prometheus.url` | HTTP(S) URL | Yes | — | Prometheus HTTP API base URL |
| `prometheus.max_sample_age_seconds` | Number > 0 | No | `300` | Maximum accepted telemetry sample age |
| `alertmanager.url` | HTTP(S) URL | Yes | — | Alertmanager base URL; alerts are posted to `/api/v2/alerts` |
| `salt_api.url` | HTTP(S) URL | Yes | — | Uyuni Salt REST API endpoint, normally port 9080 |
| `salt_api.username` | Non-empty string | Yes | — | Dedicated Salt external-auth identity |
| `salt_api.password` | String | No | Empty | Prefer `SALT_API_PASSWORD` |
| `salt_api.eauth` | Non-empty string | No | `file` | Salt external-auth backend |
| `uyuni_api.url` | HTTP(S) URL | With Uyuni inventory | — | Uyuni Manager API base URL ending in `/rhn/manager/api` |
| `uyuni_api.username` | Non-empty string | With Uyuni inventory | — | Uyuni user allowed to list visible systems |
| `uyuni_api.password` | String | With Uyuni inventory | Empty | Prefer `UYUNI_API_PASSWORD` |
| `uyuni_api.verify_tls` | Boolean | No | `true` | Verify the Uyuni HTTPS certificate |

URLs must be absolute `http://` or `https://` URLs. Trailing slashes are
normalized away.

Production should use TLS for Salt and any dependency crossing an untrusted
network. The service does not provision certificates or network policy.

## Minion inventory

### Automatic Uyuni discovery

Production deployments can use Uyuni as the authoritative inventory:

```yaml
uyuni_api:
  url: "https://uyuni.example.com/rhn/manager/api"
  username: "uyuniai-inventory"
  password: ""  # UYUNI_API_PASSWORD
  verify_tls: true

inventory:
  provider: "uyuni"
  refresh_interval_seconds: 60
  node_exporter_port: 9100
  prometheus_jobs:
    node: ["node"]
    apache: ["apache"]
    postgres: ["postgres"]

minions: []
```

At each refresh, the agent retrieves active Uyuni systems and the Uyuni
minion-ID map. It then reads Prometheus's active targets to locate the exact
`instance` labels for the configured Node, Apache, and PostgreSQL jobs.

Uyuni is the trust boundary: Prometheus targets can add exporter endpoints to
an existing Uyuni minion, but cannot create a Salt target. The resulting Uyuni
minion IDs atomically replace the Salt command allowlist before polling starts.
If refresh fails after a successful discovery, the agent retains the last
known-good inventory. Before the first successful refresh, it sends no Salt
commands.

The Node exporter endpoint defaults to `<minion-id>:9100` when Prometheus does
not expose a matching target. This deliberately produces missing-telemetry
evidence rather than silently excluding the registered system. Optional
Apache and PostgreSQL monitoring is enabled only when a matching Prometheus
job is present.

For least privilege, use a dedicated Uyuni account that can only see the
systems the agent is intended to monitor. Keep TLS verification enabled in
production.

### Static inventory

Static inventory remains available for tests and small installations:

```yaml
minions:
  - id: "database.example.com"
    instance: "database.example.com:9100"
    postgres_instance: "database.example.com:9187"
  - id: "web.example.com"
    instance: "web.example.com:9100"
    apache_instance: "web.example.com:9117"
```

| Field | Required | Description |
|---|---:|---|
| `id` | Yes | Exact Salt minion ID used for inspection calls |
| `instance` | Yes | Prometheus node-exporter `instance` label |
| `apache_instance` | No | Apache exporter `instance`; enables Apache detection for the minion |
| `postgres_instance` | No | PostgreSQL exporter `instance`; enables PostgreSQL detection for the minion |

Minion IDs must be unique. Values are trimmed and blank strings are rejected.
Keep this inventory aligned with real Prometheus labels; a DNS name that looks
correct but does not exactly match the label will produce missing telemetry.

Static mode requires at least one minion:

```yaml
inventory:
  provider: "static"
```

## Dependency correlation

```yaml
dependency_correlation:
  grace_seconds: 90
  postgres_apache:
    - postgres_minion: "database.example.com"
      apache_minion: "web.example.com"
  edges:
    - id: "backup-ssh"
      kind: "ssh"
      source_minion: "backup.example.com"
      source_service: "nightly-backup.service"
      target_minion: "storage.example.com"
      target_host: "storage.example.com"
      port: 22
      known_hosts_file: "/etc/backup/known_hosts"
      host_public_key_file: "/etc/ssh/ssh_host_ed25519_key.pub"
```

| Setting | Default | Description |
|---|---:|---|
| `grace_seconds` | `90` | Time to retain a one-sided candidate so adjacent scrape cycles can form one incident |
| `postgres_apache` | Empty list | Explicit production traffic edges from a PostgreSQL minion to an Apache minion |
| `edges` | Empty list | Generic topology-gated SSH, TLS, or NFS inspection edges associated with an exact source systemd service |

Correlation is topology-gated. In static mode, each edge must reference a
declared minion; the PostgreSQL side must define `postgres_instance`, and the
Apache side must define `apache_instance`. Dynamic mode validates those
relationships when observations are correlated because its minions do not
exist at startup. Duplicate edges are always rejected. Do not declare a
dependency only because two alerts occurred at the same time.

Generic inspection edges use a stable `id`, protocol `kind`, exact source and
target minion IDs, and an exact source `.service`. When that service fails, the
agent automatically collects a fixed read-only snapshot from both ends. The
LLM tools accept only the configured edge ID; hostnames, ports, paths, users,
and commands cannot be supplied at tool-call time.

| Kind | Required fields | Read-only evidence |
|---|---|---|
| `ssh` | `port`, `known_hosts_file`, `host_public_key_file` | Pinned and currently presented SHA-256 host-key fingerprints |
| `tls` | `port`, `expected_hostname`, `ca_file`, `certificate_file` | Live chain/hostname verification plus server subject, issuer, validity, SAN, and fingerprint |
| `nfs` | `source_mount`, `target_export`, `expected_uid`, `expected_gid` | Mount options, export policy, and numeric ownership/identity on both nodes |

All paths must be bounded absolute POSIX paths. Static inventory validates both
minions at startup; dynamic inventory gates every inspection against the
current authenticated Uyuni allowlist. Duplicate IDs and incomplete protocol
definitions fail startup validation.

## Thresholds

Every threshold band has `warning` and `critical` values. Critical must be
greater than or equal to warning. Percentage bands must remain between 0 and
100 inclusive.

| Setting | Unit | Example warning / critical | Meaning |
|---|---|---:|---|
| `thresholds.memory` | Percent used | `70 / 95` | Base memory utilization threshold |
| `thresholds.memory.pressure.swap_activity_pages_per_second` | Pages/s | `1 / 100` | Current swap I/O activity after memory exceeds warning |
| `thresholds.memory.pressure.swap_usage_percent` | Percent | `5 / 25` | Swap occupancy context; occupancy alone does not prove thrashing |
| `thresholds.cpu` | Percent | `70 / 95` | CPU utilization |
| `thresholds.disk` | Percent | `75 / 95` | Writable persistent filesystem utilization |
| `thresholds.apache.busy_workers_percent` | Percent | `75 / 90` | Apache worker occupancy |
| `thresholds.apache.requests_per_sec` | Requests/s | `500 / 1000` | Apache traffic rate |
| `thresholds.postgres.active_connections_percent` | Percent | `75 / 90` | PostgreSQL connection-slot utilization |
| `thresholds.postgres.deadlocks_per_min` | Deadlocks/min | `1 / 5` | Deadlock rate |
| `thresholds.postgres.blocked_transaction_seconds` | Seconds | `5 / 30` | Age of persistent blocked work |

Tune thresholds from observed baselines and capacity objectives. Very low
values increase investigation volume and LLM cost; very high values delay
detection. Validate changed thresholds in dry-run and evaluation scenarios.

## LLM

| Setting | Type | Required | Description |
|---|---|---:|---|
| `llm.provider` | Enum | Yes | `openai`, `google_genai`, `huggingface`, or `tokenrouter` |
| `llm.model` | Non-empty string | Yes | Provider-specific model identifier |
| `llm.api_key` | String | No in YAML | Populated from `LLM_API_KEY` when set |
| `llm.requests_per_minute` | Positive number | No | Optional process-wide request limiter shared by ReAct and structured-output calls |

The configured model must support the structured output behavior required by
the runtime. Verify model compatibility with the evaluation catalog before
enabling delivery. Changing models is a production behavior change even when
the configuration schema is unchanged.

## Polling and monitoring features

| Setting | Type | Default/example | Description |
|---|---|---:|---|
| `polling.interval_seconds` | Integer > 0 | `60` | Delay between completed poll cycles |
| `service_monitoring.enabled` | Boolean | `true` | Discover failed and restarting systemd units |
| `service_monitoring.ignored_units` | String list | `[]` | Glob patterns for intentionally failed or masked units |
| `postgres_lock_monitoring.enabled` | Boolean | `true` | Inspect blockers on minions with `postgres_instance` |
| `deduplication.cooldown_seconds` | Integer >= 0 | `900` | Re-investigation interval for a continuously active incident |

Ignored service patterns are an escape hatch, not a replacement for repairing
unexpected failed units. Review them periodically.

## Incident store

| Setting | Type | Default | Description |
|---|---|---:|---|
| `incident_store.path` | Non-empty path | `/var/lib/uyuni-ai-agent/incidents.db` | SQLite lifecycle database |
| `incident_store.resolve_after_healthy_cycles` | Integer >= 1 | `2` | Consecutive absent observations required before resolution |

The production path must be on the persistent named volume. Dry-run mode uses a
separate suffix so evaluation does not suppress production alerts. Back up the
database before a schema-changing release; do not place it on ephemeral
container storage.

## Investigation queue

| Setting | Type | Default | Description |
|---|---|---:|---|
| `investigation_queue.max_pending` | Integer >= 1 | `50` | Maximum waiting investigations |
| `investigation_queue.workers` | Integer >= 1 | `3` | Concurrent queue consumers |
| `investigation_queue.max_job_age_seconds` | Number > 0 | `300` | Maximum age of a queued snapshot |
| `investigation_queue.shutdown_grace_seconds` | Number >= 0 | `30` | Time allowed for work to drain during shutdown |

Increasing workers can raise Salt and LLM pressure, but the separate
concurrency semaphores still apply. Keep `max_job_age_seconds` no greater than
the period for which the evidence would still be operationally trustworthy.

## Observability

| Setting | Type | Default | Description |
|---|---|---:|---|
| `observability.enabled` | Boolean | `true` | Serve health, readiness, and metrics |
| `observability.host` | Non-empty string | `127.0.0.1` in schema; `0.0.0.0` in container example | Listener address |
| `observability.port` | Port 1–65535 | `9898` | Container listener port |
| `observability.readiness_max_age_seconds` | Number > 0 | `180` | Maximum age of the last usable poll |

The container example listens on all container interfaces so Podman can publish
it to host loopback. Do not publish port 9898 broadly. Use the source-restricted
proxy documented in [Operations](operations.md).

## Resilience

| Setting | Type | Default | Description |
|---|---|---:|---|
| `resilience.failure_threshold` | Integer >= 1 | `3` | Consecutive failures before a dependency circuit opens |
| `resilience.recovery_timeout_seconds` | Number > 0 | `30` | Open-circuit delay before a recovery probe |
| `resilience.initial_backoff_seconds` | Number > 0 | `1` | Initial Salt login retry delay |
| `resilience.maximum_backoff_seconds` | Number > 0 | `60` | Maximum Salt login retry delay |
| `resilience.jitter_ratio` | Number 0–1 | `0.2` | Random retry-delay variation |
| `resilience.salt_login_timeout_seconds` | Number > 0 | `20` | Salt authentication deadline |

Maximum backoff must be greater than or equal to initial backoff. Avoid setting
failure thresholds so low that a single network fluctuation opens circuits, or
so high that a failing dependency receives sustained traffic.

## Timeouts

| Setting | Default | Scope |
|---|---:|---|
| `timeouts.salt_operation_seconds` | `70` | One Salt operation |
| `timeouts.prometheus_operation_seconds` | `30` | One Prometheus operation |
| `timeouts.minion_seconds` | `90` | One minion's poll work |
| `timeouts.poll_cycle_seconds` | `180` | Whole poll cycle |
| `timeouts.llm_seconds` | `240` | LLM work within an investigation |
| `timeouts.investigation_seconds` | `300` | Whole queued investigation |
| `timeouts.alertmanager_seconds` | `30` | Alertmanager delivery operation |

Every value must be positive. `poll_cycle_seconds` must be at least
`minion_seconds`, and `investigation_seconds` must be at least `llm_seconds`.
Timeouts should be shorter than the operational period in which the evidence
remains useful.

## Quality gates

| Setting | Type | Default | Description |
|---|---|---:|---|
| `quality_gates.max_evidence_age_seconds` | Number > 0 | `300` | Oldest evidence allowed to support a confirmed RCA |
| `quality_gates.minimum_supporting_records` | Integer 1–10 | `1` | Minimum cited records for confirmation |
| `quality_gates.deterministic_analysis_enabled` | Boolean | `true` | Permit fixed proven patterns to bypass the LLM |

Raising the minimum record count can reduce false confirmation but may make
simple, directly proven incidents inconclusive. Validate changes against all
evaluation scenarios.

## Concurrency

| Setting | Type | Example | Description |
|---|---|---:|---|
| `concurrency.max_minions` | Integer > 0 | `8` | Minions processed concurrently in a cycle |
| `concurrency.max_salt_calls` | Integer > 0 | `8` | Global Salt call limit |
| `concurrency.max_llm_calls` | Integer > 0 | `5` | Global LLM investigation limit |

Set these from measured Salt, model, CPU, memory, and network capacity. Raising
them can reduce backlog while increasing dependency pressure and cost.

## Logging

| Setting | Allowed values | Default |
|---|---|---:|
| `logging.level` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG` | `INFO` |

Values are normalized to uppercase. Do not enable debug logging permanently in
production without reviewing emitted fields and retention policy.

## Validation checklist

Before enabling real delivery:

1. start the container with `--dry-run`;
2. confirm every minion ID and Prometheus instance label;
3. confirm Salt inspection is read-only and appropriately authorized;
4. verify `/healthz`, `/readyz`, and `/metrics` exposure;
5. verify queue and timeout values against the polling interval;
6. exercise at least one evaluation scenario per enabled incident family; and
7. verify firing and resolved routing in Alertmanager.
