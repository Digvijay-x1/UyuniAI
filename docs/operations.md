# Operations

## Runtime contract

The agent runs as a non-root Podman container on the Uyuni-managed `uyuni`
network. It reads telemetry from Prometheus, calls Uyuni's Salt REST API, sends
incidents to Alertmanager, and stores incident state in a named volume mounted
at `/var/lib/uyuni-ai-agent`.

Runtime secrets belong in a root-readable environment file and must not be
baked into the image or passed on the command line:

- `LLM_API_KEY`
- `SALT_API_PASSWORD`
- `LANGSMITH_API_KEY` when tracing is enabled

`SALT_API_URL`, `PROMETHEUS_URL`, and `ALERTMANAGER_URL` override endpoint
locations without changing the image. OpenAI-compatible deployments can set
`OPENAI_API_BASE` in the same environment file.

## Deployment

Build the image and install the supplied Quadlet on the Uyuni container host:

```bash
podman build --format=docker \
  -t localhost/uyuni-ai-agent:production -f Containerfile .

install -m 0644 deploy/agent/uyuni-ai-agent.container \
  /etc/containers/systemd/uyuni-ai-agent.container
deploy/agent/sync-agent-salt-secret.sh

systemctl daemon-reload
systemctl enable --now uyuni-ai-agent.service
```

The checked-in Quadlet starts in dry-run mode. Remove `Exec=--dry-run` from the
installed unit only after Alertmanager routing and RCA quality have been
validated. If the repository is not located at `/root/UyuniAI`, update the
`EnvironmentFile` and configuration `Volume` paths in the installed Quadlet.

## Health checks

The Quadlet publishes the agent's observability endpoint only on host loopback:

```bash
curl -fsS http://127.0.0.1:19898/healthz
curl -fsS http://127.0.0.1:19898/readyz
curl -fsS http://127.0.0.1:19898/metrics
systemctl status uyuni-ai-agent.service --no-pager
podman logs --since 10m ai-agent
```

`healthz` confirms that the process and observability listener are alive.
`readyz` additionally requires a recent complete minion poll and usable Salt
and Prometheus dependencies. One unreachable minion does not invalidate fresh
snapshots collected from other minions.

Accept a deployment when:

1. the container health check passes;
2. `readyz` returns HTTP 200 after a poll;
3. every configured minion has completed a poll;
4. the investigation queue is stable and below capacity;
5. dependency circuits are closed; and
6. dry-run output cites current evidence for the identified component.

## Protected Prometheus scrape

Port 9898 must not be exposed without a network restriction. Install the
socket-activated proxy on the Uyuni host with the monitoring server's IPv4
address:

```bash
deploy/agent/install-metrics-proxy.sh MONITORING_SERVER_IP
```

On the Prometheus host, install the scrape job and self-monitoring rules with
the Uyuni host name or address:

```bash
deploy/monitoring/install-agent-monitoring.sh UYUNI_HOSTNAME_OR_IP
```

Both installers validate their inputs and generated configuration. The
Prometheus installer keeps a timestamped rollback copy and restores it if the
reload fails. Confirm `up{job="uyuni-ai-agent"} == 1` after installation.

## Dependency failure test

Dependency recovery can be checked with a candidate environment file that
temporarily points `SALT_API_URL` at an unreachable endpoint. During the test,
`healthz` remains available, `readyz` becomes unavailable, and the Salt circuit
opens without causing a process restart loop. Restore the endpoint and verify
that readiness returns after Salt login and a successful minion poll.

Do not run this test against the active production environment file.

## Upgrade and rollback

Retain the previous image before replacing the `production` tag. After loading
the new image, restart `uyuni-ai-agent.service` and repeat the health checks.
The named volume preserves incident identity across container replacement.

For rollback, restore the previous image tag and restart the unit. Do not
delete or recreate the state volume during routine rollback. Back up the
SQLite database before deploying a release that changes its schema.

## Agent incident response

- `healthz` unavailable: inspect the container state and earliest exception.
- `healthz` available but `readyz` unavailable: inspect dependency and
  last-poll metrics.
- queue saturation: restore the slow dependency or reduce incoming incident
  fan-out; do not remove the queue bound.
- Alertmanager delivery failures: retain the incident as unacknowledged so a
  later poll can retry delivery.
- stale or contradictory evidence: keep the RCA inconclusive and repair the
  telemetry source before acting.
