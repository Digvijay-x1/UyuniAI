import salt.client
from langchain_core.tools import tool


local = salt.client.LocalClient()


@tool
def get_service_status(minion_id: str, service: str) -> str:
    """Check if a service is running on a minion.
    Use this to verify whether a specific service (e.g. postgresql, apache2)
    is active or has crashed.
    """
    result = local.cmd(minion_id, 'service.status', [service])
    status = result.get(minion_id, None)
    if status is True:
        return f"{service} is running"
    elif status is False:
        return f"{service} is NOT running"
    else:
        return f"No response from minion"


@tool
def get_service_logs(minion_id: str, service: str, lines: int = 50) -> str:
    """Get recent journal logs for a service on a minion.
    Use this when a service is down or misbehaving and you need to
    check the logs for errors.
    """
    cmd = f"journalctl -u {service} -n {lines} --no-pager"
    result = local.cmd(minion_id, 'cmd.run', [cmd])
    return result.get(minion_id, "No response from minion")
