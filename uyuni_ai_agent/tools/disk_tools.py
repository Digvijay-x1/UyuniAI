from langchain_core.tools import tool

from uyuni_ai_agent.salt_api import salt_api


@tool
def get_disk_usage(minion_id: str) -> str:
    """Get disk usage summary for all mounted filesystems on a minion.
    Use this when you detect high disk usage and need to see which
    partitions are filling up.
    """
    result = salt_api.cmd(minion_id, 'disk.usage', [])
    return str(result)


@tool
def find_large_files(minion_id: str, path: str = "/", min_size: str = "100M") -> str:
    """Find files larger than a specified size on a minion.
    Use this to identify what is consuming disk space.
    Args:
        minion_id: the Salt minion ID
        path: directory to search in (default: /)
        min_size: minimum file size to report (default: 100M)
    """
    cmd = f"find {path} -type f -size +{min_size} 2>/dev/null | head -20"
    return salt_api.cmd(minion_id, 'cmd.run', [cmd])
