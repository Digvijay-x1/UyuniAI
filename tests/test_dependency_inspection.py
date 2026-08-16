import asyncio

import pytest
from pydantic import ValidationError

from uyuni_ai_agent.anomaly_detector import AlertSeverity, Anomaly
from uyuni_ai_agent.config_schema import InspectionDependencyEdge
from uyuni_ai_agent.dependency_inspection import (
    build_nfs_source_command,
    build_ssh_source_command,
    build_tls_source_command,
)
from uyuni_ai_agent.deterministic_analysis import try_deterministic_analysis
from uyuni_ai_agent.evidence import EvidenceLedger, EvidenceStatus
from uyuni_ai_agent.models import AnalysisConclusion
from uyuni_ai_agent.react_agent import ALL_TOOLS, collect_required_service_evidence
from uyuni_ai_agent.salt_api import SaltAPIClient


def edge(kind, **overrides):
    values = {
        "id": f"{kind}-edge",
        "kind": kind,
        "source_minion": "client2",
        "source_service": f"{kind}-job.service",
        "target_minion": "client1",
        "target_host": "server.example",
    }
    values.update(overrides)
    return values


def test_dependency_schema_requires_protocol_fields_and_absolute_paths():
    with pytest.raises(ValidationError, match="ssh dependency requires"):
        InspectionDependencyEdge.model_validate(edge("ssh", port=2222))

    with pytest.raises(ValidationError, match="absolute POSIX path"):
        InspectionDependencyEdge.model_validate(edge(
            "nfs",
            source_mount="../mount",
            target_export="/srv/export",
            expected_uid=42,
            expected_gid=42,
        ))


def test_fixed_commands_contain_only_configured_bounded_inspections():
    ssh = edge(
        "ssh",
        port=2222,
        known_hosts_file="/etc/app/known_hosts",
        host_public_key_file="/etc/ssh/key.pub",
    )
    tls = edge(
        "tls",
        port=8443,
        expected_hostname="server.example",
        ca_file="/etc/app/ca.crt",
        certificate_file="/etc/app/server.crt",
    )
    nfs = edge(
        "nfs",
        source_mount="/mnt/backup",
        target_export="/srv/backup",
        expected_uid=42424,
        expected_gid=42424,
    )

    assert "ssh-keygen -F '[server.example]:2222'" in build_ssh_source_command(ssh)
    assert "-verify_hostname server.example" in build_tls_source_command(tls)
    assert "findmnt --target /mnt/backup" in build_nfs_source_command(nfs)
    assert "expected_uid=42424 expected_gid=42424" in build_nfs_source_command(nfs)


def test_dependency_tools_are_registered():
    names = {item.name for item in ALL_TOOLS}
    assert {
        "inspect_ssh_dependency",
        "inspect_tls_dependency",
        "inspect_nfs_dependency",
    } <= names


def test_salt_dependency_lookup_is_topology_and_inventory_gated():
    config = {
        "salt_api": {"url": "https://salt", "username": "agent"},
        "minions": [{"id": "client1"}, {"id": "client2"}],
        "concurrency": {"max_salt_calls": 2},
        "dependency_correlation": {"edges": [edge(
            "ssh",
            port=2222,
            known_hosts_file="/etc/app/known_hosts",
            host_public_key_file="/etc/ssh/key.pub",
        )]},
    }
    client = SaltAPIClient(config)

    assert client.dependencies_for_service("client2", "ssh-job.service")[0]["id"] == "ssh-edge"
    with pytest.raises(ValueError, match="not configured"):
        client._dependency("invented", "ssh")
    with pytest.raises(ValueError, match="not configured"):
        client._dependency("ssh-edge", "tls")

    client.replace_allowed_minions(["client2"])
    with pytest.raises(ValueError, match="outside.*inventory"):
        client._dependency("ssh-edge", "ssh")


