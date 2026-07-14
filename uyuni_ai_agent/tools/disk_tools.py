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
async def get_disk_usage(minion_id: str) -> str:
    """Get disk usage summary for all mounted filesystems on a minion.
    Use this when you detect high disk usage and need to see which
    partitions are filling up.
    """
    return await salt_api.salt_client.disk_usage(minion_id)


@tool
async def find_large_files(minion_id: str, path: str = "/", min_size: str = "100M") -> str:
    """Find files larger than a specified size on a minion.
    Use this to identify what is consuming disk space.
    Args:
        minion_id: the Salt minion ID
        path: directory to search in (default: /)
        min_size: minimum file size to report (default: 100M)
    """
    cmd = f"find {path} -type f -size +{min_size} 2>/dev/null | head -20"
    return await salt_api.salt_client.run_command(minion_id, cmd)
