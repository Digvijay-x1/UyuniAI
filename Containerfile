FROM python:3.11-slim@sha256:a01e48f10f90ac3ee65ef6937b9d7c831a3570c81b98d39a547ff09fb359de7f

LABEL org.opencontainers.image.title="Uyuni AI Agent" \
      org.opencontainers.image.description="Evidence-driven infrastructure incident investigator" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /opt/uyuni-ai-agent

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/var/lib/uyuni-ai-agent \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && groupadd --gid 10001 uyuni-ai-agent \
    && useradd --uid 10001 --gid 10001 \
       --home-dir /var/lib/uyuni-ai-agent --shell /usr/sbin/nologin \
       uyuni-ai-agent \
    && install -d -o 10001 -g 10001 /var/lib/uyuni-ai-agent

COPY --chown=10001:10001 uyuni_ai_agent/ uyuni_ai_agent/
COPY --chown=10001:10001 prompts/ prompts/
COPY --chown=10001:10001 config/ config/

ENV LLM_API_KEY=""
ENV LANGSMITH_TRACING="false"
ENV LANGSMITH_API_KEY=""
ENV LANGSMITH_PROJECT="New"
ENV LANGSMITH_ENDPOINT="https://api.smith.langchain.com"

USER 10001:10001

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9898/healthz', timeout=3).read()"]

ENTRYPOINT ["python", "-m", "uyuni_ai_agent.main"]
