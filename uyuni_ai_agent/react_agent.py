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
from uyuni_ai_agent.models import (
    AnalysisConclusion,
    RootCauseAnalysis,
    Urgency,
)
from uyuni_ai_agent.evidence import (
    EvidenceLedger,
    EvidenceStatus,
    evidence_status_for,
    ground_analysis,
)
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


def _ledger_for_anomaly(anomaly):
    ledger = EvidenceLedger(anomaly.minion_id)
    ledger.add(
        source="detector",
        check=anomaly.metric_name,
        status=EvidenceStatus.OK,
        summary=anomaly.description,
        details={
            "value": anomaly.current_value,
            "threshold": anomaly.threshold,
            "severity": anomaly.severity.value,
            "service": anomaly.service_name,
            "resource": anomaly.resource,
            "context": anomaly.context,
        },
        detail_limit=8_000,
    )
    if anomaly.metric_name == "telemetry_unavailable":
        evidence_source = anomaly.context.get("source", "prometheus")
        for observation in anomaly.context.get("observations", []):
            raw_status = observation.get("status", "error")
            try:
                status = EvidenceStatus(raw_status)
            except ValueError:
                status = EvidenceStatus.ERROR
            ledger.add(
                source=evidence_source,
                target=anomaly.context.get("target", anomaly.minion_id),
                check=observation.get("name", "unknown_metric"),
                status=status,
                summary=(
                    f"{observation.get('name', 'metric')} telemetry is "
                    f"{status.value}"
                ),
                details=observation,
                detail_limit=4_000,
            )
    return ledger


def _add_salt_evidence(
    ledger,
    *,
    check,
    summary,
    value,
    target=None,
    detail_limit=12_000,
):
    return ledger.add(
        source="salt",
        target=target,
        check=check,
        status=evidence_status_for(value),
        summary=summary,
        details=value,
        detail_limit=detail_limit,
    )


def _salt_unavailable(ledger, summary):
    ledger.add(
        source="salt",
        check="salt_api",
        status=EvidenceStatus.ERROR,
        summary=summary,
        details="The shared Salt API client was not initialized.",
    )
    return ledger


async def collect_required_disk_evidence(anomaly):
    """Collect the minimum evidence required for a causal disk RCA.

    This path is deterministic: the LLM may call additional tools, but cannot
    skip filesystem, largest-file, and candidate-service inspection.
    """
    ledger = _ledger_for_anomaly(anomaly)
    client = salt_api.salt_client
    if client is None:
        return _salt_unavailable(
            ledger,
            "Salt client is unavailable; required disk evidence was not collected",
        )

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

    _add_salt_evidence(
        ledger,
        check="disk_usage",
        summary=f"Disk usage snapshot for {mountpoint}",
        value=disk_usage,
        detail_limit=10_000,
    )
    _add_salt_evidence(
        ledger,
        check="largest_files",
        summary=f"Largest files on filesystem containing {mountpoint}",
        value=largest_files,
        detail_limit=8_000,
    )
    _add_salt_evidence(
        ledger,
        check="service_references",
        summary=f"Systemd units referencing {mountpoint}",
        value=references,
        detail_limit=4_000,
    )

    if candidates:
        inspections = await asyncio.gather(*(
            asyncio.gather(
                client.service_details(minion_id, service),
                client.service_logs(minion_id, service, lines=30),
            )
            for service in candidates
        ))
        for service, (details, logs) in zip(candidates, inspections):
            _add_salt_evidence(
                ledger,
                check=f"service_details:{service}",
                summary=f"Runtime properties for candidate service {service}",
                value=details,
                detail_limit=8_000,
            )
            _add_salt_evidence(
                ledger,
                check=f"service_logs:{service}",
                summary=f"Recent journal for candidate service {service}",
                value=logs,
                detail_limit=8_000,
            )
    else:
        ledger.add(
            source="detector",
            check="candidate_service_discovery",
            status=EvidenceStatus.MISSING,
            summary="No candidate systemd service was discovered",
        )
    return ledger


async def collect_required_postgres_lock_evidence(anomaly):
    """Collect availability and lock-chain evidence before LLM reasoning."""
    ledger = _ledger_for_anomaly(anomaly)
    client = salt_api.salt_client
    if client is None:
        return _salt_unavailable(
            ledger,
            "Salt client is unavailable; PostgreSQL evidence was not collected",
        )

    health, lock_pairs, apache_snapshot = await asyncio.gather(
        client.postgres_health(anomaly.minion_id),
        client.postgres_blocking_activity(anomaly.minion_id),
        client.apache_overload_snapshot(anomaly.minion_id),
    )
    _add_salt_evidence(
        ledger,
        check="postgres_health",
        summary="PostgreSQL availability and server identity",
        value=health,
        detail_limit=4_000,
    )
    _add_salt_evidence(
        ledger,
        check="postgres_blocking_activity",
        summary="Current PostgreSQL blocked and blocker sessions",
        value=lock_pairs,
        detail_limit=12_000,
    )
    _add_salt_evidence(
        ledger,
        check="apache_dependency_snapshot",
        summary="Current Apache and dependency connection snapshot",
        value=apache_snapshot,
        detail_limit=18_000,
    )
    return ledger


