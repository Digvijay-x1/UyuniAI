# Dependency circuit open

**Alert:** `UyuniAIAgentDependencyCircuitOpen`

## Symptoms

One of `salt`, `prometheus`, `llm`, or `alertmanager` has an open circuit after
repeated failures.

## Checks

```promql
uyuni_ai_agent_dependency_circuit_state{job="uyuni-ai-agent",state="open"}
uyuni_ai_agent_dependency_up{job="uyuni-ai-agent"}
uyuni_ai_agent_dependency_operations_total{job="uyuni-ai-agent"}
```

```bash
podman logs --since 15m ai-agent
```

Check the dependency from the agent host using an approved health endpoint or
client. For Salt, inspect the login response and port 9080 reachability. For
Prometheus and Alertmanager, check their service health and endpoint override.
For the LLM, check provider status, model name, quota, and API key validity.

## Safe actions

- Correct endpoint, certificate, credential, quota, or network policy issues.
- Allow the configured recovery timeout to elapse so the circuit can probe.
- Restart only after correcting a local configuration or credential problem.

## Recovery verification

The circuit state returns to `closed`, dependency operations succeed, and the
related readiness, delivery, or poll alerts resolve.

## Escalate when

The dependency is healthy from other clients but fails only from the agent
network namespace or identity.

## Do not

Do not remove circuit breakers or shorten recovery delays to force traffic into
a failing dependency.
