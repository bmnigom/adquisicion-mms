"""Regresiones de datos inválidos y calidad de la orientación, sin hardware."""
import math
import unittest

import numpy as np

from core import quality, simulation
from core.kinematics import Check, Metric, RepResult
from core.orientation import MahonyAHRS
from core.pipeline import SignalProcessor
from tests.test_algoritmos import run_detector


def sample(t=0.0, **changes):
    row = dict(time=t, host_time=t, acc_x=0.0, acc_y=0.0, acc_z=1.0,
               gyr_x=0.0, gyr_y=0.0, gyr_z=0.0, gyro_pairing="native")
    return {**row, **changes}


class SignalValidationTests(unittest.TestCase):
    def test_bad_sample_does_not_poison_orientation(self):
        for field in ("time", "host_time", "acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z"):
            for bad in (float("nan"), float("inf"), float("-inf"), "malformado"):
                with self.subTest(field=field, bad=bad):
                    proc = SignalProcessor(100.0, 16.0)
                    proc.process(sample())
                    before = proc.ahrs.q.copy()
                    result = proc.process(sample(0.01, **{field: bad}))
                    self.assertFalse(result.signal_valid)
                    np.testing.assert_array_equal(proc.ahrs.q, before)
                    good = proc.process(sample(0.02))
                    self.assertTrue(good.signal_valid)
                    self.assertTrue(np.isfinite(good.a_world_dyn).all())

    def test_nonfinite_metric_is_never_valid(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            result = RepResult("punch", 1.0, [Metric("v", "Velocidad", value, "m/s")],
                               [Check("Señal", "ok", "")])
            self.assertFalse(result.valid)

    def test_nonfinite_punch_sample_invalidates_attempt(self):
        raw = simulation.to_sensor_samples(simulation.punch_profile(), seed=5)
        bad = list(raw[112])
        bad[0] = float("nan")
        raw[112] = tuple(bad)
        result, _ = run_detector("punch", raw)
        self.assertIsNotNone(result)
        self.assertFalse(result.valid)
        self.assertTrue(any(c.status == "fail" for c in result.checks))

    def test_gyro_fallback_and_saturation_are_visible(self):
        proc = SignalProcessor(100, 16)
        fallback = proc.process(sample(gyro_emparejado=0, gyro_pairing="native"))
        self.assertEqual(fallback.gyro_pairing, "fallback")
        saturated = proc.process(sample(0.01, gyr_x=1990))
        self.assertTrue(saturated.gyro_saturated)
        rows = [sample(gyro_pairing="fallback"), sample(0.01, gyro_saturated=True)]
        q = quality.assess(rows, 100)
        self.assertEqual((q.gyro_fallbacks, q.gyro_saturated), (1, 1))
        self.assertEqual(quality.transmission_check(q, True, requires_gyro=True).status, "fail")

    def test_fifo_uncertainty_reaches_quality_check(self):
        rows = [sample(i / 100, gyro_pairing="estimated") for i in range(10)]
        q = quality.assess(rows, 100)
        self.assertEqual(q.gyro_uncertain, 10)
        check = quality.transmission_check(q, True, requires_gyro=True)
        self.assertEqual(check.status, "warn")
        self.assertIn("sin identidad nativa", check.detail)

    def test_raw_nan_is_detected_without_processed_flags(self):
        q = quality.assess([sample(acc_x=float("nan"))], 100)
        self.assertEqual(q.invalid, 1)
        self.assertEqual(quality.transmission_check(q, True).status, "fail")

    def test_ahrs_rejects_invalid_updates_without_mutation(self):
        ahrs = MahonyAHRS()
        with self.assertRaises(ValueError):
            ahrs.update([0, float("nan"), 0], [0, 0, 1])
        self.assertFalse(ahrs.initialized)
        np.testing.assert_array_equal(ahrs.q, [1, 0, 0, 0])

    def test_non_increasing_time_is_invalid(self):
        proc = SignalProcessor(100, 16)
        proc.process(sample(1.0))
        self.assertFalse(proc.process(sample(0.5)).signal_valid)

    def test_serialized_fallback_flags_are_not_treated_as_true(self):
        proc = SignalProcessor(100, 16)
        result = proc.process(sample(gyro_emparejado="0"))
        self.assertEqual(result.gyro_pairing, "fallback")
        q = quality.assess([sample(gyro_emparejado="0", gyro_saturated="0")], 100)
        self.assertEqual((q.gyro_fallbacks, q.gyro_saturated), (1, 0))

    def test_absent_optional_native_metadata_remains_valid(self):
        for absent in (None, ""):
            proc = SignalProcessor(100, 16)
            row = sample(device_time=absent, sequence=absent)
            self.assertTrue(proc.process(row).signal_valid)
            self.assertEqual(quality.assess([row], 100).invalid, 0)

    def test_empty_legacy_validity_column_is_unknown_not_invalid(self):
        row = sample(signal_valid="")
        self.assertTrue(SignalProcessor(100, 16).process(row).signal_valid)
        self.assertEqual(quality.assess([row], 100).invalid, 0)

    def test_punch_with_dynamic_tilt_matches_known_velocity(self):
        out_s, back_s = .2, .4
        world = [np.zeros(3)] * 100 + simulation.punch_profile(.5, out_s, back_s) + [np.zeros(3)] * 100
        initial = simulation._tilt_matrix(15, -10)
        raw = []
        for i, acceleration in enumerate(world):
            t, angle, omega = i / 100 - 1, 0.0, 0.0
            if 0 <= t < out_s + back_s:
                forward = t < out_s
                duration = out_s if forward else back_s
                u = t / duration if forward else (t - out_s) / duration
                fraction = 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5
                angle = math.radians(45) * (fraction if forward else 1 - fraction)
                omega = math.radians(45) / duration * (30 * u ** 2 - 60 * u ** 3 + 30 * u ** 4) * (1 if forward else -1)
            rotation = simulation._tilt_matrix(0, math.degrees(angle)) @ initial
            acc = rotation.T @ (acceleration / 9.81 + np.array([0, 0, 1]))
            gyro = rotation.T @ np.array([0, math.degrees(omega), 0])
            raw.append(tuple([*acc, *gyro]))
        result, _ = run_detector("punch", raw)
        self.assertIsNotNone(result)
        self.assertTrue(result.valid, result.checks)
        true_speed = simulation.punch_peak_speed(.5, out_s)
        self.assertAlmostEqual(result.metric("velocidad_pico_m_s").value, true_speed, delta=.1 * true_speed)


if __name__ == "__main__":
    unittest.main()
