# AI-Powered Intelligent Monitoring & Root Cause Analysis for Uyuni

An AI monitoring agent that runs inside the Uyuni Podman container, continuously queries Prometheus metrics, detects anomalies, triggers Salt-based inspections via a LangGraph ReAct agent, and delivers enriched alerts through AlertManager to Slack.

## Pipeline

```
INGESTION --> DETECTION --> INTELLIGENCE --> ACTION
Prometheus     Thresholds    LangGraph        AlertManager
PromQL         CPU/RAM/Disk  ReAct Agent      --> Slack
                             Salt inspections
                             LLM analysis
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your LLM API key
export LLM_API_KEY="your_api_key_here"

# Run the agent (dry run mode -- prints alerts, does not send)
python -m uyuni_ai_agent.main --dry-run

# Run the agent (production -- sends alerts to AlertManager)
python -m uyuni_ai_agent.main
```

## Configuration

Edit `config/settings.yaml` to set:
- Prometheus and AlertManager URLs
- Minion IDs and instance labels
- Anomaly thresholds (warning/critical for CPU, memory, disk)
- LLM provider (`huggingface`, `google_genai`, or `openai`) and model
- Polling interval

## Project Structure

```
X-project/
├── uyuni_ai_agent/
│   ├── main.py                  # Orchestrator: polling loop
│   ├── config.py                # YAML config loader
│   ├── prometheus_client.py     # Prometheus PromQL queries
│   ├── anomaly_detector.py      # Threshold-based detection
│   ├── llm_provider.py          # Configurable LLM (HF/Gemini/OpenAI)
│   ├── react_agent.py           # LangGraph ReAct agent
│   ├── alert_manager.py         # AlertManager integration
│   └── tools/                   # Salt inspection tools
│       ├── process_tools.py
│       ├── disk_tools.py
│       ├── service_tools.py
│       └── network_tools.py
├── prompts/                     # Prompt templates per scenario
├── config/
│   └── settings.yaml
└── requirements.txt
```
