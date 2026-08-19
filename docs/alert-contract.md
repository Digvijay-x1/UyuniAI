# Alert contract

The agent sends Alertmanager v2 alerts to:

```text
POST {alertmanager.url}/api/v2/alerts
```

The request body is a JSON array containing one firing or resolved alert. This
document is a compatibility contract for Alertmanager routes, templates, and
downstream notification consumers.

## Firing labels

Alertmanager identity is the complete label set.

| Label | Always present | Description |
|---|---:|---|
| `alertname` | Yes | Constant `AIAgentResponse` |
| `severity` | Yes | Detection severity: normally `info`, `warning`, or `critical` |
| `source` | Yes | Constant `ai-bot` |
| `minion` | Yes | Affected Salt minion ID |
| `metric` | Yes | Detector metric or incident-family name |
| `incident_id` | In normal runtime | Stable incident fingerprint |
| `service` | For service incidents | Validated systemd service name |
| `resource` | For resource incidents | Affected resource, such as a filesystem |

Do not route solely on `summary`, `root_cause`, or other annotations; they can
change after reinvestigation. Routes should use stable labels.

Changing, adding, or removing a label on an active incident creates a different
Alertmanager identity. The runtime resolves the previous stored label set
before emitting a changed one, but contract changes still require notification
template and lifecycle testing.

## Annotations

| Annotation | Format | Description |
|---|---|---|
| `summary` | String | One-line operator-facing title |
| `conclusion` | `confirmed` or `inconclusive` | Whether current evidence proves the root cause |
| `root_cause` | String | Evidence-cited cause or explanation of why analysis is inconclusive |
| `affected_component` | String | Specific component, or `unknown` |
| `supporting_evidence_ids` | Comma-separated IDs | Evidence ledger records supporting the conclusion |
| `key_evidence` | Markdown-like lines | Up to three human-readable cited facts |
| `remediation` | Numbered lines | Ordered, filtered operator actions |
| `urgency` | `Low`, `Medium`, `High`, or `Critical` | Post-investigation operator urgency |
| `confidence` | Percentage string | Structured confidence rendered without decimals |
| `description` | Multiline string | Complete fallback rendering for simple receivers |

Detection `severity` and RCA `urgency` are intentionally different. Severity
comes from telemetry thresholds and is suitable for routing. Urgency is the
investigation's operator-facing judgement and belongs in notification content.

## Example firing payload

```json
[
  {
    "labels": {
      "alertname": "AIAgentResponse",
      "severity": "critical",
      "source": "ai-bot",
      "minion": "database.example.com",
      "metric": "postgres_blocked_transaction",
      "incident_id": "27dc3a654f4a8894f7c9f57ddcb57982"
    },
    "annotations": {
      "summary": "PostgreSQL work is blocked by a long transaction",
      "conclusion": "confirmed",
      "root_cause": "A long-running transaction is blocking other sessions [E2].",
      "affected_component": "PostgreSQL",
      "supporting_evidence_ids": "E2",
      "key_evidence": "- [E2] one blocker has held a transaction for 94 seconds",
      "remediation": "1. Identify the owning application transaction.\n2. Have an operator end or commit the blocking transaction safely.",
      "urgency": "High",
      "confidence": "94%",
      "description": "*Conclusion:* confirmed\n\n*Root Cause:* A long-running transaction is blocking other sessions [E2]."
    },
    "startsAt": "2026-08-19T10:30:00Z"
  }
]
```

Values in this example are illustrative. Actual evidence is collected from the
target environment.

## Resolution

A resolution is a deep copy of the last successfully emitted firing payload
with an RFC3339 `endsAt` timestamp added:

```json
{
  "labels": {
    "alertname": "AIAgentResponse",
    "severity": "critical",
    "source": "ai-bot",
    "minion": "database.example.com",
    "metric": "postgres_blocked_transaction",
    "incident_id": "27dc3a654f4a8894f7c9f57ddcb57982"
  },
  "annotations": {
    "summary": "PostgreSQL work is blocked by a long transaction"
  },
  "startsAt": "2026-08-19T10:30:00Z",
  "endsAt": "2026-08-19T10:42:00Z"
}
```

All original annotations remain present in a real resolution. The abbreviated
example emphasizes identity behavior.

The agent resolves only after `incident_store.resolve_after_healthy_cycles`
consecutive observations no longer contain the anomaly. If the firing alert was
never delivered successfully, there is no stored firing identity to resolve.

## Delivery behavior

- HTTP 200 is treated as success.
- HTTP 4xx is treated as a non-retryable rejected payload for that attempt.
- Connection errors and HTTP 5xx responses are retried up to three times with
  bounded exponential delay.
- The surrounding runtime deadline still limits the whole Alertmanager
  operation.
- An incident is marked emitted only after successful delivery.
- Failed firing or resolution delivery remains visible in metrics and is
  retried by later lifecycle processing.

## Data handling

Alert annotations can contain bounded evidence summaries, but they must not
contain credentials, prompt text, arbitrary commands, raw SQL statement text,
or unrestricted process arguments. PostgreSQL evidence uses command types and
query identifiers instead of statement literals.

Notification receivers must still be treated as sensitive operational systems.
Restrict their audience and retention according to the organization’s incident
data policy.

## Template compatibility

The example notification template under `deploy/alertmanager/templates/`
consumes the structured fields above. Any change to label or annotation names
requires updates to:

1. `uyuni_ai_agent/alert_manager.py`;
2. alert payload and lifecycle tests;
3. Alertmanager routes and templates;
4. this document; and
5. `CHANGELOG.md` and upgrade notes.
