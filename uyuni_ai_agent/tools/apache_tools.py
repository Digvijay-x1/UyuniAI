from langchain_core.tools import tool

from uyuni_ai_agent import salt_api


@tool
async def get_apache_status(minion_id: str) -> str:
    """Get Apache server-status output showing workers, requests, and load.

    Returns mod_status auto output including:
    - Total Accesses and kBytes
    - BusyWorkers and IdleWorkers
    - Requests per second and bytes per request
    - Scoreboard showing worker states
    """
    return await salt_api.salt_client.run_command(
        minion_id,
        "curl -s http://localhost/server-status?auto"
    )


@tool
async def get_apache_error_log(minion_id: str, lines: int = 50) -> str:
    """Get recent Apache error log entries.

    Returns the last N lines from /var/log/apache2/error.log.
    Look for [error] and [crit] entries, module errors, and segfaults.
    """
    return await salt_api.salt_client.run_command(
        minion_id,
        f"tail -n {lines} /var/log/apache2/error.log"
    )


@tool
async def get_apache_access_log(minion_id: str, lines: int = 50) -> str:
    """Get recent Apache access log entries.

    Returns the last N lines from /var/log/apache2/access.log.
    Useful for identifying traffic spikes, suspicious IPs, or slow requests.
    """
    return await salt_api.salt_client.run_command(
        minion_id,
        f"tail -n {lines} /var/log/apache2/access.log"
    )


@tool
async def get_apache_config_check(minion_id: str) -> str:
    """Check Apache configuration for errors and show MPM worker settings.

    Returns the output of apachectl -t (config test) and the current
    MPM configuration (MaxRequestWorkers, ServerLimit, etc.).
    """
    return await salt_api.salt_client.run_command(
        minion_id,
        "apachectl -t 2>&1 && apachectl -V | grep -i mpm && "
        "grep -rh 'MaxRequestWorkers\\|ServerLimit\\|MaxConnectionsPerChild' "
        "/etc/apache2/ 2>/dev/null || echo 'Using defaults'"
    )
