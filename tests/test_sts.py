"""STS de velocidad variable: no confundir velocidad constante con reposo."""
import unittest

import numpy as np

from core import simulation
from tests.test_algoritmos import run_detector


class StsTests(unittest.TestCase):
    def test_slow_sts_finishes_after_real_ascent_with_correct_rise(self):
        for duration in (1.0, 1.5, 2.0, 2.5, 3.0):
            for noise in (0.0, .004):
                with self.subTest(duration=duration, noise=noise):
                    raw = simulation.to_sensor_samples(simulation.sts_profile(.4, duration),
                                                       noise_g=noise, seed=4)
                    result, _ = run_detector("sts", raw)
                    self.assertIsNotNone(result)
                    self.assertTrue(result.valid, result.checks)
                    self.assertGreater(result.timestamp, 1.0 + duration)
                    self.assertAlmostEqual(result.metric("desplazamiento_cm").value, 40, delta=3)

    def test_rest_noise_does_not_trigger_false_sts(self):
        for seed in (1, 4, 8):
            with self.subTest(seed=seed):
                raw = simulation.to_sensor_samples([], rest_before_s=8, rest_after_s=1, seed=seed)
                result, _ = run_detector("sts", raw)
                self.assertIsNone(result)

    def test_lost_data_during_slow_ascent_invalidates_result(self):
        raw = simulation.to_sensor_samples(simulation.sts_profile(.4, 2), seed=4)
        result, _ = run_detector("sts", raw, drop=(180, 186))
        self.assertIsNotNone(result)
        self.assertFalse(result.valid)

    def test_constant_velocity_plateau_does_not_end_ascent(self):
        profile = ([np.array([0, 0, .8])] * 50 + [np.zeros(3)] * 75
                   + [np.array([0, 0, -.8])] * 50)
        result, _ = run_detector("sts", simulation.to_sensor_samples(profile, noise_g=0, seed=4))
        self.assertIsNotNone(result)
        self.assertTrue(result.valid, result.checks)
        self.assertGreater(result.timestamp, 2.75)
        self.assertAlmostEqual(result.metric("desplazamiento_cm").value, 50, delta=3)


if __name__ == "__main__":
    unittest.main()
