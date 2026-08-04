# AI-Powered Monitoring Agent for Uyuni

This project provides evidence-driven incident investigation for
[Uyuni](https://www.uyuni-project.org/). It detects anomalous telemetry in
Prometheus, collects bounded diagnostic evidence through Salt, and reports a
structured root-cause analysis.

<img width="1147" height="712" alt="image" src="https://github.com/user-attachments/assets/d67caca9-f297-4109-830c-58156293ef01" />



## How it works

The agent runs as a separate Podman container on the Uyuni server's managed
`uyuni` bridge. Every 60 seconds it:

1. **Pulls metrics** from Prometheus (CPU, available memory, swap occupancy
   and page activity, and every writable persistent filesystem via PromQL).
2. **Discovers anomalies** -- it checks metric thresholds and asks systemd for
   every failed or automatically restarting service on each Uyuni minion.
   Newly installed services are covered automatically; no per-service
   inventory is required.
3. **Investigates** -- a LangGraph ReAct agent takes over, calling bounded,
   read-only Salt tools on the affected minion. For a failed service it
   correlates unit properties, journal errors, and listening sockets so it can
   distinguish a port conflict from merely seeing that the unit is inactive.
   For disk incidents it deterministically gathers capacity, largest files,
   systemd unit references, unit properties, and journals before asking the
   LLM for an RCA. For PostgreSQL it runs a fixed read-only cluster query,
   discovers blocked and blocking sessions across every database, and proves
   server availability before distinguishing lock contention from an outage.
   PostgreSQL evidence includes command types and query IDs, not raw SQL text,
   so statement literals are not sent to the external LLM or alert receivers.
   Memory investigations deterministically correlate `MemAvailable`, current
   page-in/page-out rates, system CPU/I/O wait, pressure stalls, and the
   largest-RSS process. Swap occupancy alone is not labeled as active
   thrashing, and process arguments are omitted from LLM evidence.
4. **Reports** -- the analysis is sent to Alertmanager for routing to configured
   notification receivers.
   Incident state is stored in SQLite, so agent restarts do not repeat every
   active alert. After two healthy observations, the agent sends an explicit
   Alertmanager resolution with the exact label identity of the firing alert.
   Investigations run through a bounded priority queue: duplicate incidents
   are coalesced, critical work can displace lower-priority pending work, and
   overload never acknowledges an incident that was not actually processed.

The agent communicates with Salt through Uyuni's built-in REST API
(`rest_cherrypy`) on port 9080. The Salt external-auth account needs access to
the inspection functions used by the agent (`cmd.run`, `disk.usage`, and
`service.status`). Keep that account read-only at the application level: the
service discovery commands are fixed in code, unit names are validated, and
the LLM is not allowed to choose arbitrary commands for this workflow.

`service_monitoring.ignored_units` in `config/settings.yaml` is an optional
glob-based escape hatch for deliberately failed units. The normal case needs
no list:

```yaml
service_monitoring:
  enabled: true
  ignored_units: []

deduplication:
  cooldown_seconds: 900

incident_store:
  path: /var/lib/uyuni-ai-agent/incidents.db
  resolve_after_healthy_cycles: 2

investigation_queue:
  max_pending: 50
  workers: 3
  max_job_age_seconds: 300
  shutdown_grace_seconds: 30

observability:
  enabled: true
  host: 0.0.0.0
  port: 9898
  readiness_max_age_seconds: 180
```

The observability listener exposes three read-only endpoints inside the agent
container. Production Quadlet publishes it only to host loopback on port
19898; a source-restricted systemd socket proxy exposes port 9898 only to the
monitoring host:

- `/healthz` reports that the agent process and listener are alive.
- `/readyz` returns HTTP 200 only after at least one recent, complete minion
  snapshot and successful Salt and Prometheus dependency checks; it returns
  503 when no usable snapshot is available or a required dependency is down.
- `/metrics` exposes Prometheus-format queue depth and events, poll and
  investigation latency, incident counts, anomaly observations, delivery
  outcomes, and Python process metrics.

These metrics intentionally exclude prompts, evidence text, commands, SQL,
credentials, incident IDs, and resource names. Verify the loopback-only
backend on the Uyuni host with
`curl -fsS http://127.0.0.1:19898/metrics`.
The production scrape and alert fragments are under `deploy/monitoring/`;
expose the port only through a source-restricted proxy or private network.

Dependency failures no longer terminate the process. Salt login is retried
with bounded exponential backoff and jitter, while independent circuits for
Salt, Prometheus, the LLM, and Alertmanager prevent retry storms. Per-operation,
per-minion, poll-cycle, LLM, and investigation deadlines keep one slow system
from monopolizing the agent. Endpoint-only overrides (`SALT_API_URL`,
`PROMETHEUS_URL`, and `ALERTMANAGER_URL`) allow one immutable image to be used
across environments without putting credentials in the image.

An RCA is emitted only when fresh evidence supports its cited claims. Strict
evidence patterns for port conflicts, disk-filling crash loops, blocked
PostgreSQL transactions, and active swap pressure use deterministic analysis;
ambiguous cases still use the configured OpenAI-compatible model and are
downgraded to an inconclusive result when evidence is stale, contradictory, or
insufficient.

## Setup

Configuration lives in `config/settings.yaml` -- set your Prometheus URL,
AlertManager URL, exact FQDN Salt minion IDs, OpenAI-compatible LLM endpoint,
and anomaly thresholds. Uyuni, its managed clients, Prometheus, and
Alertmanager are external prerequisites; this repository does not provision
those systems.

```bash
# Build the agent container

podman build --format=docker \
  -t localhost/uyuni-ai-agent:production -f Containerfile .
sudo install -m 0644 deploy/agent/uyuni-ai-agent.container \
  /etc/containers/systemd/uyuni-ai-agent.container
sudo systemctl daemon-reload
sudo systemctl enable --now uyuni-ai-agent.service

# On the Uyuni host, expose agent metrics only to your monitoring server.
sudo deploy/agent/install-metrics-proxy.sh MONITORING_SERVER_IP

# On the monitoring server, add the agent scrape job and self-alert rules.
sudo deploy/monitoring/install-agent-monitoring.sh UYUNI_HOSTNAME_OR_IP

```

The image runs as UID/GID 10001, and the Quadlet uses a named volume for the
non-root SQLite state store. Its checked-in definition stays in `--dry-run`
until detection, investigation, and the Alertmanager route have been verified.
Use `deploy/agent/sync-agent-salt-secret.sh` to install Uyuni's root-only
internal Salt API credential into the agent environment without printing or
committing it. See
[Operations](docs/operations.md) and
[Evaluation](docs/evaluation.md) for health checks, upgrades, rollback, and the
scored scenario catalog.


## License

Copyright 2026 Digvijay Rawat

Licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file for the full text.
