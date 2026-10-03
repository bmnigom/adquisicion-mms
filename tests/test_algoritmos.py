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
import unittest
from contextlib import contextmanager
from unittest.mock import patch

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


class AlgorithmTests(unittest.TestCase):
    def assert_valid_rep(self, rep):
        self.assertIsNotNone(rep, "El detector no produjo un resultado")
        self.assertTrue(rep.valid, "; ".join(c.detail for c in rep.checks if c.status == "fail"))

    def metric_value(self, rep, key):
        self.assertIsNotNone(rep)
        metric = rep.metric(key)
        self.assertIsNotNone(metric, f"Falta la métrica {key}")
        return metric.value

    def test_bluetooth_bursts_do_not_create_false_losses(self):
        raw = sim.to_sensor_samples(sim.sts_profile(0.4), seed=1)
        _, stats = run_detector("sts", raw)
        self.assertEqual(stats.lost, 0)

    def test_orientation_initializes_from_first_gravity_vector(self):
        ahrs = MahonyAHRS()
        a = sim.to_sensor_samples([], roll_deg=30, pitch_deg=-20, noise_g=0, rest_before_s=0.01)[0][:3]
        ahrs.update([0, 0, 0], a)
        np.testing.assert_allclose(ahrs.rotate_to_world(a), [0, 0, 1], atol=1e-6)

    def test_placement_comparison_ignores_yaw(self):
        yaw90 = np.array([math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)])
        self.assertLess(tilt_angle_diff_deg([1, 0, 0, 0], yaw90), 1e-6)

    def test_jump_height_for_known_profiles(self):
        for height in (0.15, 0.30, 0.45):
            with self.subTest(height_cm=height * 100):
                raw = sim.to_sensor_samples(sim.jump_profile(height), seed=2)
                rep, _ = run_detector("jump", raw)
                self.assert_valid_rep(rep)
                # El vuelo se redondea a muestras enteras (hasta ±0,6 cm).
                self.assertLess(abs(self.metric_value(rep, "altura_salto_cm") - height * 100), 1.0)

    def test_jump_rejects_samples_lost_during_flight(self):
        raw = sim.to_sensor_samples(sim.jump_profile(0.30), seed=3)
        flight_idx = 100 + 25 + 35 + 10
        for n_lost in (5, 8):
            with self.subTest(lost_samples=n_lost):
                rep, _ = run_detector("jump", raw, drop=(flight_idx, flight_idx + n_lost))
                self.assertIsNotNone(rep)
                self.assertFalse(rep.valid)

    def test_jump_accepts_host_stall_without_sample_loss(self):
        raw = sim.to_sensor_samples(sim.jump_profile(0.30), seed=3)
        flight_idx = 100 + 25 + 35 + 10
        rep, _ = run_detector("jump", raw, stall=(flight_idx / RATE, 0.3))
        self.assert_valid_rep(rep)
        self.assertLess(abs(self.metric_value(rep, "altura_salto_cm") - 30), 1.0)

    def test_sts_displacement_and_power_for_known_profiles(self):
        for rise in (0.30, 0.45):
            with self.subTest(rise_cm=rise * 100):
                raw = sim.to_sensor_samples(sim.sts_profile(rise, 1.0), seed=4)
                rep, _ = run_detector("sts", raw, mass=70)
                self.assert_valid_rep(rep)
                displacement = self.metric_value(rep, "desplazamiento_cm")
                power = self.metric_value(rep, "potencia_pico_w")
                # Potencia física de referencia: max(m (a+g) v), perfil min-jerk.
                s = np.linspace(0, 1, 2000)
                velocity = rise * (30 * s ** 2 - 60 * s ** 3 + 30 * s ** 4)
                acceleration = rise * (60 * s - 180 * s ** 2 + 120 * s ** 3)
                expected_power = float((70 * (acceleration + 9.81) * velocity).max())
                self.assertLess(abs(displacement - rise * 100), 3)
                self.assertLess(abs(power - expected_power) / expected_power, 0.08)

    def test_punch_speed_matches_known_profile(self):
        raw = sim.to_sensor_samples(sim.punch_profile(0.5, 0.2), seed=5)
        rep, _ = run_detector("punch", raw)
        self.assert_valid_rep(rep)
        speed = self.metric_value(rep, "velocidad_pico_m_s")
        expected = sim.punch_peak_speed(0.5, 0.2)
        self.assertLess(abs(speed - expected) / expected, 0.1)

    def test_detector_does_not_measure_without_initial_rest(self):
        det = RepDetector("jump", 70, RATE)
        self.assertFalse(det.timeout_result(15).valid)

    def test_timeout_explains_unfinished_motion(self):
        det = RepDetector("jump", 70, RATE)
        det.phase = "moving"
        self.assertIn("no quedó quieta", det.timeout_result(20).checks[0].detail)


class PairingTests(unittest.TestCase):
    def test_fifo_preserves_order_across_alternating_bursts(self):
        pairer = ImuPairer()
        out = pairer.add_gyro(("pre",) * 3)
        for k in range(0, 30, 3):
            if k % 6 == 0:
                for i in range(k, k + 3):
                    out += pairer.add_acc((i,) * 3, i)
                for i in range(k, k + 3):
                    out += pairer.add_gyro((i,) * 3)
            else:
                for i in range(k, k + 3):
                    out += pairer.add_gyro((i,) * 3)
                for i in range(k, k + 3):
                    out += pairer.add_acc((i,) * 3, i)
        self.assertEqual(len(out), 30)
        for index, (acc, gyro, _, paired) in enumerate(out):
            with self.subTest(index=index):
                self.assertEqual(acc[0], gyro[0])
                self.assertTrue(paired)

    def test_missing_gyro_does_not_retain_acceleration_indefinitely(self):
        pairer = ImuPairer()
        out = []
        for i in range(20):
            out += pairer.add_acc((i,) * 3, i)
        self.assertEqual(len(out), 20 - pairer.max_wait)
        self.assertEqual(pairer.fallbacks, len(out))


