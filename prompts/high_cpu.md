High CPU usage detected on {minion_id}.

## Alert details

- Server: {minion_id}
- Instance: {instance}
- Current CPU usage: {current_value}%
- Threshold: {threshold}%
- Severity: {severity}

## Current Prometheus metrics

{metrics}

## Required investigation

The agent pre-collects CPU count, load averages, three one-second `vmstat`
samples, CPU pressure stalls, kernel throttling/lockup events, and processes
sorted by CPU. Use all mandatory evidence. You may call
`get_cpu_pressure_snapshot` with `minion_id="{minion_id}"` for a fresh sample.

Determine:

1. Whether CPU is still saturated in the live samples.
2. Which PID and systemd unit consume the CPU.
3. Whether the work is user CPU, system CPU, I/O wait, steal time, or runnable
   queue contention.
4. Whether memory pressure and swapping are present. If they are, treat CPU as
   a possible secondary symptom and use the memory-pressure evidence instead
   of assuming a CPU-bound workload.

Do not infer a runaway process from load average alone. Do not recommend a
host restart as the first action. Name the process only when the process list
supports it, and recommend stopping, correcting, or constraining that workload.
Process command-line arguments are intentionally omitted to avoid exposing
credentials. PSI `avg10`, `avg60`, and `avg300` are percentages of time stalled,
not seconds.

The integer under `LOGICAL_CPU_COUNT` is the authoritative logical CPU count.
Do not infer the CPU count from utilization percentages or load average. A
process can show approximately 100% for one logical CPU, so two such processes
can saturate a two-CPU host while the host-wide utilization remains capped at
100%.
