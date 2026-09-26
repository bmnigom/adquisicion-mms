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


class SignalProcessor:
    def __init__(self, rate_hz: float, acc_range_g: float):
        self.rate_hz = rate_hz
        self.acc_range_g = acc_range_g
        self.ahrs = MahonyAHRS()
        self._last_t: float | None = None

    def process(self, sample: dict) -> ProcessedSample:
        t = float(sample["time"])
        dt = 1.0 / self.rate_hz if self._last_t is None else max(t - self._last_t, 1e-4)
        self._last_t = t
        acc = (float(sample["acc_x"]), float(sample["acc_y"]), float(sample["acc_z"]))
        gyro = (float(sample["gyr_x"]), float(sample["gyr_y"]), float(sample["gyr_z"]))

        # Con muestras perdidas no se integra el giroscopio a ciegas sobre todo el hueco:
        # el valor retenido no representa el giro de ese intervalo.
        self.ahrs.update([math.radians(g) for g in gyro], acc, dt=min(dt, 0.05))
        a_world = self.ahrs.rotate_to_world(acc)
        a_world_dyn = (a_world - np.array([0.0, 0.0, 1.0])) * G
        roll, pitch, _ = self.ahrs.euler_deg()
        limit = SATURATION_FRACTION * self.acc_range_g
        return ProcessedSample(
            t=t, host_time=float(sample.get("host_time", t)), dt=dt,
            lost_before=int(sample.get("lost_before", 0)),
            acc_g=acc, gyro_dps=gyro,
            acc_mag=math.sqrt(sum(a * a for a in acc)),
            a_world_dyn=a_world_dyn, a_vertical=float(a_world_dyn[2]),
            gyro_mag_dps=math.sqrt(sum(g * g for g in gyro)),
            saturated=any(abs(a) >= limit for a in acc),
            roll=roll, pitch=pitch,
        )