def service_anomaly(kind):
    return Anomaly(
        minion_id="client2",
        metric_name="service_down",
        current_value=1,
        threshold=1,
        severity=AlertSeverity.CRITICAL,
        description=f"{kind}-job.service failed",
        service_name=f"{kind}-job.service",
    )


def ledger_with(kind, log, snapshot):
    ledger = EvidenceLedger("client2")
    ledger.add(
        source="salt",
        check=f"service_logs:{kind}-job.service",
        status=EvidenceStatus.OK,
        summary="service logs",
        details=log,
    )
    ledger.add(
        source="salt",
        check=f"dependency_inspection:{kind}:{kind}-edge",
        status=EvidenceStatus.OK,
        summary="dependency snapshot",
        details=snapshot,
    )
    return ledger


@pytest.mark.parametrize(
    "kind,log,snapshot,component,required_remediation",
    [
        (
            "ssh",
            "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! Host key verification failed.",
            "--- SOURCE ---\nCLIENT_PINNED_HOST_KEYS\n256 SHA256:OLDKEY host\n"
            "--- TARGET ---\nSERVER_PRESENTED_HOST_KEY\n256 SHA256:NEWKEY host",
            "SSH host-key trust",
            "out-of-band",
        ),
        (
            "tls",
            "curl: (60) no alternative certificate subject name matches target host name",
            "verify error:num=62:hostname mismatch\nVerification error: hostname mismatch\n"
            "X509v3 Subject Alternative Name:\n DNS:wrong.internal",
            "TLS certificate identity",
            "without disabling TLS verification",
        ),
        (
            "nfs",
            "cannot create /mnt/backup.tmp: Permission denied",
            "mount=/mnt/backup uid=43434 gid=43434 mode=750 type=directory\n"
            "expected_uid=42424 expected_gid=42424\n"
            "export=/srv/backup uid=43434 gid=43434 mode=750 type=directory",
            "NFS export ownership mapping",
            "without weakening export policy",
        ),
    ],
)
def test_protocol_evidence_produces_confirmed_safe_deterministic_rca(
    kind, log, snapshot, component, required_remediation
):
    result = try_deterministic_analysis(
        service_anomaly(kind), ledger_with(kind, log, snapshot)
    )

    assert result.conclusion is AnalysisConclusion.CONFIRMED
    assert result.affected_component == component
    assert result.confidence == 0.99
    assert required_remediation in " ".join(result.remediation)
    assert "[E1]" in result.root_cause and "[E2]" in result.root_cause


def test_matching_failed_service_collects_dependency_snapshot(monkeypatch):
    class FakeSalt:
        async def service_details(self, *_args, **_kwargs):
            return "ActiveState=failed"

        async def service_logs(self, *_args, **_kwargs):
            return "Host key verification failed"

        async def run_command(self, *_args, **_kwargs):
            return "LISTEN"

        def dependencies_for_service(self, minion, service):
            assert (minion, service) == ("client2", "ssh-job.service")
            return [edge("ssh")]

        async def inspect_dependency(self, dependency_id, kind):
            assert (dependency_id, kind) == ("ssh-edge", "ssh")
            return "pinned SHA256:OLD presented SHA256:NEW"

    monkeypatch.setattr(
        "uyuni_ai_agent.react_agent.salt_api.salt_client", FakeSalt()
    )
    ledger = asyncio.run(collect_required_service_evidence(service_anomaly("ssh")))

    assert ledger.records[-1].check == "dependency_inspection:ssh:ssh-edge"
    assert ledger.records[-1].target == "client2->client1"


def test_ssh_pattern_does_not_flag_when_any_pinned_key_matches_presented():
    snapshot = (
        "--- SOURCE ---\n256 SHA256:OLD host\n256 SHA256:CURRENT host\n"
        "--- TARGET ---\n256 SHA256:CURRENT host"
    )
    result = try_deterministic_analysis(
        service_anomaly("ssh"),
        ledger_with("ssh", "Host key verification failed", snapshot),
    )

    assert result is None
