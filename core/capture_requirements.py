"""Signal freshness and rest requirements shared by capture and calibration."""
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RequirementCheck:
    allowed: bool
    message: str = ""


class CaptureRequirements:
    def __init__(
        self, clock: Callable[[], float] = time.perf_counter, *,
        freshness_s: float = 0.5, rest_window_s: float = 1.0,
        min_rest_samples: int = 50, max_gyro_dps: float = 8.0,
        max_acc_std_g: float = 0.03, gravity_tolerance_g: float = 0.10,
    ):
        self._clock = clock
        self.freshness_s = freshness_s
        self.rest_window_s = rest_window_s
        self.min_rest_samples = min_rest_samples
        self.max_gyro_dps = max_gyro_dps
        self.max_acc_std_g = max_acc_std_g
        self.gravity_tolerance_g = gravity_tolerance_g
        self._samples: deque = deque()
        self._last_time: float | None = None

    def reset(self):
        self._samples.clear()
        self._last_time = None

    def update(self, sample):
        host_time = float(sample.host_time)
        acc = float(sample.acc_mag)
        gyro = float(sample.gyro_mag_dps)
        if (not getattr(sample, "signal_valid", True)
                or not all(math.isfinite(v) for v in (host_time, acc, gyro))):
            self.reset()
            return
        if (self._last_time is not None
                and (host_time < self._last_time or host_time - self._last_time > self.freshness_s)):
            self.reset()
        self._last_time = host_time
        self._samples.append((host_time, acc, gyro))
        while self._samples and host_time - self._samples[0][0] > self.rest_window_s:
            self._samples.popleft()

    def capture_check(self, status: str) -> RequirementCheck:
        if status != "transmitiendo":
            return RequirementCheck(False, "Espere a que el sensor esté conectado y transmitiendo.")
        if self._last_time is None:
            return RequirementCheck(False, "Todavía no hay muestras válidas del sensor.")
        age = self._clock() - self._last_time
        if age > self.freshness_s or age < -0.05:
            return RequirementCheck(False, "La señal no está actualizada. Compruebe el sensor y el Bluetooth.")
        return RequirementCheck(True)

    def calibration_check(self, status: str, initialized: bool = True) -> RequirementCheck:
        check = self.capture_check(status)
        if not check.allowed:
            return check
        if not initialized:
            return RequirementCheck(False, "Espere a que el sensor determine su orientación inicial.")
        if (len(self._samples) < self.min_rest_samples
                or self._samples[-1][0] - self._samples[0][0] < 0.8 * self.rest_window_s):
            return RequirementCheck(False, "Mantenga el sensor quieto durante un segundo antes de calibrar.")
        acc = [row[1] for row in self._samples]
        if (max(row[2] for row in self._samples) > self.max_gyro_dps
                or any(abs(value - 1.0) > self.gravity_tolerance_g for value in acc)
                or statistics.pstdev(acc) > self.max_acc_std_g):
            return RequirementCheck(False, "El sensor está en movimiento. Colóquelo y manténgalo quieto para calibrar.")
        return RequirementCheck(True)
