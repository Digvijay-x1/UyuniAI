**Apache Overload Alert on `{minion_id}`**

**Anomaly:** {metric_name} is at **{current_value}** (threshold: {threshold}, severity: {severity})

**Current System Metrics:**
{metrics}

Investigate this Apache issue on the server. Use the available tools:

1. **get_apache_status** — Check `server-status` for BusyWorkers, IdleWorkers, requests/sec, and scoreboard
2. **get_top_cpu_processes** / **get_top_memory_processes** — See if Apache or related processes are consuming resources
3. **get_apache_error_log** — Check for module errors, segfaults, or AH* error codes
4. **get_apache_access_log** — Look for traffic spikes, DDoS patterns, or runaway bots
5. **get_apache_config_check** — Check if MaxRequestWorkers is too low or configuration has errors

Common root causes to look for:
- Traffic spike overwhelming worker capacity
- Slow backend (PHP/CGI) causing workers to stay busy
- MaxRequestWorkers set too low for current load
- Memory leak in Apache modules causing workers to grow
- DDoS or bot traffic flooding the server
