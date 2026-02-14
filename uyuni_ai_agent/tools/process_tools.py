import salt.client
from langchain_core.tools import tool


local = salt.client.LocalClient()


@tool
def get_top_memory_processes(minion_id: str, top_n: int = 10) -> str:
    """Get the top memory-consuming processes on a minion.
    Use this when you detect high memory usage and need to find which
    processes are consuming the most RAM.
    """
    cmd = f"ps aux --sort=-%mem | head -n {top_n + 1}"
    result = local.cmd(minion_id, 'cmd.run', [cmd])
    return result.get(minion_id, "No response from minion")


@tool
def get_top_cpu_processes(minion_id: str, top_n: int = 10) -> str:
    """Get the top CPU-consuming processes on a minion.
    Use this when you detect high CPU usage and need to find which
    processes are consuming the most CPU.
    """
    cmd = f"ps aux --sort=-%cpu | head -n {top_n + 1}"
    result = local.cmd(minion_id, 'cmd.run', [cmd])
    return result.get(minion_id, "No response from minion")
