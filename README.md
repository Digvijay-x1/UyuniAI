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
```

## Setup

Configuration lives in `config/settings.yaml` -- set your Prometheus URL, AlertManager URL, minion IDs, LLM provider (HuggingFace, Google Gemini, or OpenAI), and anomaly thresholds.

```bash
# Build the agent container

podman build -t uyuni-ai-agent -f Containerfile .
# Remove --dry-run to send real alerts to AlertManager; also, the project assumes that you have a "agent" name in the config of salt-api and you are putting its password
podman run -d --name ai-agent --network=container:uyuni-server -e LLM_API_KEY="your_key" -e SALT_API_PASSWORD="your_salt_password" uyuni-ai-agent --dry-run

```


## License

Copyright 2026 Digvijay Rawat

Licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file for the full text.
