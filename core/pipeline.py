"""Procesamiento por muestra, compartido por la aplicacion y el reprocesado offline."""
import math
from dataclasses import dataclass

import numpy as np

from core.orientation import G, MahonyAHRS

SATURATION_FRACTION = 0.98


@dataclass
class ProcessedSample:
    t: float                 # tiempo de medicion (s); provisional hasta reconstruct()
    host_time: float         # hora de llegada al PC (s), para reconstruir perdidas
    dt: float                # intervalo real desde la muestra anterior (s)
    lost_before: int         # muestras perdidas justo antes de esta
    acc_g: tuple             # aceleracion medida (g, marco del sensor)
    gyro_dps: tuple
    acc_mag: float           # |a| en g
    a_world_dyn: np.ndarray  # aceleracion sin gravedad en el marco del mundo (m/s^2)
    a_vertical: float        # componente vertical de a_world_dyn (m/s^2, positivo = arriba)
    gyro_mag_dps: float
    saturated: bool
    roll: float
    pitch: float
    signal_valid: bool = True
    signal_error: str = ""
    gyro_pairing: str = "unknown"
    gyro_saturated: bool = False
    device_time: float | None = None
    sequence: int | None = None


class SignalProcessor:
    def __init__(self, rate_hz: float, acc_range_g: float, gyro_range_dps: float = 2000.0):
        if not all(math.isfinite(v) and v > 0 for v in (rate_hz, acc_range_g, gyro_range_dps)):
            raise ValueError("Frecuencia y rangos del sensor deben ser positivos y finitos.")
        self.rate_hz = rate_hz
        self.acc_range_g = acc_range_g
        self.gyro_range_dps = gyro_range_dps
        self.ahrs = MahonyAHRS()
        self._last_t: float | None = None

    def process(self, sample: dict) -> ProcessedSample:
        errors = []
        def number(key, default=None):
            try:
                value = float(sample[key] if key in sample else default)
            except (TypeError, ValueError, OverflowError):
                value = float("nan")
            if not math.isfinite(value):
                errors.append(key)
            return value

        def flag(value):
            return value.strip().lower() not in {"0", "false", "no", ""} if isinstance(value, str) else bool(value)

        # Legacy/optional CSV columns can be present but empty; treat them as unknown.
        if sample.get("signal_valid") not in (None, "") and not flag(sample["signal_valid"]):
            errors.append("signal_valid")

        t = number("time")
        if not math.isfinite(t):
            t = 0.0 if self._last_t is None else self._last_t + 1.0 / self.rate_hz
        elif self._last_t is not None and t <= self._last_t:
            errors.append("orden temporal")
            t = self._last_t + 1.0 / self.rate_hz
        dt = 1.0 / self.rate_hz if self._last_t is None else max(t - self._last_t, 1e-4)
        self._last_t = t
        host_time = number("host_time", t)
        if not math.isfinite(host_time):
            host_time = t
        acc = tuple(number("acc_" + axis) for axis in "xyz")
        gyro = tuple(number("gyr_" + axis) for axis in "xyz")
        lost = number("lost_before", 0)
        if not math.isfinite(lost) or lost < 0 or not lost.is_integer():
            errors.append("lost_before")
            lost = 0
        device_time = number("device_time") if sample.get("device_time") not in (None, "") else None
        sequence = number("sequence") if sample.get("sequence") not in (None, "") else None
        if sequence is not None and (not math.isfinite(sequence) or sequence < 0 or not sequence.is_integer()):
            errors.append("sequence")
            sequence = None
        if device_time is not None and not math.isfinite(device_time):
            device_time = None
        pairing = sample.get("gyro_pairing", "unknown")
        gyro_flag = sample.get("gyro_emparejado", 1)
        if isinstance(gyro_flag, str):
            gyro_flag = gyro_flag.strip().lower() not in {"0", "false", "no", ""}
        if not gyro_flag:
            pairing = "fallback"
        if pairing not in {"native", "estimated", "fallback", "unknown"}:
            pairing = "unknown"

        # Con muestras perdidas no se integra el giroscopio a ciegas sobre todo el hueco:
        # el valor retenido no representa el giro de ese intervalo.
        gyro_saturated = (any(abs(g) >= SATURATION_FRACTION * self.gyro_range_dps for g in gyro)
                          or flag(sample.get("gyro_saturated", sample.get("gyro_saturado", False))))
        if not errors:
            if pairing != "fallback" and not gyro_saturated:
                self.ahrs.update([math.radians(g) for g in gyro], acc, dt=min(dt, 0.05))
            a_world = self.ahrs.rotate_to_world(acc)
            a_world_dyn = (a_world - np.array([0.0, 0.0, 1.0])) * G
        else:
            # La muestra se conserva para invalidar el intento, sin contaminar el filtro.
            a_world_dyn = np.full(3, float("nan"))
        roll, pitch, _ = self.ahrs.euler_deg()
        limit = SATURATION_FRACTION * self.acc_range_g
        return ProcessedSample(
            t=t, host_time=host_time, dt=dt,
            lost_before=int(lost),
            acc_g=acc, gyro_dps=gyro,
            acc_mag=math.sqrt(sum(a * a for a in acc)),
            a_world_dyn=a_world_dyn, a_vertical=float(a_world_dyn[2]),
            gyro_mag_dps=math.sqrt(sum(g * g for g in gyro)),
            saturated=any(abs(a) >= limit for a in acc),
            roll=roll, pitch=pitch,
            signal_valid=not errors, signal_error=", ".join(dict.fromkeys(errors)),
            gyro_pairing=pairing,
            gyro_saturated=gyro_saturated,
            device_time=device_time, sequence=int(sequence) if sequence is not None else None,
        )
