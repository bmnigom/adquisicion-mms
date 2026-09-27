"""Pruebas de los algoritmos con senales sinteticas de valor conocido.

Ejecutar desde la carpeta del proyecto:
    python -m tests.test_algoritmos
"""
import json
import math
import os
import random
import sys
import tempfile

import numpy as np

from core import config, storage
from core.imu_pairing import ImuPairer
from core.kinematics import Metric, RepDetector
from core.report import participant_summary
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
        # Tolerancia 1 cm: la simulacion redondea el vuelo a muestras enteras (hasta ±0,6 cm).
        ok &= check(f"Salto {h * 100:.0f} cm", abs(got - h * 100) < 1.0, f"medido={got:.1f} cm")

    raw = sim.to_sensor_samples(sim.jump_profile(0.30), seed=3)
    flight_idx = 100 + 25 + 35 + 10  # reposo 1 s + contramovimiento + impulso + 0,1 s de vuelo
    for n_lost in (5, 8):
        rep, _ = run_detector("jump", raw, drop=(flight_idx, flight_idx + n_lost))
        ok &= check(f"Salto con {n_lost} muestras perdidas en el vuelo se rechaza",
                    rep is not None and not rep.valid,
                    "; ".join(c.detail for c in rep.checks if c.status == "fail") if rep else "sin resultado")
    rep, _ = run_detector("jump", raw, stall=(flight_idx / RATE, 0.3))
    got = rep.metric("altura_salto_cm").value if rep and rep.valid else float("nan")
    ok &= check("Salto con PC bloqueado 300 ms (sin pérdida) se acepta", abs(got - 30) < 1.0,
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
    det.phase = "moving"
    ok &= check("Límite con movimiento en curso lo explica",
                "no quedó quieta" in det.timeout_result(20).checks[0].detail)

    ok &= test_pairing()
    ok &= test_storage_and_config()
    ok &= test_participant_text()

    print("\nTODAS LAS PRUEBAS PASARON" if ok else "\nHAY PRUEBAS FALLIDAS")
    return 0 if ok else 1


def test_pairing():
    ok = True
    # Paquetes de 3 muestras, giroscopio iniciado antes y llegando a veces antes, a veces despues.
    p = ImuPairer()
    out = p.add_gyro(("pre",) * 3)  # anterior a la primera aceleracion: se descarta
    for k in range(0, 30, 3):
        if k % 6 == 0:
            for i in range(k, k + 3):
                out += p.add_acc((i,) * 3, i)
            for i in range(k, k + 3):
                out += p.add_gyro((i,) * 3)
        else:
            for i in range(k, k + 3):
                out += p.add_gyro((i,) * 3)
            for i in range(k, k + 3):
                out += p.add_acc((i,) * 3, i)
    ok &= check("Giroscopio emparejado con su muestra",
                len(out) == 30 and all(acc[0] == gyro[0] and paired for acc, gyro, _, paired in out))
    # Giroscopio detenido: la aceleracion no queda retenida mas de MAX_WAIT muestras.
    p = ImuPairer()
    out = []
    for i in range(20):
        out += p.add_acc((i,) * 3, i)
    ok &= check("Sin giroscopio no se retiene la señal", len(out) == 20 - p.max_wait and p.fallbacks == len(out))
    return ok


def _use_temp_data_dir(tmp):
    storage.DATA_DIR = tmp
    storage.RESULTS_LOG = os.path.join(tmp, "resultados_ciclovia_v2.csv")
    storage.TIMED_RESULTS_LOG = os.path.join(tmp, "resultados_pruebas_funcionales.csv")
    storage.REFERENCE_ORIENTATION_FILE = os.path.join(tmp, "orientacion_referencia.json")
    storage.REPORTS_DIR = os.path.join(tmp, "reportes")


def test_storage_and_config():
    from core.timed_capture import TimedResult
    ok = True
    saved = {k: getattr(storage, k) for k in
             ("DATA_DIR", "RESULTS_LOG", "TIMED_RESULTS_LOG", "REFERENCE_ORIENTATION_FILE", "REPORTS_DIR")}
    with tempfile.TemporaryDirectory() as tmp:
        _use_temp_data_dir(tmp)
        try:
            ok &= check("ID de participante válido", storage.normalize_sub("7") == "07"
                        and storage.normalize_sub("AB12") == "AB12")
            ok &= check("ID con caracteres de ruta se rechaza",
                        all(storage.normalize_sub(t) is None for t in ("3/4", "a_b", "..", "c:", "")))

            # CSV bloqueado (Excel): la fila va al pendiente y se incorpora despues.
            real_write = storage._write_rows

            def locked(path, header, rows):
                if path == storage.TIMED_RESULTS_LOG:
                    raise PermissionError(13, "Permission denied")
                real_write(path, header, rows)

            storage._write_rows = locked
            warning = storage.append_timed_result("01", "tug", "01", TimedResult(10.5, 900, "manual"))
            storage._write_rows = real_write
            pending = storage._pending_path(storage.TIMED_RESULTS_LOG)
            ok &= check("CSV bloqueado: aviso y fila en pendiente", "Excel" in warning and os.path.exists(pending))
            ok &= check("Valor anterior se lee del pendiente",
                        storage.previous_value("01", "tug", timed=True) == 10.5)
            warning = storage.append_timed_result("01", "tug", "02", TimedResult(9.8, 900, "manual"))
            with open(storage.TIMED_RESULTS_LOG, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
            ok &= check("Pendiente incorporado al desbloquear",
                        warning == "" and len(lines) == 3 and not os.path.exists(pending), f"lineas={len(lines)}")
            with open(storage.TIMED_RESULTS_LOG, "rb") as f:
                ok &= check("CSV legible en Excel (BOM UTF-8)", f.read(3) == b"\xef\xbb\xbf")

            # Un intento sin muestras deja reporte: el siguiente no lo sobrescribe.
            storage.save_report("01", "jump", "01", "<p>sin datos</p>")
            ok &= check("Número de intento no se reutiliza", storage.next_run_number("01", "jump") == "02")

            # Archivos danados no impiden arrancar.
            with open(storage.REFERENCE_ORIENTATION_FILE, "w") as f:
                f.write("{no es json")
            ok &= check("Referencia dañada se ignora", storage.load_reference_orientation("Muñeca") is None)
            storage.save_reference_orientation("Muñeca", [1, 0, 0, 0])
            ok &= check("Referencia por ubicación", storage.load_reference_orientation("Muñeca") == [1, 0, 0, 0]
                        and storage.load_reference_orientation("Cintura") is None)
            with open(os.path.join(tmp, "configuracion.json"), "w") as f:
                json.dump(["no", "es", "un", "dict"], f)
            ok &= check("Configuración dañada usa valores por defecto",
                        config.load()["mac_address"] == config.DEFAULT_MAC)
        finally:
            for k, v in saved.items():
                setattr(storage, k, v)
    return ok


def test_participant_text():
    ok = True
    tug = [Metric("duration_s", "Tiempo", 13.2, "s")]
    text = participant_summary("tug", "ok", tug, 70)
    ok &= check("TUG ≥12 s en ≥65 años remite a profesional", "profesional de salud" in text and "No es un diagnóstico" in text)
    ok &= check("TUG sin edad no aplica umbral", "12 s" not in participant_summary("tug", "ok", tug, None))
    walk = [Metric("duration_s", "Tiempo", 5.0, "s"), Metric("velocidad_marcha", "Velocidad", 1.0, "m/s")]
    ok &= check("Marcha 1,0 m/s en ≥65 años sin alarma", "profesional" not in participant_summary("walk", "ok", walk, 70))
    ok &= check("Intento inválido no muestra valores",
                "13" not in participant_summary("tug", "fail", tug, 70))
    return ok


if __name__ == "__main__":
    sys.exit(main())
