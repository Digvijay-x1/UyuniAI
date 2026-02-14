FROM python:3.11-slim

WORKDIR /opt/uyuni-ai-agent

# Disable Python output buffering so prints show in podman logs
ENV PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agent code
COPY uyuni_ai_agent/ uyuni_ai_agent/
COPY prompts/ prompts/
COPY config/ config/

# LLM_API_KEY should be passed as an env variable at runtime
ENV LLM_API_KEY=""

ENTRYPOINT ["python", "-m", "uyuni_ai_agent.main"]
