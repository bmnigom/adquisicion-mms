"""Senales sinteticas fisicamente coherentes (salto, STS, golpe) para simulacion y pruebas.

Cada movimiento se define por su cinematica en el marco del mundo; la lectura
del acelerometro es a/g + gravedad, rotada al marco del sensor segun una
inclinacion fija. Asi las pruebas conocen el valor verdadero (altura,
ascenso, velocidad) y pueden comprobar el algoritmo.
"""
import math
import random

import numpy as np

from core.orientation import G


def _tilt_matrix(roll_deg: float, pitch_deg: float) -> np.ndarray:
    r, p = math.radians(roll_deg), math.radians(pitch_deg)
    rx = np.array([[1, 0, 0], [0, math.cos(r), -math.sin(r)], [0, math.sin(r), math.cos(r)]])
    ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0], [-math.sin(p), 0, math.cos(p)]])
    return ry @ rx  # sensor -> mundo


def _rest(n):
    return [np.zeros(3)] * n


def jump_profile(height_m: float, rate_hz: float = 100.0) -> list[np.ndarray]:
    """Aceleracion vertical del mundo (m/s^2, sin gravedad) de un salto con contramovimiento."""
    dt = 1.0 / rate_hz
    v0 = math.sqrt(2 * G * height_m)
    unweight_t, push_t, land_t = 0.25, 0.35, 0.15
    a_push = (v0 + 0.6 * G * unweight_t) / push_t
    flight_t = 2 * v0 / G
    out = []
    for dur, a in ((unweight_t, -0.6 * G), (push_t, a_push), (flight_t, -G), (land_t, v0 / land_t)):
        n = int(round(dur / dt))
        out += [np.array([0.0, 0.0, a])] * n
    return out


def sts_profile(rise_m: float, duration_s: float = 1.2, rate_hz: float = 100.0) -> list[np.ndarray]:
    """Ascenso de minimo tiron (min-jerk)."""
    n = int(round(duration_s * rate_hz))
    out = []
    for i in range(n):
        s = i / n
        a = rise_m / duration_s ** 2 * (60 * s - 180 * s ** 2 + 120 * s ** 3)
        out.append(np.array([0.0, 0.0, a]))
    return out


def punch_profile(reach_m: float = 0.5, out_s: float = 0.2, back_s: float = 0.4,
                  rate_hz: float = 100.0) -> list[np.ndarray]:
    """Golpe horizontal (eje X del mundo): ida rapida y regreso, ambos min-jerk."""
    out = []
    for dist, dur in ((reach_m, out_s), (-reach_m, back_s)):
        n = int(round(dur * rate_hz))
        for i in range(n):
            s = i / n
            a = dist / dur ** 2 * (60 * s - 180 * s ** 2 + 120 * s ** 3)
            out.append(np.array([a, 0.0, 0.0]))
    return out


def punch_peak_speed(reach_m: float = 0.5, out_s: float = 0.2) -> float:
    return 1.875 * reach_m / out_s


def to_sensor_samples(world_acc: list[np.ndarray], roll_deg=15.0, pitch_deg=-10.0,
                      noise_g=0.004, acc_range_g=16.0, rest_before_s=1.0, rest_after_s=1.0,
                      rate_hz=100.0, seed=None) -> list[tuple]:
    """Convierte aceleraciones del mundo en lecturas (acc g, gyro dps) del sensor."""
    rng = random.Random(seed)
    r_sw = _tilt_matrix(roll_deg, pitch_deg).T  # mundo -> sensor
    seq = _rest(int(rest_before_s * rate_hz)) + list(world_acc) + _rest(int(rest_after_s * rate_hz))
    samples = []
    for a in seq:
        specific = a / G + np.array([0.0, 0.0, 1.0])
        acc = r_sw @ specific
        acc = [max(-acc_range_g, min(acc_range_g, v + rng.gauss(0, noise_g))) for v in acc]
        gyro = [rng.gauss(0, 0.3) for _ in range(3)]
        samples.append((*acc, *gyro))
    return samples
