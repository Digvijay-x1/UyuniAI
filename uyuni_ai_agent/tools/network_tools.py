import salt.client
from langchain_core.tools import tool


local = salt.client.LocalClient()


@tool
def check_connectivity(minion_id: str, target: str) -> str:
    """Ping a target host from a minion to check network connectivity.
    Use this when you suspect network issues are causing service problems.
    """
    cmd = f"ping -c 3 {target}"
    result = local.cmd(minion_id, 'cmd.run', [cmd])
    return result.get(minion_id, "No response from minion")


@tool
def get_listening_ports(minion_id: str) -> str:
    """Get all listening TCP ports on a minion.
    Use this to verify which services have their ports open and listening.
    """
    cmd = "ss -tlnp"
    result = local.cmd(minion_id, 'cmd.run', [cmd])
    return result.get(minion_id, "No response from minion")
