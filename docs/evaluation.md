# Evaluation

The evaluation catalog in `evaluation/scenarios.yaml` turns the mentor's
requirements into reviewable pass/fail criteria. It includes baseline,
correlation, root-cause-chain, and adversarial cases.

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

For a live evaluation, preserve these artifacts for each attempt:

1. injection and cleanup timestamps;
2. raw Prometheus alerts and samples;
3. the agent's bounded Salt evidence records;
4. the structured RCA before notification rendering;
5. the scenario score and each failed criterion;
6. recovery metrics and the resolved incident.

Do not score a test as successful merely because an alert appeared. The RCA
must name the causal component, cite fresh supporting records, avoid forbidden
claims such as a blind database restart, and recommend action at the cause.

Reproduction scripts remain local lab assets and are intentionally excluded
from Git. Unit tests and the catalog remain in the repository because they are
portable: they validate reasoning and safety contracts without requiring the
three-VM lab.
