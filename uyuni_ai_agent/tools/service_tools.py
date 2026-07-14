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
async def get_service_status(minion_id: str, service: str) -> str:
    """Check if a service is running on a minion.
    Use this to verify whether a specific service (e.g. postgresql, apache2)
    is active or has crashed.
    """
    result = await salt_api.salt_client.service_status(minion_id, service)
    if result is True:
        return f"{service} is running"
    elif result is False:
        return f"{service} is NOT running"
    else:
        return str(result)


@tool
async def get_service_logs(minion_id: str, service: str, lines: int = 50) -> str:
    """Get recent journal logs for a service on a minion.
    Use this when a service is down or misbehaving and you need to
    check the logs for errors.
    """
    return await salt_api.salt_client.service_logs(minion_id, service, lines)
