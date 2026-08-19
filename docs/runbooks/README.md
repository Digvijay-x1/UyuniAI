# Runbooks

These runbooks are for the self-monitoring alerts installed by
`deploy/monitoring/install-agent-monitoring.sh`. They assume access to the
Uyuni host, the monitoring host, Podman, systemd, and the relevant dependency
owners.

| Alert | Runbook |
|---|---|
| `UyuniAIAgentTargetDown` | [Agent target down](agent-target-down.md) |
| `UyuniAIAgentNotReady` | [Agent not ready](agent-not-ready.md) |
| `UyuniAIAgentPollStalled` | [Polling stalled](agent-poll-stalled.md) |
| `UyuniAIAgentDependencyCircuitOpen` | [Dependency circuit open](dependency-circuit-open.md) |
| `UyuniAIAgentTimeouts` | [Operation timeouts](operation-timeouts.md) |
| `UyuniAIAgentQueueBacklog` | [Queue backlog](queue-backlog.md) |
| `UyuniAIAgentQueueSaturated` | [Queue saturated](queue-saturated.md) |
| `UyuniAIAgentAlertDeliveryFailures` | [Alert delivery failures](alert-delivery-failures.md) |

Use these procedures to restore observability and delivery. They do not
authorize changing the underlying Uyuni, database, or application systems
without the normal change and incident process.
