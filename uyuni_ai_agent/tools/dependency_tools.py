# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Topology-gated dependency tools; callers provide only a configured ID."""

from langchain_core.tools import tool

from uyuni_ai_agent import salt_api


@tool
async def inspect_ssh_dependency(dependency_id: str) -> str:
    """Compare pinned and presented SSH fingerprints for a configured edge."""
    return await salt_api.salt_client.inspect_dependency(dependency_id, "ssh")


@tool
async def inspect_tls_dependency(dependency_id: str) -> str:
    """Verify chain and hostname and inspect the certificate for a TLS edge."""
    return await salt_api.salt_client.inspect_dependency(dependency_id, "tls")


@tool
async def inspect_nfs_dependency(dependency_id: str) -> str:
    """Compare mount/export policy and numeric identity for an NFS edge."""
    return await salt_api.salt_client.inspect_dependency(dependency_id, "nfs")
