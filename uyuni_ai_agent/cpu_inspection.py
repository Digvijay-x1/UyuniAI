# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


def build_cpu_pressure_command() -> str:
    """Return a fixed, bounded CPU investigation command."""
    return (
        "printf '%s\\n' '=== LOAD_AVERAGE ==='; "
        "uptime; "
        "printf '%s\\n' '=== LOGICAL_CPU_COUNT ==='; "
        "nproc; "
        "printf '%s\\n' '=== VMSTAT_1S_3_SAMPLES ==='; "
        "LC_ALL=C vmstat -w 1 3; "
        "printf '%s\\n' '=== TOP_CPU ==='; "
        "LC_ALL=C ps -eo pid,ppid,user,comm,%cpu,%mem,rss,etimes,unit "
        "--sort=-%cpu | head -n 16; "
        "printf '%s\\n' '=== CPU_PRESSURE_STALL ==='; "
        "cat /proc/pressure/cpu 2>/dev/null || true; "
        "printf '%s\\n' '=== RECENT_THERMAL_OR_SOFT_LOCKUP_EVENTS ==='; "
        "journalctl -k --since '-10 minutes' --no-pager -n 30 "
        "| grep -Ei 'thermal|throttl|soft lockup|watchdog' || true"
    )
