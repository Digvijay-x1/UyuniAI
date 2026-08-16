# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Fixed, read-only commands for explicitly configured dependency edges."""

from __future__ import annotations

import shlex


def _q(value) -> str:
    return shlex.quote(str(value))


def build_ssh_source_command(edge: dict) -> str:
    host = edge["target_host"]
    port = edge["port"]
    lookup = host if port == 22 else f"[{host}]:{port}"
    known_hosts = _q(edge["known_hosts_file"])
    return (
        "printf '%s\\n' 'CLIENT_PINNED_HOST_KEYS'; "
        f"ssh-keygen -F {_q(lookup)} -f {known_hosts} 2>/dev/null "
        "| ssh-keygen -lf - -E sha256 2>&1 | head -n 10"
    )


def build_ssh_target_command(edge: dict) -> str:
    public_key = _q(edge["host_public_key_file"])
    return (
        "printf '%s\\n' 'SERVER_PRESENTED_HOST_KEY'; "
        f"ssh-keygen -lf {public_key} -E sha256 2>&1 | head -n 10"
    )


def build_tls_source_command(edge: dict) -> str:
    endpoint = f"{edge['target_host']}:{edge['port']}"
    hostname = _q(edge["expected_hostname"])
    ca_file = _q(edge["ca_file"])
    return (
        "printf '%s\\n' 'CLIENT_TLS_IDENTITY_VERIFICATION'; "
        f"openssl s_client -connect {_q(endpoint)} -servername {hostname} "
        f"-verify_hostname {hostname} -verify_return_error -CAfile {ca_file} "
        "</dev/null 2>&1 | head -n 100"
    )


def build_tls_target_command(edge: dict) -> str:
    certificate = _q(edge["certificate_file"])
    return (
        "printf '%s\\n' 'SERVER_CERTIFICATE_IDENTITY'; "
        f"openssl x509 -in {certificate} -noout -subject -issuer -dates "
        "-ext subjectAltName -fingerprint -sha256 2>&1 | head -n 40"
    )


def build_nfs_source_command(edge: dict) -> str:
    mount = _q(edge["source_mount"])
    uid = edge["expected_uid"]
    gid = edge["expected_gid"]
    return (
        "printf '%s\\n' 'CLIENT_NFS_MOUNT'; "
        f"findmnt --target {mount} --noheadings "
        "--output SOURCE,TARGET,FSTYPE,OPTIONS 2>&1 | head -n 5; "
        f"stat -c 'mount=%n uid=%u gid=%g mode=%a type=%F' {mount} 2>&1; "
        f"printf 'expected_uid={uid} expected_gid={gid}\\n'; "
        f"getent passwd {uid} 2>&1 | head -n 1; getent group {gid} 2>&1 | head -n 1"
    )


def build_nfs_target_command(edge: dict) -> str:
    export = _q(edge["target_export"])
    uid = edge["expected_uid"]
    gid = edge["expected_gid"]
    return (
        "printf '%s\\n' 'SERVER_NFS_EXPORT'; "
        "exportfs -v 2>&1 | head -n 80; "
        f"stat -c 'export=%n uid=%u gid=%g mode=%a type=%F' {export} 2>&1; "
        f"printf 'expected_uid={uid} expected_gid={gid}\\n'; "
        f"getent passwd {uid} 2>&1 | head -n 1; getent group {gid} 2>&1 | head -n 1"
    )


BUILDERS = {
    "ssh": (build_ssh_source_command, build_ssh_target_command),
    "tls": (build_tls_source_command, build_tls_target_command),
    "nfs": (build_nfs_source_command, build_nfs_target_command),
}