async def collect_required_apache_evidence(anomaly):
    """Collect one coherent traffic/backend snapshot before Apache RCA."""
    ledger = _ledger_for_anomaly(anomaly)
    client = salt_api.salt_client
    if client is None:
        return _salt_unavailable(
            ledger,
            "Salt client is unavailable; Apache evidence was not collected",
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
    _add_salt_evidence(
        ledger,
        target=apache_minion_id,
        check="apache_overload_snapshot",
        summary="Apache traffic, worker, connection, process, and config snapshot",
        value=snapshot,
        detail_limit=24_000,
    )
    _add_salt_evidence(
        ledger,
        target=postgres_minion_id,
        check="postgres_health",
        summary="Downstream PostgreSQL availability",
        value=postgres_health,
        detail_limit=4_000,
    )
    _add_salt_evidence(
        ledger,
        target=postgres_minion_id,
        check="postgres_blocking_activity",
        summary="Downstream PostgreSQL blocked and blocker sessions",
        value=postgres_locks,
        detail_limit=14_000,
    )
    _add_salt_evidence(
        ledger,
        target=postgres_minion_id,
        check="postgres_connection_activity",
        summary="Downstream PostgreSQL connection capacity and ownership",
        value=postgres_connections,
        detail_limit=12_000,
    )
    return ledger


async def collect_required_postgres_connection_evidence(anomaly):
    """Collect availability, capacity ownership, and lock evidence."""
    ledger = _ledger_for_anomaly(anomaly)
    client = salt_api.salt_client
    if client is None:
        return _salt_unavailable(
            ledger,
            "Salt client is unavailable; PostgreSQL connection evidence was not collected",
        )

    health, connections, lock_pairs = await asyncio.gather(
        client.postgres_health(anomaly.minion_id),
        client.postgres_connection_activity(anomaly.minion_id),
        client.postgres_blocking_activity(anomaly.minion_id),
    )
    _add_salt_evidence(
        ledger,
        check="postgres_health",
        summary="PostgreSQL availability and server identity",
        value=health,
        detail_limit=4_000,
    )
    _add_salt_evidence(
        ledger,
        check="postgres_connection_activity",
        summary="PostgreSQL connection capacity and ownership",
        value=connections,
        detail_limit=16_000,
    )
    _add_salt_evidence(
        ledger,
        check="postgres_blocking_activity",
        summary="Current PostgreSQL blocked and blocker sessions",
        value=lock_pairs,
        detail_limit=10_000,
    )
    return ledger


async def collect_required_memory_evidence(anomaly):
    """Collect a live, fixed-command snapshot before memory RCA reasoning."""
    ledger = _ledger_for_anomaly(anomaly)
    client = salt_api.salt_client
    if client is None:
        return _salt_unavailable(
            ledger,
            "Salt client is unavailable; memory-pressure evidence was not collected",
        )

    snapshot = await client.memory_pressure_snapshot(anomaly.minion_id)
    _add_salt_evidence(
        ledger,
        check="memory_pressure_snapshot",
        summary="Live memory, swap, CPU, PSI, and top-RSS snapshot",
        value=snapshot,
        detail_limit=16_000,
    )
    return ledger


async def collect_required_cpu_evidence(anomaly):
    """Collect a live fixed-command snapshot before CPU RCA reasoning."""
    ledger = _ledger_for_anomaly(anomaly)
    client = salt_api.salt_client
    if client is None:
        return _salt_unavailable(
            ledger,
            "Salt client is unavailable; CPU evidence was not collected",
        )
    snapshot = await client.cpu_pressure_snapshot(anomaly.minion_id)
    _add_salt_evidence(
        ledger,
        check="cpu_pressure_snapshot",
        summary="Live load, CPU, PSI, and top-CPU process snapshot",
        value=snapshot,
        detail_limit=16_000,
    )
    return ledger


async def collect_required_service_evidence(anomaly):
    """Collect service state, logs, and listeners before service-down RCA."""
    ledger = _ledger_for_anomaly(anomaly)
    client = salt_api.salt_client
    if client is None:
        return _salt_unavailable(
            ledger,
            "Salt client is unavailable; service evidence was not collected",
        )
    service = anomaly.service_name or "unknown.service"
    details, logs, listeners = await asyncio.gather(
        client.service_details(anomaly.minion_id, service),
        client.service_logs(anomaly.minion_id, service, lines=50),
        client.run_command(anomaly.minion_id, "ss -ltnp"),
    )
    _add_salt_evidence(
        ledger,
        check=f"service_details:{service}",
        summary=f"Runtime properties for failed service {service}",
        value=details,
        detail_limit=8_000,
    )
    _add_salt_evidence(
        ledger,
        check=f"service_logs:{service}",
        summary=f"Recent journal for failed service {service}",
        value=logs,
        detail_limit=10_000,
    )
    _add_salt_evidence(
        ledger,
        check="listening_tcp_ports",
        summary="Processes listening on TCP ports",
        value=listeners,
        detail_limit=8_000,
    )
    return ledger


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
    "service_down": collect_required_service_evidence,
}


