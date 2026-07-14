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

from langchain_core.tools import tool

from uyuni_ai_agent import salt_api


@tool
async def get_top_memory_processes(minion_id: str, top_n: int = 10) -> str:
    """Get the top memory-consuming processes on a minion.
    Use this when you detect high memory usage and need to find which
    processes are consuming the most RAM.
    """
    cmd = f"ps aux --sort=-%mem | head -n {top_n + 1}"
    return await salt_api.salt_client.run_command(minion_id, cmd)


@tool
async def get_top_cpu_processes(minion_id: str, top_n: int = 10) -> str:
    """Get the top CPU-consuming processes on a minion.
    Use this when you detect high CPU usage and need to find which
    processes are consuming the most CPU.
    """
    cmd = f"ps aux --sort=-%cpu | head -n {top_n + 1}"
    return await salt_api.salt_client.run_command(minion_id, cmd)
