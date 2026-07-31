# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import os
import logging

from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage

from uyuni_ai_agent.llm_provider import get_llm
from uyuni_ai_agent.models import RootCauseAnalysis
from uyuni_ai_agent import salt_api
from uyuni_ai_agent.disk_inspection import parse_service_unit_references
from uyuni_ai_agent.tools.process_tools import (
    get_cpu_pressure_snapshot,
    get_memory_pressure_snapshot,
    get_top_cpu_processes,
    get_top_memory_processes,
)
from uyuni_ai_agent.tools.disk_tools import (
    find_large_files,
    find_service_references,
    get_disk_usage,
)
from uyuni_ai_agent.tools.service_tools import (
    get_service_details,
    get_service_logs,
    get_service_status,
)
from uyuni_ai_agent.tools.network_tools import check_connectivity, get_listening_ports
from uyuni_ai_agent.tools.apache_tools import (
    get_apache_overload_snapshot,
    get_apache_status,
    get_apache_error_log,
    get_apache_access_log,
    get_apache_config_check,
)
from uyuni_ai_agent.tools.postgres_tools import (
    get_postgres_active_queries, get_postgres_locks,
    get_postgres_connections, get_postgres_health, get_postgres_log,
)

logger = logging.getLogger(__name__)


# All Salt inspection tools available to the agent
ALL_TOOLS = [
    # System tools
    get_top_memory_processes,
    get_top_cpu_processes,
    get_memory_pressure_snapshot,
    get_cpu_pressure_snapshot,
    get_disk_usage,
    find_large_files,
    find_service_references,
    get_service_status,
    get_service_details,
    get_service_logs,
    check_connectivity,
    get_listening_ports,
    # Apache tools
    get_apache_overload_snapshot,
    get_apache_status,
    get_apache_error_log,
    get_apache_access_log,
    get_apache_config_check,
    # PostgreSQL tools
    get_postgres_active_queries,
    get_postgres_locks,
    get_postgres_health,
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
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    return template.format(**kwargs)


def get_prompt_for_anomaly(anomaly, metrics):
    """Pick the right prompt template based on the anomaly type."""
    template_map = {
        "memory": "high_ram.md",
        "memory_pressure": "high_ram.md",
        "cpu": "high_cpu.md",
        "disk": "disk_full.md",
        "apache_busy_workers": "apache_overload.md",
        "apache_requests": "apache_overload.md",
        "postgres_connections": "postgres_connection_exhaustion.md",
        "postgres_deadlocks": "postgres_issues.md",
        "postgres_blocked_transaction": "postgres_blocked_transaction.md",
        "postgres_apache_chain": "postgres_apache_chain.md",
        "service_down": "service_down.md",
    }
    template_name = template_map.get(anomaly.metric_name, "high_ram.md")
    if anomaly.metric_name in {"memory", "memory_pressure"}:
        return load_prompt(
            template_name,
            minion_id=anomaly.minion_id,
            instance=anomaly.minion_id,
            current_value=f"{anomaly.current_value:.1f}",
            threshold=f"{anomaly.threshold:.1f}",
            severity=anomaly.severity.value,
            memory_available_bytes=f"{anomaly.context.get('memory_available_bytes', 0):.0f}",
            memory_total_bytes=f"{anomaly.context.get('memory_total_bytes', 0):.0f}",
            swap_used_bytes=f"{anomaly.context.get('swap_used_bytes', 0):.0f}",
            swap_total_bytes=f"{anomaly.context.get('swap_total_bytes', 0):.0f}",
            swap_usage_percent=f"{anomaly.context.get('swap_usage_percent', 0):.1f}",
            swap_in_pages_per_second=f"{anomaly.context.get('swap_in_pages_per_second', 0):.1f}",
            swap_out_pages_per_second=f"{anomaly.context.get('swap_out_pages_per_second', 0):.1f}",
            system_cpu_percent=f"{anomaly.context.get('system_cpu_percent', 0):.1f}",
            iowait_cpu_percent=f"{anomaly.context.get('iowait_cpu_percent', 0):.1f}",
            cpu_usage_percent=f"{anomaly.context.get('cpu_usage_percent', metrics.get('cpu_percent', 0)):.1f}",
            metrics=str(metrics),
        )
    if anomaly.metric_name == "service_down":
        return load_prompt(
            template_name,
            minion_id=anomaly.minion_id,
            instance=anomaly.minion_id,
            service_name=anomaly.service_name or "unknown.service",
            severity=anomaly.severity.value,
            metrics=str(metrics),
        )
    if anomaly.metric_name == "disk":
        return load_prompt(
            template_name,
            minion_id=anomaly.minion_id,
            instance=anomaly.minion_id,
            mountpoint=anomaly.context.get("mountpoint", anomaly.resource or "/"),
            device=anomaly.context.get("device", "unknown"),
            related_services=", ".join(
                anomaly.context.get("related_unhealthy_services", [])
            ) or "none discovered",
            current_value=f"{anomaly.current_value:.1f}",
            threshold=f"{anomaly.threshold:.1f}",
            severity=anomaly.severity.value,
            metrics=str(metrics),
        )
    if anomaly.metric_name == "postgres_blocked_transaction":
        return load_prompt(
            template_name,
            minion_id=anomaly.minion_id,
            instance=anomaly.minion_id,
            database=anomaly.context.get("database", "unknown"),
            blocked_pids=", ".join(
                str(pid) for pid in anomaly.context.get("blocked_pids", [])
            ) or "unknown",
            blocker_pids=", ".join(
                str(pid) for pid in anomaly.context.get("blocker_pids", [])
            ) or "unknown",
            current_value=f"{anomaly.current_value:.1f}",
            threshold=f"{anomaly.threshold:.1f}",
            severity=anomaly.severity.value,
            metrics=str(metrics),
        )
    if anomaly.metric_name == "postgres_apache_chain":
        return load_prompt(
            template_name,
            minion_id=anomaly.minion_id,
            instance=anomaly.minion_id,
            apache_minion_id=anomaly.context.get(
                "apache_minion_id", anomaly.minion_id
            ),
            postgres_minion_id=anomaly.context.get(
                "postgres_minion_id", anomaly.minion_id
            ),
            metric_name=anomaly.metric_name,
            current_value=f"{anomaly.current_value:.1f}",
            threshold=f"{anomaly.threshold:.1f}",
            severity=anomaly.severity.value,
            metrics=str(metrics),
        )
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


def _bounded_text(value, limit=8000):
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


async def collect_required_disk_evidence(anomaly):
    """Collect the minimum evidence required for a causal disk RCA.

    This path is deterministic: the LLM may call additional tools, but cannot
    skip filesystem, largest-file, and candidate-service inspection.
    """
    client = salt_api.salt_client
    if client is None:
        return "Salt client is unavailable; required disk evidence not collected."

    minion_id = anomaly.minion_id
    mountpoint = anomaly.context.get("mountpoint", anomaly.resource or "/")
    disk_usage, largest_files, references = await asyncio.gather(
        client.disk_usage(minion_id),
        client.largest_files(minion_id, mountpoint),
        client.service_references(minion_id, mountpoint),
    )

    candidates = list(
        anomaly.context.get("related_unhealthy_services", [])
    )
    for unit in parse_service_unit_references(references):
        if unit not in candidates:
            candidates.append(unit)
    candidates = candidates[:3]

    service_evidence = []
    if candidates:
        inspections = await asyncio.gather(*(
            asyncio.gather(
                client.service_details(minion_id, service),
                client.service_logs(minion_id, service, lines=30),
            )
            for service in candidates
        ))
        for service, (details, logs) in zip(candidates, inspections):
            service_evidence.append(
                f"SERVICE {service}\n"
                f"DETAILS:\n{_bounded_text(details, 8000)}\n"
                f"JOURNAL:\n{_bounded_text(logs, 8000)}"
            )
    else:
        service_evidence.append("No candidate systemd service was discovered.")

    return (
        f"AFFECTED MOUNTPOINT: {mountpoint}\n"
        f"DISK USAGE:\n{_bounded_text(disk_usage, 10000)}\n\n"
        f"LARGEST FILES:\n{_bounded_text(largest_files, 8000)}\n\n"
        f"UNIT FILE REFERENCES:\n{_bounded_text(references, 4000)}\n\n"
        + "\n\n".join(service_evidence)
    )


async def collect_required_postgres_lock_evidence(anomaly):
    """Collect availability and lock-chain evidence before LLM reasoning."""
    client = salt_api.salt_client
    if client is None:
        return (
            "Salt client is unavailable; required PostgreSQL evidence "
            "was not collected."
        )

    health, lock_pairs, apache_snapshot = await asyncio.gather(
        client.postgres_health(anomaly.minion_id),
        client.postgres_blocking_activity(anomaly.minion_id),
        client.apache_overload_snapshot(anomaly.minion_id),
    )
    detector_pairs = anomaly.context.get("blocked_pairs", [])
    return (
        "POSTGRESQL AVAILABILITY:\n"
        f"{_bounded_text(health, 4000)}\n\n"
        "CURRENT BLOCKED/BLOCKER PAIRS:\n"
        f"{_bounded_text(lock_pairs, 12000)}\n\n"
        "CURRENT APACHE/DEPENDENCY SNAPSHOT:\n"
        f"{_bounded_text(apache_snapshot, 18000)}\n\n"
        "DETECTOR SNAPSHOT:\n"
        f"{_bounded_text(detector_pairs, 12000)}"
    )


async def collect_required_apache_evidence(anomaly):
    """Collect one coherent traffic/backend snapshot before Apache RCA."""
    client = salt_api.salt_client
    if client is None:
        return (
            "Salt client is unavailable; required Apache evidence was not "
            "collected."
        )
    apache_minion_id = anomaly.context.get(
        "apache_minion_id", anomaly.minion_id
    )
    postgres_minion_id = anomaly.context.get(
        "postgres_minion_id", anomaly.minion_id
    )
    snapshot, postgres_health, postgres_locks, postgres_connections = (
        await asyncio.gather(
            client.apache_overload_snapshot(apache_minion_id),
            client.postgres_health(postgres_minion_id),
            client.postgres_blocking_activity(postgres_minion_id),
            client.postgres_connection_activity(postgres_minion_id),
        )
    )
    return (
        "PROMETHEUS DETECTOR SNAPSHOT:\n"
        f"{_bounded_text(anomaly.context, 5000)}\n\n"
        f"APACHE/APPLICATION MINION: {apache_minion_id}\n"
        "LIVE APACHE, TRAFFIC, CONNECTION, PROCESS, AND CONFIG SNAPSHOT:\n"
        f"{_bounded_text(snapshot, 24000)}\n\n"
        f"POSTGRESQL MINION: {postgres_minion_id}\n"
        "POSTGRESQL AVAILABILITY:\n"
        f"{_bounded_text(postgres_health, 4000)}\n\n"
        "POSTGRESQL BLOCKED/BLOCKER PAIRS:\n"
        f"{_bounded_text(postgres_locks, 14000)}\n\n"
        "POSTGRESQL CONNECTION CAPACITY/OWNERSHIP:\n"
        f"{_bounded_text(postgres_connections, 12000)}"
    )


async def collect_required_postgres_connection_evidence(anomaly):
    """Collect availability, capacity ownership, and lock evidence."""
    client = salt_api.salt_client
    if client is None:
        return (
            "Salt client is unavailable; required PostgreSQL connection "
            "evidence was not collected."
        )

    health, connections, lock_pairs = await asyncio.gather(
        client.postgres_health(anomaly.minion_id),
        client.postgres_connection_activity(anomaly.minion_id),
        client.postgres_blocking_activity(anomaly.minion_id),
    )
    return (
        "POSTGRESQL AVAILABILITY:\n"
        f"{_bounded_text(health, 4000)}\n\n"
        "CONNECTION CAPACITY AND OWNERSHIP:\n"
        f"{_bounded_text(connections, 16000)}\n\n"
        "CURRENT BLOCKED/BLOCKER PAIRS:\n"
        f"{_bounded_text(lock_pairs, 10000)}\n\n"
        "PROMETHEUS DETECTOR SNAPSHOT:\n"
        f"{_bounded_text(anomaly.context, 4000)}"
    )


async def collect_required_memory_evidence(anomaly):
    """Collect a live, fixed-command snapshot before memory RCA reasoning."""
    client = salt_api.salt_client
    if client is None:
        return (
            "Salt client is unavailable; required memory-pressure evidence "
            "was not collected."
        )

    snapshot = await client.memory_pressure_snapshot(anomaly.minion_id)
    return (
        "PROMETHEUS DETECTOR SNAPSHOT:\n"
        f"{_bounded_text(anomaly.context, 8000)}\n\n"
        "LIVE HOST SNAPSHOT:\n"
        f"{_bounded_text(snapshot, 16000)}"
    )


async def collect_required_cpu_evidence(anomaly):
    """Collect a live fixed-command snapshot before CPU RCA reasoning."""
    client = salt_api.salt_client
    if client is None:
        return (
            "Salt client is unavailable; required CPU evidence was not "
            "collected."
        )
    snapshot = await client.cpu_pressure_snapshot(anomaly.minion_id)
    return (
        "PROMETHEUS DETECTOR SNAPSHOT:\n"
        f"{_bounded_text(anomaly.context, 8000)}\n\n"
        "LIVE HOST SNAPSHOT:\n"
        f"{_bounded_text(snapshot, 16000)}"
    )


_REQUIRED_EVIDENCE_COLLECTORS = {
    "memory": collect_required_memory_evidence,
    "memory_pressure": collect_required_memory_evidence,
    "cpu": collect_required_cpu_evidence,
    "apache_busy_workers": collect_required_apache_evidence,
    "apache_requests": collect_required_apache_evidence,
    "postgres_apache_chain": collect_required_apache_evidence,
    "disk": collect_required_disk_evidence,
    "postgres_blocked_transaction": collect_required_postgres_lock_evidence,
    "postgres_connections": collect_required_postgres_connection_evidence,
}


async def collect_required_evidence(anomaly):
    """Collect deterministic evidence for anomaly types that require it."""
    collector = _REQUIRED_EVIDENCE_COLLECTORS.get(anomaly.metric_name)
    if collector is None:
        return ""
    return await collector(anomaly)


def append_required_evidence(prompt, evidence):
    """Append one consistently formatted, bounded evidence section."""
    if not evidence:
        return prompt
    return (
        f"{prompt}\n\n## Pre-collected mandatory evidence\n\n"
        f"{evidence}\n\n"
        "Use this evidence in the RCA. You may call tools for clarification."
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
    required_evidence = await collect_required_evidence(anomaly)
    scenario_prompt = append_required_evidence(
        scenario_prompt,
        required_evidence,
    )

    # Phase 1: run the ReAct agent (async; async tools are awaited by the tool node)
    result = await agent.ainvoke({
        "messages": [
            SystemMessage(content=system_prompt),
            ("human", scenario_prompt),
        ]
    })

    reasoning = _extract_text(result["messages"][-1])
    if required_evidence:
        reasoning = (
            "PRE-COLLECTED MANDATORY EVIDENCE:\n"
            f"{required_evidence}\n\n"
            f"AGENT SYNTHESIS:\n{reasoning}"
        )

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
        f"minion={anomaly.minion_id}, "
        f"service={anomaly.service_name or 'n/a'}, "
        f"resource={anomaly.resource or 'n/a'}, "
        f"context={anomaly.context})\n\n"
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
