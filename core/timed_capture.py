"""Cronómetro monotónico para pruebas con inicio y final definidos por el operador."""

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class TimedResult:
    duration_s: float
    sample_count: int
    ended_by: str


class TimedCapture:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._started_at: float | None = None

    def start(self) -> None:
        self._started_at = self._clock()

    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self._clock() - self._started_at)

    def finish(self, sample_count: int, ended_by: str = "manual") -> TimedResult:
        if self._started_at is None:
            raise RuntimeError("La captura no ha comenzado")
        duration = self.elapsed()
        self._started_at = None
        return TimedResult(duration, sample_count, ended_by)
