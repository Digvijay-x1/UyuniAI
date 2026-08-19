# Agent target down

**Alert:** `UyuniAIAgentTargetDown`

## Symptoms

Prometheus cannot scrape `uyuni-ai-agent` for at least two minutes. The alert
does not distinguish a stopped container from a blocked metrics proxy.

## Impact

Agent self-monitoring is unavailable. New incident detection and delivery may
also be stopped, but this must be verified separately.

## Checks

Run on the Uyuni host:

```bash
systemctl status uyuni-ai-agent.service --no-pager
podman ps --filter name=ai-agent
podman logs --since 15m ai-agent
curl -fsS http://127.0.0.1:19898/healthz
```

If loopback works, check the proxy and firewall:

```bash
systemctl status uyuni-ai-agent-metrics-proxy.socket --no-pager
systemctl status uyuni-ai-agent-metrics-firewall.service --no-pager
ss -ltn | grep 9898
```

Run from the monitoring host:

```bash
curl -fsS http://UYUNI_HOSTNAME_OR_IP:9898/metrics
```

## Safe actions

- If the container is stopped and logs show no active incident, restart the
  systemd unit once:

  ```bash
  systemctl restart uyuni-ai-agent.service
  ```

- If loopback is healthy but remote scraping fails, repair the source-restricted
  proxy or firewall configuration using the supplied installer.

## Recovery verification

Confirm `/healthz` succeeds locally, Prometheus reports
`up{job="uyuni-ai-agent"} == 1`, and the target-down alert resolves.

## Escalate when

The container repeatedly exits, the image cannot start, the host volume is
unavailable, or the proxy is reachable from an unauthorized source.

## Do not

Do not delete the state volume or SQLite database as a first recovery action.