@contextmanager
def temporary_data_dir(simulate=False):
    """Restore every storage selector, including simulation/config paths."""
    names = ("BASE_DATA_DIR", "DATA_SOURCE", "DATA_DIR", "RESULTS_LOG", "TIMED_RESULTS_LOG",
             "REFERENCE_ORIENTATION_FILE", "REPORTS_DIR")
    original = {name: getattr(storage, name) for name in names}
    with tempfile.TemporaryDirectory() as tmp, patch.multiple(storage, **original):
        storage.configure_storage(simulate, base_dir=tmp)
        yield tmp


class StorageAndConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(temporary_data_dir())

    def test_normalizes_valid_participant_ids(self):
        for supplied, expected in (("7", "07"), ("AB12", "AB12")):
            with self.subTest(supplied=supplied):
                self.assertEqual(storage.normalize_sub(supplied), expected)

    def test_rejects_ids_with_path_characters(self):
        for value in ("3/4", "a_b", "..", "c:", ""):
            with self.subTest(value=value):
                self.assertIsNone(storage.normalize_sub(value))

    def test_locked_csv_retains_previous_value_and_recovers_pending_rows(self):
        from core.timed_capture import TimedResult
        real_write = storage._write_rows
        def locked(path, header, rows):
            if path == storage.TIMED_RESULTS_LOG:
                raise PermissionError(13, "Permission denied")
            return real_write(path, header, rows)
        with patch.object(storage, "_write_rows", side_effect=locked):
            warning = storage.append_timed_result("01", "tug", "01", TimedResult(10.5, 900, "manual"))
        pending = storage._pending_path(storage.TIMED_RESULTS_LOG)
        self.assertIn("Excel", warning)
        self.assertTrue(os.path.exists(pending))
        self.assertEqual(storage.previous_value("01", "tug", timed=True), 10.5)
        warning = storage.append_timed_result("01", "tug", "02", TimedResult(9.8, 900, "manual"))
        with open(storage.TIMED_RESULTS_LOG, encoding="utf-8-sig") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(warning, "")
        self.assertEqual(len(lines), 3)
        self.assertFalse(os.path.exists(pending))
        with open(storage.TIMED_RESULTS_LOG, "rb") as handle:
            self.assertEqual(handle.read(3), b"\xef\xbb\xbf")

    def test_report_only_attempt_number_is_not_reused(self):
        storage.save_report("01", "jump", "01", "<p>sin datos</p>")
        self.assertEqual(storage.next_run_number("01", "jump"), "02")

    def test_damaged_reference_is_ignored_and_locations_are_independent(self):
        with open(storage.REFERENCE_ORIENTATION_FILE, "w", encoding="utf-8") as handle:
            handle.write("{no es json")
        self.assertIsNone(storage.load_reference_orientation("Muñeca"))
        storage.save_reference_orientation("Muñeca", [1, 0, 0, 0])
        self.assertEqual(storage.load_reference_orientation("Muñeca"), [1, 0, 0, 0])
        self.assertIsNone(storage.load_reference_orientation("Cintura"))

    def test_damaged_config_uses_defaults(self):
        with open(os.path.join(self.tmp, "configuracion.json"), "w", encoding="utf-8") as handle:
            json.dump(["no", "es", "un", "dict"], handle)
        self.assertEqual(config.load()["mac_address"], config.DEFAULT_MAC)

    def test_simulation_has_its_own_sensor_configuration(self):
        real_mac, simulated_mac = "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"
        config.save({"mac_address": real_mac})
        storage.configure_storage(True, base_dir=self.tmp)
        self.assertEqual(config.load()["mac_address"], config.DEFAULT_MAC)
        config.save({"mac_address": simulated_mac})
        self.assertEqual(config.load()["mac_address"], simulated_mac)
        storage.configure_storage(False)
        self.assertEqual(config.load()["mac_address"], real_mac)


class ParticipantTextTests(unittest.TestCase):
    def test_tug_threshold_for_older_adults_refers_to_a_professional(self):
        metrics = [Metric("duration_s", "Tiempo", 13.2, "s")]
        text = participant_summary("tug", "ok", metrics, 70)
        self.assertIn("profesional de salud", text)
        self.assertIn("No es un diagnóstico", text)

    def test_tug_without_age_does_not_apply_age_specific_threshold(self):
        metrics = [Metric("duration_s", "Tiempo", 13.2, "s")]
        self.assertNotIn("12 s", participant_summary("tug", "ok", metrics, None))

    def test_normal_walk_speed_has_no_alarm_for_older_adults(self):
        metrics = [Metric("duration_s", "Tiempo", 5.0, "s"), Metric("velocidad_marcha", "Velocidad", 1.0, "m/s")]
        self.assertNotIn("profesional", participant_summary("walk", "ok", metrics, 70))

    def test_invalid_attempt_does_not_show_metric_values(self):
        metrics = [Metric("duration_s", "Tiempo", 13.2, "s")]
        self.assertNotIn("13", participant_summary("tug", "fail", metrics, 70))


def main():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\nTODAS LAS PRUEBAS PASARON" if result.wasSuccessful() else "\nHAY PRUEBAS FALLIDAS")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
