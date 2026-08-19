# Evaluation

Evaluation verifies the analysis and safety contracts described in
[Architecture](architecture.md) and [Security](security.md). Changes to a
detector, inspection tool, deterministic pattern, prompt, model, or evidence
quality gate should update this catalog in the same pull request.

The catalog in `evaluation/scenarios.yaml` defines repeatable pass/fail
criteria for baseline, correlation, root-cause-chain, and adversarial cases.

The catalog currently covers isolated CPU pressure, service port conflict,
disk-filling crash loops, PostgreSQL blockers, memory swap thrashing, the
PostgreSQL-to-Apache cross-node chain, dependency outages, stale telemetry,
unrelated simultaneous alerts, and queue backpressure.

Each scenario declares:

- the injected fault;
- expected alerts and inspection tools;
- required root-cause and remediation concepts;
- forbidden generic or unsafe conclusions;
- minimum cited evidence and confidence;
- the score required to pass.

Run the unit and scoring checks with:

```bash
pytest -q -p no:cacheprovider
ruff check .
```

For live validation, retain these artifacts for each run:

1. injection and cleanup timestamps;
2. raw Prometheus alerts and samples;
3. the agent's bounded Salt evidence records;
4. the structured RCA before notification rendering;
5. the scenario score and each failed criterion;
6. recovery metrics and the resolved incident.

An alert alone does not make a scenario successful. The RCA
must name the causal component, cite fresh supporting records, avoid forbidden
claims such as a blind database restart, and recommend action at the cause.

Fault injection is environment-specific and is not included in this
repository. The catalog and unit tests validate the same reasoning and safety
contracts without depending on a particular infrastructure topology.
