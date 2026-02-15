# AI-Powered Monitoring Agent for Uyuni

This project is part of an ongoing effort to bring intelligent, automated monitoring to [Uyuni](https://www.uyuni-project.org/). The idea is straightforward: instead of manually investigating alerts, let an AI agent do the initial research -- pull metrics from Prometheus, figure out what's wrong using Salt, and report back with a root-cause analysis.

## How it works

The agent runs as a sidecar Podman container alongside the Uyuni server. Every 60 seconds it:

1. **Pulls metrics** from Prometheus (CPU, memory, disk usage via PromQL).
2. **Checks thresholds** -- if something crosses warning/critical levels, it flags it as an anomaly.
3. **Investigates** -- a LangGraph ReAct agent takes over, calling Salt commands on the affected minion (e.g., listing top processes, checking service status) and reasoning about what it finds using an LLM.
4. **Reports** -- the analysis gets sent to AlertManager, which can forward it to Slack or wherever your alerts go.

The agent communicates with Salt through Uyuni's built-in REST API (`rest_cherrypy`) on port 9080. This gives the agent full access to Salt execution modules (`cmd.run`, `disk.usage`, `service.status`, etc.) on all registered minions.


## Setup

Configuration lives in `config/settings.yaml` -- set your Prometheus URL, AlertManager URL, minion IDs, LLM provider (HuggingFace, Google Gemini, or OpenAI), and anomaly thresholds.

```bash
# Build the agent container

podman build -t uyuni-ai-agent -f Containerfile .
# Remove --dry-run to send real alerts to AlertManager
podman run -d --name ai-agent --network=container:uyuni-server -e LLM_API_KEY="your_key" -e SALT_API_PASSWORD="your_salt_password" uyuni-ai-agent --dry-run

```

We tested it in a minion and here is the [result](https://github.com/sussysimpai-blip/X-project/wiki/Current-Result-from-the-agent)
