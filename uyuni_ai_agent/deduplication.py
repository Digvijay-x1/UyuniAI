"""In-memory anomaly deduplication for the polling loop."""

from __future__ import annotations

import time


class AnomalyDeduplicator:
    """Emit new/escalated anomalies and repeat persistent ones after cooldown.

    When an anomaly disappears, its state is cleared so a later recurrence is
    emitted immediately even if it happens inside the previous cooldown. A
    warning that becomes critical is also emitted immediately.
    """

    def __init__(self, cooldown_seconds=900):
        self.cooldown_seconds = max(0, int(cooldown_seconds))
        self._active_by_minion = {}
        self._active_severity = {}
        self._last_emitted = {}

    @staticmethod
    def _severity_rank(anomaly):
        value = getattr(anomaly.severity, "value", anomaly.severity)
        return {
            "info": 0,
            "warning": 1,
            "critical": 2,
        }.get(str(value).lower(), -1)

    def filter(self, minion_id, anomalies, now=None):
        now = time.monotonic() if now is None else float(now)
        current_keys = {anomaly.identity_key() for anomaly in anomalies}
        previous_keys = self._active_by_minion.get(minion_id, set())

        for resolved_key in previous_keys - current_keys:
            self._last_emitted.pop(resolved_key, None)
            self._active_severity.pop(resolved_key, None)

        emitted = []
        for anomaly in anomalies:
            key = anomaly.identity_key()
            last_emitted = self._last_emitted.get(key)
            is_new = key not in previous_keys
            current_severity = self._severity_rank(anomaly)
            previous_severity = self._active_severity.get(key, -1)
            severity_escalated = (
                not is_new and current_severity > previous_severity
            )
            cooldown_elapsed = (
                last_emitted is None
                or now - last_emitted >= self.cooldown_seconds
            )
            if is_new or severity_escalated or cooldown_elapsed:
                emitted.append(anomaly)
                self._last_emitted[key] = now
            self._active_severity[key] = current_severity

        self._active_by_minion[minion_id] = current_keys
        return emitted
