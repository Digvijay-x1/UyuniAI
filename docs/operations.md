# Operations

## Runtime contract

The agent is a non-root sidecar in the `uyuni-server` network namespace. It
reads Prometheus over HTTP, reaches Uyuni's Salt API at `localhost:9080`, calls
the configured OpenAI-compatible LLM API, and writes only its SQLite incident
state under `/var/lib/uyuni-ai-agent`.

Required secrets are supplied at runtime:

- `LLM_API_KEY`
- `SALT_API_PASSWORD`
- `LANGSMITH_API_KEY` only when tracing is deliberately enabled

Do not bake `.env` into the image or pass secret values directly on the command
line. Restrict the env file to the account that manages Podman.

The supported endpoint overrides are `SALT_API_URL`, `PROMETHEUS_URL`, and
`ALERTMANAGER_URL`. They change destinations, not credentials, and are useful
for recovery tests and promoting the same image between environments.

## Deployment

Build and retain a uniquely tagged image before replacing the container:

```bash
podman build --format=docker -t localhost/ai-agent:2026-08-production -f Containerfile .
podman volume create uyuni-ai-agent-state
podman run -d --name ai-agent-candidate \
  --network=container:uyuni-server \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=all --security-opt=no-new-privileges \
  --pids-limit=256 --memory=1g --cpus=2 \
  -v uyuni-ai-agent-state:/var/lib/uyuni-ai-agent:U \
  --env-file /root/UyuniAI/.env \
  localhost/ai-agent:2026-08-production --dry-run
```

Only one agent can bind port 9898 in the shared network namespace, so stop the
old container immediately before starting the candidate. Do not remove the old
container or image until the candidate passes the checks below.

## Health and acceptance checks

```bash
podman exec uyuni-server curl -fsS http://127.0.0.1:9898/healthz
podman exec uyuni-server curl -fsS http://127.0.0.1:9898/readyz
podman exec uyuni-server curl -fsS http://127.0.0.1:9898/metrics
podman inspect --format '{{.State.Health.Status}}' ai-agent
podman logs --since 10m ai-agent
```

`healthz` proves the event loop and metrics listener are alive. `readyz` also
requires at least one recent, complete minion snapshot and available Salt and
Prometheus dependencies. A healthy process can therefore be intentionally
unready while it retries a dependency. Other minions can be reported as
incomplete without discarding the usable snapshots from healthy minions.

Accept a release only when:

1. the container health is healthy;
2. `readyz` returns HTTP 200 after a poll;
3. both configured minions complete a poll;
4. the queue is bounded and not continually growing;
5. no unexpected dependency circuit remains open;
6. dry-run RCA output contains current evidence and the correct component.

## Protected Prometheus scrape

The listener binds inside the container network and must not be published to
the internet without a source restriction. Forward host TCP 9898 to the Uyuni
container's TCP 9898 only from the monitoring VM (`52.91.91.80/32`), or use a
private network/TLS reverse proxy. Verify the restriction from an unrelated
source before enabling the scrape.

The files under `deploy/monitoring/uyuni-ai-agent-metrics-*` provide the
current lab deployment: a socket-activated `systemd-socket-proxyd` listener and
an nftables input rule that accepts TCP 9898 only from `52.91.91.80`. The proxy
resolves the `uyuni-server` bridge address whenever it starts, so recreating the
container does not require a hard-coded address update.

Merge `deploy/monitoring/prometheus-agent-scrape.yml` into Prometheus's
`scrape_configs`, copy `deploy/monitoring/agent-self-alerts.yml` into its rule
directory, and add that file under `rule_files`. Validate before reload:

```bash
promtool check config /etc/prometheus/prometheus.yml
promtool check rules /etc/prometheus/rules/agent-self-alerts.yml
curl -fsS -X POST http://127.0.0.1:9090/-/reload
```

For the current openSUSE monitoring VM, copy both YAML fragments to `/tmp` and
run `deploy/monitoring/install-agent-monitoring.sh` as root. The installer is
idempotent, validates a candidate configuration before replacement, preserves
a timestamped backup, and restores that backup automatically if reload fails.

Confirm `up{job="uyuni-ai-agent"} == 1` and exercise `readyz` degradation before
considering self-monitoring complete.

## Dependency failure drill

Use a candidate container and an endpoint override; do not modify the image:

```bash
# Add this option to the candidate `podman run` command above:
--env SALT_API_URL=https://127.0.0.1:1
```

During the drill, `healthz` must remain 200, `readyz` must become 503, Salt's
dependency metric must become zero, and the process must retry without a crash
loop. Remove the override and replace the candidate. Readiness must recover
after Salt login and at least one complete minion snapshot.

## Rollback

Stop and rename the failed candidate, then restart the retained prior
container. The named volume preserves incident generations and alert identity.
Never delete or recreate that volume as part of routine rollback. If a schema
migration is introduced later, back up the SQLite database and document its
backward-compatibility before deployment.

## Incident response for the agent

- `healthz` down: inspect container state and the earliest exception.
- `healthz` up, `readyz` down: inspect dependency and last-poll metrics.
- queue saturation: reduce the incoming incident fan-out or restore the slow
  dependency; do not make the queue unbounded.
- Alertmanager delivery failures: preserve incidents as unacknowledged and
  restore routing; the next cycle retries them.
- stale or contradictory evidence: keep the RCA inconclusive and repair the
  telemetry source before acting on a guessed cause.
