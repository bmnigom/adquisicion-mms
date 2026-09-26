"""Pruebas de los algoritmos con senales sinteticas de valor conocido.

Ejecutar desde la carpeta del proyecto:
    python -m tests.test_algoritmos
"""
import math
import random
import sys

import numpy as np

from core.kinematics import RepDetector
from core.orientation import MahonyAHRS, tilt_angle_diff_deg
from core.pipeline import SignalProcessor
from core.sample_clock import SampleClock
from core import simulation as sim

RATE = 100.0


def run_detector(task, raw, mass=70.0, drop=None, stall=None, rng_seed=1):
    """Pasa las lecturas por reloj -> procesamiento -> detector, simulando rafagas Bluetooth.

    drop=(i0, i1): el sensor pierde esas muestras. stall=(t0, dur): el PC no procesa
    nada durante dur segundos (las muestras se acumulan y llegan juntas, sin perderse).
    """
    rng = random.Random(rng_seed)
    clock = SampleClock(RATE)
    proc = SignalProcessor(RATE, 16.0)
    det = RepDetector(task, mass, RATE)
    result = None
    burst_arrival = 0.0
    last_arrival = 0.0
    for i, (ax, ay, az, gx, gy, gz) in enumerate(raw):
        # El sensor mide en i/RATE; el PC recibe cada 6 muestras con 5-40 ms de latencia.
        if i % 6 == 0:
            burst_arrival = (i + 5) / RATE + rng.uniform(0.005, 0.04)
        if drop and drop[0] <= i < drop[1]:
            continue
        arrival = burst_arrival + rng.uniform(0, 0.002)
        if stall and stall[0] <= arrival < stall[0] + stall[1]:
            arrival = stall[0] + stall[1] + rng.uniform(0, 0.003)
        arrival = last_arrival = max(arrival, last_arrival)
        t, lost = clock.stamp(arrival)
        s = proc.process({"time": t, "host_time": arrival, "lost_before": lost,
                          "acc_x": ax, "acc_y": ay, "acc_z": az,
                          "gyr_x": gx, "gyr_y": gy, "gyr_z": gz})
        _, rep = det.update(s)
        if rep is not None:
            result = rep
            break
    return result, clock.stats


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("OK   " if cond else "FALLA") + f"  {name}  {detail}")
    return cond


def main():
    ok = True

    # Reloj: rafagas sin perdidas no deben contarse como perdidas
    raw = sim.to_sensor_samples(sim.sts_profile(0.4), seed=1)
    _, stats = run_detector("sts", raw)
    ok &= check("Reloj sin falsas pérdidas", stats.lost == 0, f"perdidas={stats.lost}")

    # Orientacion inicial correcta desde el primer vector de gravedad
    ahrs = MahonyAHRS()
    a = sim.to_sensor_samples([], roll_deg=30, pitch_deg=-20, noise_g=0, rest_before_s=0.01)[0][:3]
    ahrs.update([0, 0, 0], a)
    ok &= check("Inicialización por gravedad", np.allclose(ahrs.rotate_to_world(a), [0, 0, 1], atol=1e-6))

    # Colocacion: girar alrededor de la vertical no cambia la inclinacion
    yaw90 = np.array([math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)])
    ok &= check("Colocación ignora el rumbo", tilt_angle_diff_deg([1, 0, 0, 0], yaw90) < 1e-6)

    for h in (0.15, 0.30, 0.45):
        raw = sim.to_sensor_samples(sim.jump_profile(h), seed=2)
        rep, _ = run_detector("jump", raw)
        got = rep.metric("altura_salto_cm").value if rep and rep.valid else float("nan")
        ok &= check(f"Salto {h * 100:.0f} cm", abs(got - h * 100) < 2.0, f"medido={got:.1f} cm")

    raw = sim.to_sensor_samples(sim.jump_profile(0.30), seed=3)
    flight_idx = 100 + 25 + 35 + 10  # reposo 1 s + contramovimiento + impulso + 0,1 s de vuelo
    for n_lost in (5, 8):
        rep, _ = run_detector("jump", raw, drop=(flight_idx, flight_idx + n_lost))
        ok &= check(f"Salto con {n_lost} muestras perdidas en el vuelo se rechaza",
                    rep is not None and not rep.valid,
                    "; ".join(c.detail for c in rep.checks if c.status == "fail") if rep else "sin resultado")
    rep, _ = run_detector("jump", raw, stall=(flight_idx / RATE, 0.3))
    got = rep.metric("altura_salto_cm").value if rep and rep.valid else float("nan")
    ok &= check("Salto con PC bloqueado 300 ms (sin pérdida) se acepta", abs(got - 30) < 2.0,
                f"medido={got:.1f} cm")

    for rise in (0.30, 0.45):
        raw = sim.to_sensor_samples(sim.sts_profile(rise, 1.0), seed=4)
        rep, _ = run_detector("sts", raw, mass=70)
        d = rep.metric("desplazamiento_cm").value if rep else float("nan")
        p = rep.metric("potencia_pico_w").value if rep else float("nan")
        # Potencia teorica: max(m (a+g) v) del perfil min-jerk
        T, n = 1.0, 2000
        s = np.linspace(0, 1, n)
        v = rise / T * (30 * s ** 2 - 60 * s ** 3 + 30 * s ** 4)
        acc = rise / T ** 2 * (60 * s - 180 * s ** 2 + 120 * s ** 3)
        p_true = float((70 * (acc + 9.81) * v).max())
        ok &= check(f"STS ascenso {rise * 100:.0f} cm", rep and rep.valid and abs(d - rise * 100) < 3,
                    f"medido={d:.1f} cm")
        ok &= check(f"STS potencia ({p_true:.0f} W teórica)", rep and abs(p - p_true) / p_true < 0.08,
                    f"medido={p:.0f} W")

    raw = sim.to_sensor_samples(sim.punch_profile(0.5, 0.2), seed=5)
    rep, _ = run_detector("punch", raw)
    v_true = sim.punch_peak_speed(0.5, 0.2)
    v = rep.metric("velocidad_pico_m_s").value if rep else float("nan")
    ok &= check(f"Golpe velocidad ({v_true:.2f} m/s teórica)", rep and rep.valid and abs(v - v_true) / v_true < 0.1,
                f"medido={v:.2f} m/s")

    # Sin reposo previo no se arma el detector
    det = RepDetector("jump", 70, RATE)
    ok &= check("Sin reposo previo no mide", det.timeout_result(15).valid is False)

    print("\nTODAS LAS PRUEBAS PASARON" if ok else "\nHAY PRUEBAS FALLIDAS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
