"""Freshness and calibration tests, using only synthetic scalar samples."""
import unittest
from types import SimpleNamespace

from core.capture_requirements import CaptureRequirements


class CaptureRequirementTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.requirements = CaptureRequirements(clock=lambda: self.now)

    def sample(self, host_time=None, acc=1.0, gyro=0.0, valid=True):
        self.requirements.update(SimpleNamespace(
            host_time=self.now if host_time is None else host_time,
            acc_mag=acc, gyro_mag_dps=gyro, signal_valid=valid,
        ))

    def stable_window(self, **kwargs):
        for i in range(101):
            self.sample(9.0 + i / 100.0, **kwargs)

    def test_capture_requires_transmission_and_valid_samples(self):
        self.assertFalse(self.requirements.capture_check("transmitiendo").allowed)
        self.sample()
        self.assertFalse(self.requirements.capture_check("desconectado").allowed)
        self.assertTrue(self.requirements.capture_check("transmitiendo").allowed)

    def test_delayed_queued_samples_do_not_make_signal_fresh(self):
        self.sample(host_time=9.0)
        self.assertFalse(self.requirements.capture_check("transmitiendo").allowed)

    def test_invalid_sample_clears_previous_fresh_signal(self):
        self.stable_window()
        self.sample(valid=False)
        self.assertFalse(self.requirements.capture_check("transmitiendo").allowed)

    def test_nonfinite_sample_invalidates_readiness(self):
        self.sample()
        self.sample(acc=float("nan"))
        self.assertFalse(self.requirements.capture_check("transmitiendo").allowed)

    def test_calibration_requires_initialization_and_continuous_rest(self):
        self.sample()
        self.assertFalse(self.requirements.calibration_check("transmitiendo").allowed)
        self.stable_window()
        self.assertFalse(self.requirements.calibration_check("transmitiendo", initialized=False).allowed)
        self.assertTrue(self.requirements.calibration_check("transmitiendo", initialized=True).allowed)

    def test_calibration_rejects_motion_and_non_gravity_acceleration(self):
        self.stable_window(gyro=20.0)
        self.assertFalse(self.requirements.calibration_check("transmitiendo").allowed)
        self.requirements.reset()
        self.stable_window(acc=1.2)
        self.assertFalse(self.requirements.calibration_check("transmitiendo").allowed)

    def test_calibration_rejects_variance_even_within_gravity_gate(self):
        for i in range(101):
            self.sample(9.0 + i / 100.0, acc=1.08 if i % 2 else 0.92)
        self.assertFalse(self.requirements.calibration_check("transmitiendo").allowed)

    def test_burst_count_cannot_replace_elapsed_rest(self):
        for i in range(100):
            self.sample()
        self.assertFalse(self.requirements.calibration_check("transmitiendo").allowed)

    def test_disconnect_gap_resets_calibration_history(self):
        self.stable_window()
        self.now = 11.0
        self.sample()
        self.assertTrue(self.requirements.capture_check("transmitiendo").allowed)
        self.assertFalse(self.requirements.calibration_check("transmitiendo").allowed)

    def test_new_connection_reset_requires_new_samples(self):
        self.stable_window()
        self.requirements.reset()
        self.assertFalse(self.requirements.capture_check("transmitiendo").allowed)


if __name__ == "__main__":
    unittest.main()
