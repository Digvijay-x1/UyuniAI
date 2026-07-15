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


def build_memory_pressure_command() -> str:
    """Return a fixed, bounded command for memory-pressure investigation.

    Process arguments are deliberately omitted because command lines may
    contain credentials. The systemd unit column still gives the investigator
    a useful process-to-service correlation when one is available.
    """
    return (
        "printf '%s\\n' '=== FREE_BYTES ==='; "
        "LC_ALL=C free -b; "
        "printf '%s\\n' '=== VMSTAT_1S_3_SAMPLES ==='; "
        "LC_ALL=C vmstat -w 1 3; "
        "printf '%s\\n' '=== TOP_RSS_KIB ==='; "
        "LC_ALL=C ps -eo pid,ppid,user,comm,%cpu,%mem,rss,vsz,etimes,unit "
        "--sort=-rss | head -n 16; "
        "printf '%s\\n' '=== MEMORY_PRESSURE_STALL ==='; "
        "cat /proc/pressure/memory 2>/dev/null || true; "
        "printf '%s\\n' '=== RECENT_OOM_EVENTS ==='; "
        "journalctl -k --since '-10 minutes' --no-pager -n 30 "
        "| grep -Ei 'out of memory|oom-kill|killed process' || true"
    )
