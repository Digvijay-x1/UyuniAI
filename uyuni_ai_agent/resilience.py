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

"""Bounded retry scheduling and dependency circuit breakers."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class DependencyUnavailable(RuntimeError):
    """Raised when a dependency circuit rejects an operation."""

    def __init__(self, dependency: str, retry_after_seconds: float):
        self.dependency = dependency
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(
            f"{dependency} circuit is open; retry after "
            f"{self.retry_after_seconds:.1f}s"
        )


@dataclass(frozen=True)
class CircuitSnapshot:
    state: CircuitState
    consecutive_failures: int
    retry_after_seconds: float


class CircuitBreaker:
    """Small deterministic circuit breaker with one half-open probe."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be greater than 0")
        self.failure_threshold = int(failure_threshold)
        self.recovery_timeout_seconds = float(recovery_timeout_seconds)
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def snapshot(self) -> CircuitSnapshot:
        now = self._clock()
        state = self._effective_state(now)
        retry_after = 0.0
        if state is CircuitState.OPEN and self._opened_at is not None:
            retry_after = max(
                0.0,
                self.recovery_timeout_seconds - (now - self._opened_at),
            )
        return CircuitSnapshot(
            state=state,
            consecutive_failures=self._consecutive_failures,
            retry_after_seconds=retry_after,
        )

    def acquire(self) -> CircuitSnapshot:
        snapshot = self.snapshot
        if snapshot.state is CircuitState.OPEN:
            return snapshot
        if snapshot.state is CircuitState.HALF_OPEN:
            if self._probe_in_flight:
                return CircuitSnapshot(
                    CircuitState.OPEN,
                    snapshot.consecutive_failures,
                    self.recovery_timeout_seconds,
                )
            self._probe_in_flight = True
        return snapshot

    def record_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self._probe_in_flight = False
        self._consecutive_failures += 1
        if (
            self._state is CircuitState.HALF_OPEN
            or self._consecutive_failures >= self.failure_threshold
        ):
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()

    def _effective_state(self, now: float) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and now - self._opened_at >= self.recovery_timeout_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._probe_in_flight = False
        return self._state


class ExponentialBackoff:
    """Retry delays with a bounded symmetric jitter window."""

    def __init__(
        self,
        *,
        initial_seconds: float,
        maximum_seconds: float,
        jitter_ratio: float,
        random_source: Callable[[], float] = random.random,
    ):
        if initial_seconds <= 0:
            raise ValueError("initial_seconds must be greater than 0")
        if maximum_seconds < initial_seconds:
            raise ValueError("maximum_seconds must be >= initial_seconds")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")
        self.initial_seconds = float(initial_seconds)
        self.maximum_seconds = float(maximum_seconds)
        self.jitter_ratio = float(jitter_ratio)
        self._random = random_source

    def delay(self, failure_number: int) -> float:
        exponent = max(0, int(failure_number) - 1)
        base = min(
            self.maximum_seconds,
            self.initial_seconds * (2 ** exponent),
        )
        spread = base * self.jitter_ratio
        jittered = base - spread + (2 * spread * self._random())
        return min(self.maximum_seconds, max(0.0, jittered))


Observer = Callable[[str, str, float, CircuitSnapshot], None]


class DependencyManager:
    """Execute dependency operations through independent circuit breakers."""

    def __init__(
        self,
        dependencies: list[str],
        *,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        observer: Observer | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._clock = clock
        self._observer = observer
        self._breakers = {
            name: CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout_seconds=recovery_timeout_seconds,
                clock=clock,
            )
            for name in dependencies
        }

    def snapshot(self, dependency: str) -> CircuitSnapshot:
        return self._breaker(dependency).snapshot

    async def execute(
        self,
        dependency: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        timeout_seconds: float | None = None,
        success_predicate: Callable[[Any], bool] | None = None,
    ) -> Any:
        breaker = self._breaker(dependency)
        acquired = breaker.acquire()
        if acquired.state is CircuitState.OPEN:
            self._observe(dependency, "circuit_open", 0.0, acquired)
            raise DependencyUnavailable(
                dependency, acquired.retry_after_seconds
            )

        started = self._clock()
        try:
            pending = operation()
            if timeout_seconds is not None:
                result = await asyncio.wait_for(
                    pending, timeout=max(0.001, float(timeout_seconds))
                )
            else:
                result = await pending
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            breaker.record_failure()
            self._observe(
                dependency,
                "timeout",
                self._clock() - started,
                breaker.snapshot,
            )
            raise
        except Exception:
            breaker.record_failure()
            self._observe(
                dependency,
                "error",
                self._clock() - started,
                breaker.snapshot,
            )
            raise

        if success_predicate is not None and not success_predicate(result):
            breaker.record_failure()
            self._observe(
                dependency,
                "error",
                self._clock() - started,
                breaker.snapshot,
            )
            return result

        breaker.record_success()
        self._observe(
            dependency,
            "success",
            self._clock() - started,
            breaker.snapshot,
        )
        return result

    def record_external_failure(
        self, dependency: str, *, outcome: str = "error"
    ) -> None:
        breaker = self._breaker(dependency)
        breaker.record_failure()
        self._observe(dependency, outcome, 0.0, breaker.snapshot)

    def record_external_success(self, dependency: str) -> None:
        breaker = self._breaker(dependency)
        breaker.record_success()
        self._observe(dependency, "success", 0.0, breaker.snapshot)

    def _breaker(self, dependency: str) -> CircuitBreaker:
        try:
            return self._breakers[dependency]
        except KeyError as exc:
            raise ValueError(f"unknown dependency {dependency!r}") from exc

    def _observe(
        self,
        dependency: str,
        outcome: str,
        duration_seconds: float,
        snapshot: CircuitSnapshot,
    ) -> None:
        if self._observer is not None:
            self._observer(
                dependency,
                outcome,
                max(0.0, duration_seconds),
                snapshot,
            )
