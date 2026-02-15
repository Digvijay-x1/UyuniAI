# AI-Powered Monitoring Agent for Uyuni

This project is part of an ongoing effort to bring intelligent, automated monitoring to [Uyuni](https://www.uyuni-project.org/). The idea is straightforward: instead of manually investigating alerts, let an AI agent do the initial triage -- pull metrics from Prometheus, figure out what's wrong using Salt, and report back with a root-cause analysis.

## How it works

The agent runs as a sidecar Podman container alongside the Uyuni server. Every 60 seconds it:

1. **Pulls metrics** from Prometheus (CPU, memory, disk usage via PromQL).
2. **Checks thresholds** -- if something crosses warning/critical levels, it flags it as an anomaly.
3. **Investigates** -- a LangGraph ReAct agent takes over, calling Salt commands on the affected minion (e.g. listing top processes, checking service status) and reasoning about what it finds using an LLM.
4. **Reports** -- the analysis gets sent to AlertManager, which can forward it to Slack or wherever your alerts go.

A separate Flask server (`tools_server.py`) runs inside the Uyuni container to give the agent access to Salt's LocalClient over HTTP. This avoids the Salt API auth complexity and works with the container's Python 3.6.


## Setup

Configuration lives in `config/settings.yaml` -- set your Prometheus URL, AlertManager URL, minion IDs, LLM provider (HuggingFace, Google Gemini, or OpenAI), and anomaly thresholds.

```bash
# On the Uyuni host (Master):

# 1. Start the tools server inside the Uyuni container
podman cp tools_server.py uyuni-server:/opt/tools_server.py
mgrctl term
# inside the uyuni server container
python3 /opt/tools_server.py

# 2. Build and run the agent
podman build -t uyuni-ai-agent -f Containerfile .
podman run -d --name ai-agent \
  --network=container:uyuni-server \
  -e LLM_API_KEY="your_key" \
  uyuni-ai-agent --dry-run
```