async def collect_required_evidence(anomaly):
    """Collect deterministic evidence for anomaly types that require it."""
    collector = _REQUIRED_EVIDENCE_COLLECTORS.get(anomaly.metric_name)
    if collector is None:
        return _ledger_for_anomaly(anomaly)
    return await collector(anomaly)


def append_required_evidence(prompt, evidence):
    """Append one consistently formatted, bounded evidence section."""
    if not evidence:
        return prompt
    evidence_text = (
        evidence.to_prompt()
        if isinstance(evidence, EvidenceLedger)
        else str(evidence)
    )
    if not evidence_text:
        return prompt
    return (
        f"{prompt}\n\n## Pre-collected mandatory evidence\n\n"
        f"{evidence_text}\n\n"
        "Use this evidence in the RCA. Cite evidence IDs exactly as [E1], "
        "and set conclusion=confirmed only when the cited records prove the "
        "cause. You may call tools for clarification."
    )


def _telemetry_unavailable_analysis(anomaly, ledger):
    failed = [
        record for record in ledger.records
        if record.status is not EvidenceStatus.OK
    ]
    supporting = failed or ledger.records
    citations = ", ".join(f"[{record.id}]" for record in supporting[:3])
    source = anomaly.context.get("source", "prometheus")
    if source == "salt":
        root_cause = (
            f"Salt cannot provide trustworthy inspection results for the "
            f"configured minion {citations}."
        )
        remediation = [
            "Check Salt minion connectivity and whether jobs return to the Uyuni server.",
            "Restore the Salt inspection path before evaluating service or database health.",
        ]
    else:
        root_cause = (
            f"Prometheus cannot provide trustworthy telemetry for the "
            f"configured target {citations}."
        )
        remediation = [
            "Check the Prometheus target status and the exporter process.",
            "Restore scraping, then wait for a fresh sample before evaluating system health.",
        ]
    analysis = RootCauseAnalysis(
        summary=anomaly.description,
        conclusion=AnalysisConclusion.CONFIRMED,
        affected_component=anomaly.context.get("exporter", "telemetry"),
        root_cause=root_cause,
        supporting_evidence_ids=[record.id for record in supporting[:3]],
        key_evidence=[
            f"[{record.id}] {record.summary}" for record in supporting[:3]
        ],
        remediation=remediation,
        urgency=Urgency.MEDIUM,
        confidence=1.0,
    )
    return ground_analysis(analysis, ledger, allow_failed_evidence=True)


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
    required_evidence = await collect_required_evidence(anomaly)
    if anomaly.metric_name == "telemetry_unavailable":
        return _telemetry_unavailable_analysis(anomaly, required_evidence)

    # Load system and scenario-specific prompts only for LLM investigations.
    system_prompt = load_prompt("system_prompt.md")
    scenario_prompt = get_prompt_for_anomaly(anomaly, metrics)

    # Reuse the compiled agent + LLM client (built once, cached) instead of
    # reconstructing both on every call. Only the messages vary per anomaly.
    agent = get_agent(config)
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
    evidence_text = required_evidence.to_prompt()
    if evidence_text:
        reasoning = (
            "PRE-COLLECTED MANDATORY EVIDENCE:\n"
            f"{evidence_text}\n\n"
            f"AGENT SYNTHESIS:\n{reasoning}"
        )

    # Phase 2: structure the free-form reasoning into RootCauseAnalysis.
    structured_llm = get_structured_llm(config)
    structuring_prompt = (
        "Convert the following investigation into the required structured "
        "analysis. Use ONLY the information present in the investigation; do "
        "not invent evidence or evidence IDs. Set conclusion='confirmed' only "
        "when the cause is proven. A confirmed root_cause must cite one or "
        "more supplied IDs such as [E1], supporting_evidence_ids must contain "
        "those IDs, and every key_evidence item must start with a supplied "
        "ID. Otherwise set conclusion='inconclusive', affected_component="
        "'unknown', and use low confidence.\n\n"
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
    return ground_analysis(analysis, required_evidence)


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
