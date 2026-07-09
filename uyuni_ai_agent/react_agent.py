import os
import logging

from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage

from uyuni_ai_agent.llm_provider import get_llm
from uyuni_ai_agent.models import RootCauseAnalysis
from uyuni_ai_agent.tools.process_tools import get_top_memory_processes, get_top_cpu_processes
from uyuni_ai_agent.tools.disk_tools import get_disk_usage, find_large_files
from uyuni_ai_agent.tools.service_tools import get_service_status, get_service_logs
from uyuni_ai_agent.tools.network_tools import check_connectivity, get_listening_ports
from uyuni_ai_agent.tools.apache_tools import (
    get_apache_status, get_apache_error_log, get_apache_access_log, get_apache_config_check,
)
from uyuni_ai_agent.tools.postgres_tools import (
    get_postgres_active_queries, get_postgres_locks,
    get_postgres_connections, get_postgres_log,
)

logger = logging.getLogger(__name__)


# All Salt inspection tools available to the agent
ALL_TOOLS = [
    # System tools
    get_top_memory_processes,
    get_top_cpu_processes,
    get_disk_usage,
    find_large_files,
    get_service_status,
    get_service_logs,
    check_connectivity,
    get_listening_ports,
    # Apache tools
    get_apache_status,
    get_apache_error_log,
    get_apache_access_log,
    get_apache_config_check,
    # PostgreSQL tools
    get_postgres_active_queries,
    get_postgres_locks,
    get_postgres_connections,
    get_postgres_log,
]


# Compiled agent cache, keyed by (provider, model). The chat-model constructor
# (e.g. ChatOpenAI) opens its own httpx client pool, and LangGraph compilation is
# non-trivial — both should happen once, not on every investigate() call (which
# fires per anomaly, per minion, per cycle). The ReAct agent is stateless across
# invocations (each ainvoke gets fresh messages), so reuse is safe.
_agent_cache = {}

# Structured-output LLM cache, keyed by (provider, model). Built from the same
# provider/model as the ReAct agent but wrapped with .with_structured_output()
# so the final formatting pass returns a validated RootCauseAnalysis instead of
# free text. Cached for the same reason as the agent: the chat-model constructor
# opens an httpx pool that should be created once, not per investigation.
_structured_llm_cache = {}


def get_structured_llm(config):
    """Return the shared LLM bound to the RootCauseAnalysis schema.

    Requires a provider/model that supports native json_schema structured
    output (see structured-output-models.md). ``with_structured_output`` makes
    the model emit JSON conforming to the Pydantic schema, which LangChain then
    parses into a RootCauseAnalysis instance.
    """
    cache_key = (config["llm"]["provider"], config["llm"]["model"])
    structured = _structured_llm_cache.get(cache_key)
    if structured is None:
        llm = get_llm(config)
        structured = llm.with_structured_output(RootCauseAnalysis)
        _structured_llm_cache[cache_key] = structured
        logger.info("Built structured-output LLM for provider=%s model=%s", *cache_key)
    return structured


def get_agent(config):
    """Return the shared, compiled ReAct agent for this provider/model.

    Builds and caches the LLM + agent graph on first use. Keyed on
    (provider, model) since the api key is resolved once at load_config() and
    does not change for the process lifetime.
    """
    cache_key = (config["llm"]["provider"], config["llm"]["model"])
    agent = _agent_cache.get(cache_key)
    if agent is None:
        llm = get_llm(config)
        agent = create_react_agent(llm, ALL_TOOLS)
        _agent_cache[cache_key] = agent
        logger.info("Compiled ReAct agent for provider=%s model=%s", *cache_key)
    return agent


def load_prompt(template_name, **kwargs):
    """Load a prompt template from the prompts/ directory and fill in variables."""
    prompts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "prompts"
    )
    template_path = os.path.join(prompts_dir, template_name)
    with open(template_path, "r") as f:
        template = f.read()
    return template.format(**kwargs)


