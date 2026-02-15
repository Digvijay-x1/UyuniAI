from langchain_core.tools import tool

from uyuni_ai_agent.salt_api import salt_client


@tool
def check_connectivity(minion_id: str, target: str) -> str:
    """Ping a target host from a minion to check network connectivity.
    Use this when you suspect network issues are causing service problems.
    """
    cmd = f"ping -c 3 {target}"
    return salt_client.run_command(minion_id, cmd)


@tool
def get_listening_ports(minion_id: str) -> str:
    """Get all listening TCP ports on a minion.
    Use this to verify which services have their ports open and listening.
    """
    return salt_client.run_command(minion_id, "ss -tlnp")
