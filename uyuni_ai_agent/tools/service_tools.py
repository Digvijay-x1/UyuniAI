from langchain_core.tools import tool

from uyuni_ai_agent.salt_api import salt_client


@tool
def get_service_status(minion_id: str, service: str) -> str:
    """Check if a service is running on a minion.
    Use this to verify whether a specific service (e.g. postgresql, apache2)
    is active or has crashed.
    """
    result = salt_client.service_status(minion_id, service)
    if result is True:
        return f"{service} is running"
    elif result is False:
        return f"{service} is NOT running"
    else:
        return str(result)


@tool
def get_service_logs(minion_id: str, service: str, lines: int = 50) -> str:
    """Get recent journal logs for a service on a minion.
    Use this when a service is down or misbehaving and you need to
    check the logs for errors.
    """
    return salt_client.service_logs(minion_id, service, lines)
