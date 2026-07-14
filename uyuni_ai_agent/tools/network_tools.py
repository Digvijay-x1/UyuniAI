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
async def check_connectivity(minion_id: str, target: str) -> str:
    """Ping a target host from a minion to check network connectivity.
    Use this when you suspect network issues are causing service problems.
    """
    cmd = f"ping -c 3 {target}"
    return await salt_api.salt_client.run_command(minion_id, cmd)


@tool
async def get_listening_ports(minion_id: str) -> str:
    """Get all listening TCP ports on a minion.
    Use this to verify which services have their ports open and listening.
    """
    return await salt_api.salt_client.run_command(minion_id, "ss -tlnp")
