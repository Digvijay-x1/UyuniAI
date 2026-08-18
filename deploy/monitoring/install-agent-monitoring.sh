#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <uyuni-agent-hostname-or-ip>" >&2
    exit 2
fi

agent_target=$1
case "$agent_target" in
    *[!A-Za-z0-9._-]*|'')
        echo "Agent target must be a hostname or IPv4 address." >&2
        exit 2
        ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
config=/etc/prometheus/prometheus.yml
rule_source=${script_dir}/agent-self-alerts.yml
scrape_source=${script_dir}/prometheus-agent-scrape.yml
rule_target=/etc/prometheus/rules/agent-self-alerts.yml
candidate=$(mktemp)
with_rules=$(mktemp)
rendered_scrape=$(mktemp)
trap 'rm -f "$candidate" "$with_rules" "$rendered_scrape"' EXIT

test -r "$config"
test -r "$rule_source"
test -r "$scrape_source"

sed "s/UYUNI_AGENT_TARGET/${agent_target}/g" \
    "$scrape_source" > "$rendered_scrape"

install -d -m 0755 -o root -g prometheus /etc/prometheus/rules
install -m 0644 -o root -g prometheus "$rule_source" "$rule_target"
promtool check rules "$rule_target"

cp "$config" "$candidate"
if ! grep -q '^rule_files:' "$candidate"; then
    {
        printf 'rule_files:\n  - /etc/prometheus/rules/*.yml\n\n'
        cat "$candidate"
    } > "$with_rules"
    mv "$with_rules" "$candidate"
fi

if ! grep -Eq 'job_name:.*uyuni-ai-agent' "$candidate"; then
    printf '\n' >> "$candidate"
    # Keep the list item nested beneath the existing top-level
    # ``scrape_configs`` key.
    tail -n +4 "$rendered_scrape" >> "$candidate"
fi

promtool check config "$candidate"

backup="${config}.before-ai-agent.$(date -u +%Y%m%dT%H%M%SZ)"
cp --preserve=mode,ownership,timestamps "$config" "$backup"
cat "$candidate" > "$config"

if ! systemctl reload prometheus; then
    cp --preserve=mode,ownership,timestamps "$backup" "$config"
    systemctl reload prometheus
    echo "Prometheus reload failed; restored $backup" >&2
    exit 1
fi

echo "Prometheus agent monitoring installed; rollback file: $backup"
