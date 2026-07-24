Host memory pressure detected on {minion_id}.

## Alert details

- Server: {minion_id}
- Instance: {instance}
- Memory usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}
- Available / total memory: {memory_available_bytes} / {memory_total_bytes} bytes
- Swap used / total: {swap_used_bytes} / {swap_total_bytes} bytes ({swap_usage_percent}%)
- Swap-in / swap-out rate: {swap_in_pages_per_second} / {swap_out_pages_per_second} pages/s
- Overall CPU usage: {cpu_usage_percent}%
- System CPU / I/O-wait CPU: {system_cpu_percent}% / {iowait_cpu_percent}%

## Current Prometheus metrics

{metrics}

## Required investigation

The agent pre-collects `free -b`, three one-second `vmstat` samples, memory
pressure-stall data, recent kernel OOM events, and the largest-RSS processes.
Use all of that mandatory evidence. You may call
`get_memory_pressure_snapshot` with `minion_id="{minion_id}"` again if a fresh
sample is necessary.

Correlate:

1. Low `MemAvailable` or high memory usage.
2. Current swap-in/swap-out activity from Prometheus and the `si`/`so` vmstat
   columns.
3. System CPU, I/O wait, and memory pressure-stall evidence.
4. The largest RSS process and its systemd unit, when present.

Important interpretation rules:

- Swap *usage* by itself does not prove current swap thrashing; pages can
  remain swapped out after pressure ends. Claim active swapping only when the
  rate or vmstat `si`/`so` samples show activity.
- Keep units exact: Prometheus `pswpin`/`pswpout` rates are pages/s. With this
  command's default units, `vmstat` memory columns (including `swpd`) are KiB
  and `si`/`so` are KiB/s. Never describe `vmstat` `si`/`so` values as
  pages/s. The `ps` RSS column is KiB.
- In `/proc/pressure/memory`, `avg10`, `avg60`, and `avg300` are percentages of
  wall-clock time stalled over those windows; they are not seconds. `total` is
  cumulative microseconds.
- Linux cache is reclaimable. Prefer `MemAvailable` over the raw `free` column.
- High system CPU or I/O wait can be a secondary effect of memory reclaim and
  swapping. Do not report it as an independent root cause when the timing and
  evidence correlate.
- When overall CPU exceeds its configured warning threshold while active
  swapping is proven, the final RCA must explicitly say whether that CPU usage
  is a secondary effect of the oversized working set, reclaim, and swap I/O.
  Cite overall CPU plus system CPU or I/O wait as evidence. Do not silently
  omit the correlated CPU symptom.
- `cpu_usage_percent` is total host-wide non-idle CPU; it is not system-mode
  CPU. `system_cpu_percent` and `iowait_cpu_percent` are the separate mode
  values. Keep those labels distinct.
- `memory_usage_percent` is already calculated from `MemAvailable`. If deriving
  the available percentage, use `100 - memory_usage_percent`; do not misstate
  the order of magnitude.
- Name the responsible process only when the RSS/process evidence supports it.
  Do not infer a memory leak from one snapshot.
- If there is no swap device, say so explicitly and diagnose memory pressure
  without claiming swapping.
- Do not recommend restarting the host as the first response. Recommend
  stopping or constraining the responsible workload, then correcting its
  memory limit/configuration. Prefer the systemd cgroup setting `MemoryMax=`
  when giving an example. Mention OOM risk when supported.
- Process command-line arguments are intentionally omitted from evidence to
  avoid exposing credentials.

The desired RCA explains the causal chain, for example: a named process
consumed most RAM, low available memory caused active swap I/O and reclaim,
and the observed CPU/I/O slowdown was a secondary effect.
