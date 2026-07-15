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
from uyuni_ai_agent.disk_inspection import (
    build_large_files_command,
    build_service_references_command,
)


@tool
async def get_disk_usage(minion_id: str) -> str:
    """Get disk usage summary for all mounted filesystems on a minion.
    Use this when you detect high disk usage and need to see which
    partitions are filling up.
    """
    return await salt_api.salt_client.disk_usage(minion_id)


@tool
async def find_large_files(
    minion_id: str,
    path: str = "/",
    min_size: str = "10M",
    limit: int = 20,
) -> str:
    """List the largest files on one filesystem under an absolute path.

    Results include sizes and are sorted largest first. The search stays on the
    selected filesystem, which makes it suitable for investigating a specific
    full mountpoint.

    Args:
        minion_id: the Salt minion ID
        path: directory to search in (default: /)
        min_size: minimum file size to report (default: 10M)
        limit: maximum results, bounded to 1-50
    """
    return await salt_api.salt_client.run_command(
        minion_id,
        build_large_files_command(path, min_size, limit),
    )


@tool
async def find_service_references(minion_id: str, path: str) -> str:
    """Find systemd unit files whose definitions reference an absolute path.

    Use this after locating a full mount or runaway file to discover services
    configured to read from or write to that location. The search is bounded to
    systemd unit directories and does not modify the minion.
    """
    return await salt_api.salt_client.run_command(
        minion_id,
        build_service_references_command(path),
    )
