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

"""Validated application settings.

The runtime still consumes dictionaries so this module can be introduced
without changing the deployment or the Prometheus/Salt/Alertmanager clients.
Validation happens once at startup, before any external connection is opened.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _HttpEndpoint(_StrictModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute http:// or https:// URL")
        return value


class PrometheusSettings(_HttpEndpoint):
    max_sample_age_seconds: float = Field(default=300, gt=0)


class SaltAPISettings(_HttpEndpoint):
    username: str = Field(min_length=1)
    password: str = ""
    eauth: str = Field(default="file", min_length=1)


class MinionSettings(_StrictModel):
    id: str = Field(min_length=1)
    instance: str = Field(min_length=1)
    apache_instance: str | None = None
    postgres_instance: str | None = None

    @field_validator("id", "instance", "apache_instance", "postgres_instance")
    @classmethod
    def strip_non_empty_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ThresholdBand(_StrictModel):
    warning: float = Field(ge=0)
    critical: float = Field(ge=0)

    @model_validator(mode="after")
    def critical_must_not_be_lower(self):
        if self.critical < self.warning:
            raise ValueError("critical threshold must be >= warning threshold")
        return self


class PercentThresholdBand(ThresholdBand):
    warning: float = Field(ge=0, le=100)
    critical: float = Field(ge=0, le=100)


class MemoryPressureSettings(_StrictModel):
    swap_activity_pages_per_second: ThresholdBand
    swap_usage_percent: PercentThresholdBand


class MemoryThresholdSettings(PercentThresholdBand):
    pressure: MemoryPressureSettings


class ApacheThresholdSettings(_StrictModel):
    busy_workers_percent: PercentThresholdBand
    requests_per_sec: ThresholdBand


class PostgresThresholdSettings(_StrictModel):
    active_connections_percent: PercentThresholdBand
    deadlocks_per_min: ThresholdBand
    blocked_transaction_seconds: ThresholdBand


class ThresholdSettings(_StrictModel):
    memory: MemoryThresholdSettings
    cpu: PercentThresholdBand
    disk: PercentThresholdBand
    apache: ApacheThresholdSettings
    postgres: PostgresThresholdSettings


class LLMSettings(_StrictModel):
    provider: Literal["huggingface", "google_genai", "openai", "tokenrouter"]
    model: str = Field(min_length=1)
    api_key: str | None = None


class LoggingSettings(_StrictModel):
    level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value: str) -> str:
        return str(value).upper()


class PollingSettings(_StrictModel):
    interval_seconds: int = Field(gt=0)


class ServiceMonitoringSettings(_StrictModel):
    enabled: bool = True
    ignored_units: list[str] = Field(default_factory=list)


class PostgresLockMonitoringSettings(_StrictModel):
    enabled: bool = True


class DeduplicationSettings(_StrictModel):
    cooldown_seconds: int = Field(ge=0)


class IncidentStoreSettings(_StrictModel):
    path: str = Field(
        default="/var/lib/uyuni-ai-agent/incidents.db", min_length=1
    )
    resolve_after_healthy_cycles: int = Field(default=2, ge=1)


class InvestigationQueueSettings(_StrictModel):
    max_pending: int = Field(default=50, ge=1)
    workers: int = Field(default=3, ge=1)
    max_job_age_seconds: float = Field(default=300, gt=0)
    shutdown_grace_seconds: float = Field(default=30, ge=0)


class ObservabilitySettings(_StrictModel):
    enabled: bool = True
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=9898, ge=1, le=65535)
    readiness_max_age_seconds: float = Field(default=180, gt=0)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ConcurrencySettings(_StrictModel):
    max_minions: int = Field(gt=0)
    max_salt_calls: int = Field(gt=0)
    max_llm_calls: int = Field(gt=0)


class DependencyEdge(_StrictModel):
    postgres_minion: str = Field(min_length=1)
    apache_minion: str = Field(min_length=1)


class DependencyCorrelationSettings(_StrictModel):
    grace_seconds: float = Field(default=90, ge=0)
    postgres_apache: list[DependencyEdge] = Field(default_factory=list)


class Settings(_StrictModel):
    prometheus: PrometheusSettings
    alertmanager: _HttpEndpoint
    salt_api: SaltAPISettings
    minions: list[MinionSettings] = Field(min_length=1)
    dependency_correlation: DependencyCorrelationSettings = Field(
        default_factory=DependencyCorrelationSettings
    )
    thresholds: ThresholdSettings
    llm: LLMSettings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    polling: PollingSettings
    service_monitoring: ServiceMonitoringSettings = Field(
        default_factory=ServiceMonitoringSettings
    )
    postgres_lock_monitoring: PostgresLockMonitoringSettings = Field(
        default_factory=PostgresLockMonitoringSettings
    )
    deduplication: DeduplicationSettings
    incident_store: IncidentStoreSettings = Field(
        default_factory=IncidentStoreSettings
    )
    investigation_queue: InvestigationQueueSettings = Field(
        default_factory=InvestigationQueueSettings
    )
    observability: ObservabilitySettings = Field(
        default_factory=ObservabilitySettings
    )
    concurrency: ConcurrencySettings

    @model_validator(mode="after")
    def validate_inventory_and_dependencies(self):
        by_id = {minion.id: minion for minion in self.minions}
        if len(by_id) != len(self.minions):
            raise ValueError("minion ids must be unique")

        seen_edges: set[tuple[str, str]] = set()
        for edge in self.dependency_correlation.postgres_apache:
            edge_key = (edge.postgres_minion, edge.apache_minion)
            if edge_key in seen_edges:
                raise ValueError(f"duplicate dependency edge: {edge_key}")
            seen_edges.add(edge_key)

            postgres_minion = by_id.get(edge.postgres_minion)
            apache_minion = by_id.get(edge.apache_minion)
            if postgres_minion is None:
                raise ValueError(
                    f"dependency references unknown PostgreSQL minion "
                    f"{edge.postgres_minion!r}"
                )
            if apache_minion is None:
                raise ValueError(
                    f"dependency references unknown Apache minion "
                    f"{edge.apache_minion!r}"
                )
            if postgres_minion.postgres_instance is None:
                raise ValueError(
                    f"PostgreSQL dependency minion {edge.postgres_minion!r} "
                    "has no postgres_instance"
                )
            if apache_minion.apache_instance is None:
                raise ValueError(
                    f"Apache dependency minion {edge.apache_minion!r} "
                    "has no apache_instance"
                )
        return self


def validate_config(config: object) -> dict:
    """Validate raw YAML data and return the existing dictionary interface."""
    settings = Settings.model_validate(config)
    return settings.model_dump(mode="python", exclude_none=True)
