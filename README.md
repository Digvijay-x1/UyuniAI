# AI-Powered Monitoring Agent for Uyuni

This project is part of an ongoing effort to bring intelligent, automated monitoring to [Uyuni](https://www.uyuni-project.org/). The idea is straightforward: instead of manually investigating alerts, let an AI agent do the initial research -- pull metrics from Prometheus, figure out what's wrong using Salt, and report back with a root-cause analysis.

<img width="1147" height="712" alt="image" src="https://github.com/user-attachments/assets/d67caca9-f297-4109-830c-58156293ef01" />



## How it works

The agent runs as a sidecar Podman container alongside the Uyuni server. Every 60 seconds it:

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
4. **Reports** -- the analysis gets sent to AlertManager, which can forward it to Slack or wherever your alerts go.
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

The observability listener exposes three read-only endpoints inside the Uyuni
server container's network namespace. Port 9898 is not published by the
sidecar deployment command:

- `/healthz` reports that the agent process and listener are alive.
- `/readyz` returns HTTP 200 only after at least one recent, complete minion
  snapshot and successful Salt and Prometheus dependency checks; it returns
  503 when no usable snapshot is available or a required dependency is down.
- `/metrics` exposes Prometheus-format queue depth and events, poll and
  investigation latency, incident counts, anomaly observations, delivery
  outcomes, and Python process metrics.

These metrics intentionally exclude prompts, evidence text, commands, SQL,
credentials, incident IDs, and resource names. With the sidecar network,
verify them locally with
`podman exec uyuni-server curl -fsS http://127.0.0.1:9898/metrics`.
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

Configuration lives in `config/settings.yaml` -- set your Prometheus URL, AlertManager URL, minion IDs, LLM provider (HuggingFace, Google Gemini, or OpenAI), and anomaly thresholds.

```bash
# Build the agent container

podman build --format=docker -t uyuni-ai-agent -f Containerfile .
# Remove --dry-run to send real alerts to AlertManager; also, the project assumes that you have a "agent" name in the config of salt-api and you are putting its password
podman volume create uyuni-ai-agent-state
podman run -d --name ai-agent --network=container:uyuni-server \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=all --security-opt=no-new-privileges \
  --pids-limit=256 --memory=1g --cpus=2 \
  -v uyuni-ai-agent-state:/var/lib/uyuni-ai-agent:U \
  --env-file /root/UyuniAI/.env \
  uyuni-ai-agent --dry-run

```

The image runs as UID/GID 10001. The `:U` volume option performs the one-time
ownership adjustment needed by the non-root SQLite state store. Keep
`--dry-run` until the complete detection, investigation, and Alertmanager route
have been verified. See [Operations](docs/operations.md) and
[Evaluation](docs/evaluation.md) for health checks, upgrades, rollback, and the
scored scenario catalog.


## License

Copyright 2026 Digvijay Rawat

Licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file for the full text.
