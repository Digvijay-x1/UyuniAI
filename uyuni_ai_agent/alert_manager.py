# Copyright 2026 Digvijay Rawat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import datetime
import logging

import httpx

logger = logging.getLogger(__name__)

# Ref: https://prometheus.io/docs/alerting/latest/alerts_api/
#      https://petstore.swagger.io/?url=https://raw.githubusercontent.com/prometheus/alertmanager/main/api/v2/openapi.yaml

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 0.5


def _rfc3339_now() -> str:
    """Return the current UTC time as an RFC3339 timestamp with a 'Z' suffix.

    AlertManager's v2 API expects RFC3339. The previous implementation appended
    a literal 'Z' to a timezone-naive ``isoformat()`` which produced a malformed
    value; here we build a proper UTC timestamp and replace the ``+00:00`` offset
    with ``Z``.
    """
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def build_alert_payload(analysis, *, severity, minion_id, metric_name):
    """Build the AlertManager v2 payload from a RootCauseAnalysis.

    Structured fields become individual annotations so notification templates
    can render them independently (root cause, evidence, remediation, ...),
    while ``description`` carries the full rendered text as a fallback for
    receivers that only read one field.

    Args:
        analysis: a RootCauseAnalysis instance (from react_agent.investigate).
        severity: raw threshold-derived severity (info/warning/critical).
        minion_id: the affected minion.
        metric_name: the metric that triggered the alert.
    """
    key_evidence = "\n".join(f"- {e}" for e in analysis.key_evidence)
    remediation = "\n".join(
        f"{i}. {s}" for i, s in enumerate(analysis.remediation, 1)
    )

    return {
        "labels": {
            "alertname": "AIAgentResponse",
            "severity": severity,
            "source": "ai-bot",
            "minion": minion_id,
            "metric": metric_name,
            "component": analysis.affected_component,
            "urgency": analysis.urgency.value,
        },
        "annotations": {
            "summary": analysis.summary,
            "root_cause": analysis.root_cause,
            "affected_component": analysis.affected_component,
            "key_evidence": key_evidence,
            "remediation": remediation,
            "urgency": analysis.urgency.value,
            "confidence": f"{analysis.confidence:.0%}",
            # Full human-readable block, for receivers that render only one field.
            "description": analysis.to_text(),
        },
        "startsAt": _rfc3339_now(),
    }


async def send_to_alertmanager(client, config, analysis, severity="info",
                               minion_id="", metric_name=""):
    """Send an enriched, structured alert to AlertManager.

    Retries transient failures (connection errors and 5xx responses) with
    exponential backoff. A 4xx response is not retried because it indicates a
    malformed payload that will not succeed on retry.

    Args:
        client: an httpx.AsyncClient used for the POST.
        config: the loaded settings dict (provides alertmanager.url).
        analysis: a RootCauseAnalysis instance.
        severity: alert severity (info, warning, critical).
        minion_id: the affected minion.
        metric_name: the metric that triggered the alert.
    """
    url = f"{config['alertmanager']['url']}/api/v2/alerts"
    payload = [build_alert_payload(
        analysis, severity=severity, minion_id=minion_id, metric_name=metric_name
    )]

    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            last_error = f"Connection failed: {e}"
            logger.warning(
                "AlertManager POST attempt %d/%d failed: %s",
                attempt, _MAX_RETRIES, e,
            )
        else:
            if response.status_code == 200:
                return "Success: alert routed through AlertManager."
            # 4xx: malformed/rejected -- retrying will not help.
            if 400 <= response.status_code < 500:
                return f"Error: {response.status_code} - {response.text}"
            # 5xx: server-side, transient -- retry.
            last_error = f"Error: {response.status_code} - {response.text}"
            logger.warning(
                "AlertManager POST attempt %d/%d returned %d",
                attempt, _MAX_RETRIES, response.status_code,
            )

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

    return last_error or "Error: failed to send alert after retries."
