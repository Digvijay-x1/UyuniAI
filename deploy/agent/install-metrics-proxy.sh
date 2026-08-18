#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this script as root on the Uyuni container host." >&2
    exit 1
fi
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <monitoring-server-ipv4>" >&2
    exit 2
fi

monitoring_ip=$1
python3 -c \
    'import ipaddress, sys; address = ipaddress.ip_address(sys.argv[1]); assert address.version == 4' \
    "${monitoring_ip}" 2>/dev/null || {
        echo "Monitoring server address must be valid IPv4." >&2
        exit 2
    }

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
monitoring_dir=${script_dir}/../monitoring
rendered_firewall=$(mktemp)
trap 'rm -f "${rendered_firewall}"' EXIT

sed "s/MONITORING_SERVER_IP/${monitoring_ip}/g" \
    "${monitoring_dir}/uyuni-ai-agent-metrics.nft" > "${rendered_firewall}"

install -D -o root -g root -m 0755 \
    "${monitoring_dir}/uyuni-ai-agent-metrics-proxy" \
    /usr/local/sbin/uyuni-ai-agent-metrics-proxy
install -D -o root -g root -m 0644 \
    "${rendered_firewall}" \
    /etc/nftables/uyuni-ai-agent-metrics.nft
install -D -o root -g root -m 0644 \
    "${monitoring_dir}/uyuni-ai-agent-metrics-firewall.service" \
    /etc/systemd/system/uyuni-ai-agent-metrics-firewall.service
install -D -o root -g root -m 0644 \
    "${monitoring_dir}/uyuni-ai-agent-metrics-proxy.service" \
    /etc/systemd/system/uyuni-ai-agent-metrics-proxy.service
install -D -o root -g root -m 0644 \
    "${monitoring_dir}/uyuni-ai-agent-metrics-proxy.socket" \
    /etc/systemd/system/uyuni-ai-agent-metrics-proxy.socket

systemctl daemon-reload
systemctl enable --now \
    uyuni-ai-agent-metrics-firewall.service \
    uyuni-ai-agent-metrics-proxy.socket

# firewalld's later input hook can still reject traffic accepted by the
# dedicated nftables chain. Add the same source-scoped permission there when
# firewalld is active; do not open the port generally.
if command -v firewall-cmd >/dev/null 2>&1 \
    && firewall-cmd --state >/dev/null 2>&1; then
    firewall_rule="rule family=ipv4 source address=${monitoring_ip} port port=9898 protocol=tcp accept"
    firewall-cmd --permanent --add-rich-rule="${firewall_rule}"
    firewall-cmd --reload
fi

echo "Agent metrics are exposed only to ${monitoring_ip}."
