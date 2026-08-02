#!/bin/sh
set -eu

config=/etc/prometheus/prometheus.yml
rule_source=/tmp/agent-self-alerts.yml
scrape_source=/tmp/prometheus-agent-scrape.yml
rule_target=/etc/prometheus/rules/agent-self-alerts.yml
candidate=$(mktemp)
with_rules=$(mktemp)
trap 'rm -f "$candidate" "$with_rules"' EXIT

test -r "$config"
test -r "$rule_source"
test -r "$scrape_source"

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
    tail -n +4 "$scrape_source" | sed 's/^  //' >> "$candidate"
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
