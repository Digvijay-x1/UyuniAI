import os
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage

from uyuni_ai_agent.llm_provider import get_llm
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


def investigate(anomaly, metrics):
    """Run the ReAct agent to investigate an anomaly.
    The agent uses Salt tools to gather context and the LLM to reason
    about the root cause.

    Args:
        anomaly: an Anomaly dataclass from anomaly_detector
        metrics: dict of current Prometheus metrics

    Returns:
        str: the AI-generated root cause analysis
    """
    llm = get_llm()

    # Load system prompt
    system_prompt = load_prompt("system_prompt.md")

    # Load scenario-specific prompt
    scenario_prompt = get_prompt_for_anomaly(anomaly, metrics)

    # Create the ReAct agent with all Salt tools
    agent = create_react_agent(llm, ALL_TOOLS)

    # Run the agent
    result = agent.invoke({
        "messages": [
            SystemMessage(content=system_prompt),
            ("human", scenario_prompt),
        ]
    })

    # Extract the final response.
    # Some LLMs (Gemini) return content as a list of blocks
    final_message = result["messages"][-1]
    content = final_message.content

    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(text_parts)

    return content