def get_prompt_for_anomaly(anomaly, metrics):
    """Pick the right prompt template based on the anomaly type."""
    template_map = {
        "memory": "high_ram.md",
        "cpu": "high_cpu.md",
        "disk": "disk_full.md",
        "apache_busy_workers": "apache_overload.md",
        "apache_requests": "apache_overload.md",
        "postgres_connections": "postgres_issues.md",
        "postgres_deadlocks": "postgres_issues.md",
    }
    template_name = template_map.get(anomaly.metric_name, "high_ram.md")
    return load_prompt(
        template_name,
        minion_id=anomaly.minion_id,
        instance=anomaly.minion_id,
        metric_name=anomaly.metric_name,
        current_value=f"{anomaly.current_value:.1f}",
        threshold=f"{anomaly.threshold:.1f}",
        severity=anomaly.severity.value,
        metrics=str(metrics),
    )


async def investigate(anomaly, metrics, config):
    """Run the ReAct agent to investigate an anomaly, then structure the result.

    Two phases:
      1. INVESTIGATE -- the ReAct agent calls Salt tools and reasons about the
         root cause, producing free-form text.
      2. STRUCTURE   -- a second LLM pass (with_structured_output) converts that
         reasoning into a validated RootCauseAnalysis so AlertManager receives
         stable, machine-readable fields instead of one text blob.

    Args:
        anomaly: an Anomaly dataclass from anomaly_detector
        metrics: dict of current Prometheus metrics
        config: the loaded settings dict (passed to get_llm)

    Returns:
        RootCauseAnalysis: the validated, structured analysis.
    """
    # Reuse the compiled agent + LLM client (built once, cached) instead of
    # reconstructing both on every call. Only the messages vary per anomaly.
    agent = get_agent(config)

    # Load system prompt
    system_prompt = load_prompt("system_prompt.md")

    # Load scenario-specific prompt
    scenario_prompt = get_prompt_for_anomaly(anomaly, metrics)

    # Phase 1: run the ReAct agent (async; async tools are awaited by the tool node)
    result = await agent.ainvoke({
        "messages": [
            SystemMessage(content=system_prompt),
            ("human", scenario_prompt),
        ]
    })

    reasoning = _extract_text(result["messages"][-1])

    # Phase 2: structure the free-form reasoning into RootCauseAnalysis.
    structured_llm = get_structured_llm(config)
    structuring_prompt = (
        "Convert the following investigation into the required structured "
        "analysis. Use ONLY the information present in the investigation; do "
        "not invent evidence. If a field cannot be determined, use a clearly "
        "conservative value (e.g. affected_component='unknown', low "
        "confidence).\n\n"
        f"ANOMALY: {anomaly.description} "
        f"(metric={anomaly.metric_name}, value={anomaly.current_value:.1f}, "
        f"threshold={anomaly.threshold:.1f}, severity={anomaly.severity.value}, "
        f"minion={anomaly.minion_id})\n\n"
        f"INVESTIGATION:\n{reasoning}"
    )
    analysis = await structured_llm.ainvoke([
        SystemMessage(
            content=(
                "You format a completed system-administration investigation "
                "into a structured root-cause analysis."
            )
        ),
        ("human", structuring_prompt),
    ])
    return analysis


def _extract_text(final_message):
    """Extract readable text from a LangChain message's ``content``.

    LLMs may return content as a string or a list of blocks. Block shapes vary
    by provider: {"type": "text", "text": ...}, plain strings, AIMessageChunk
    objects, or tool-use blocks (which carry no readable text). We extract every
    readable fragment and warn if the result is empty so the structuring pass is
    never fed a blank investigation.
    """
    content = final_message.content

    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict):
                # {"type": "text", "text": "..."} or {"text": "..."}
                if block.get("type") == "text" and "text" in block:
                    text_parts.append(block["text"])
                elif "text" in block:
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    logger.debug("Skipping tool_use block in final message")
                else:
                    logger.warning("Unrecognized content block shape: %r", block)
            else:
                # Objects with a .content attribute (e.g. AIMessageChunk); fall
                # back to str() so we never silently drop something readable.
                logger.debug("Non-dict/str content block of type %s", type(block).__name__)
                text_parts.append(str(block))
        text = "\n".join(text_parts).strip()
        if not text:
            logger.warning("LLM returned no readable text content; blocks: %r", content)
        return text

    if isinstance(content, str):
        return content.strip()

    # Unexpected scalar type (bytes, None, etc.)
    logger.warning("Unexpected content type %s: %r", type(content).__name__, content)
    return str(content)
