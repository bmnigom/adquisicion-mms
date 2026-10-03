"""Identidad temporal, pérdidas por canal y límites del reloj de llegada."""
import unittest

import numpy as np

from core.imu_pairing import ImuPairer, PairingStatus
from core.sample_clock import reconstruct


class SignalTimingTests(unittest.TestCase):
    def test_native_indices_detect_one_and_two_lost_samples(self):
        for count in (1, 2):
            indices = np.delete(np.arange(400), np.s_[150:150 + count])
            arrivals = indices / 100 + 0.04
            t, lost = reconstruct(arrivals, 100, sequences=indices)
            self.assertEqual(lost.sum(), count)
            self.assertEqual(lost[150], count)
            self.assertAlmostEqual(t[-1], 3.99)

    def test_native_time_detects_small_loss_with_bursty_host(self):
        native = np.array([0, .01, .04, .05])
        _, lost = reconstruct([100, 100, 100, 100], 100, device_times=native)
        np.testing.assert_array_equal(lost, [0, 0, 2, 0])

    def test_host_latency_step_does_not_override_native_sequence(self):
        host = np.arange(400) / 100
        host[150:] += .2
        _, inferred = reconstruct(host, 100)
        _, native = reconstruct(host, 100, sequences=np.arange(400))
        self.assertGreater(inferred.sum(), 0)
        self.assertEqual(native.sum(), 0)

    def test_asymmetric_gyro_loss_preserves_native_identity(self):
        pairer = ImuPairer()
        out = []
        for i in range(30):
            out += pairer.add_acc((i, 0, 0), i, sequence=i)
            if not 9 <= i < 12:
                out += pairer.add_gyro((i, 0, 0), sequence=i)
        out += pairer.flush()
        self.assertEqual(len(out), 30)
        self.assertEqual([meta for _, _, meta, status in out if status == PairingStatus.FALLBACK], [9, 10, 11])
        self.assertTrue(all(acc[0] == gyro[0] for acc, gyro, _, status in out if status == PairingStatus.NATIVE))

    def test_native_gyro_can_arrive_before_first_acc(self):
        pairer = ImuPairer()
        self.assertEqual(pairer.add_gyro((7, 0, 0), device_time=.07), [])
        out = pairer.add_acc((7, 0, 0), "meta", device_time=.071)
        self.assertEqual(out[0][-1], PairingStatus.NATIVE)

    def test_no_identity_is_always_declared_estimated(self):
        pairer = ImuPairer()
        pairer.add_acc((1, 0, 0), None)
        out = pairer.add_gyro((1, 0, 0))
        self.assertTrue(bool(out[0][-1]))  # API histórica
        self.assertEqual(out[0][-1], PairingStatus.ESTIMATED)
        self.assertEqual(pairer.verified, 0)

    def test_resync_flushes_old_acc_instead_of_pairing_it_to_new_gyro(self):
        pairer = ImuPairer()
        pairer.add_acc((1, 0, 0), "old")
        out = pairer.add_acc((2, 0, 0), "new", resync=True)
        self.assertEqual(out[0][2:], ("old", PairingStatus.FALLBACK))
        out = pairer.add_gyro((2, 0, 0))
        self.assertEqual(out[0][2], "new")

    def test_invalid_native_identity_is_rejected(self):
        for kwargs in ({"device_times": [0, float("nan")]}, {"device_times": [1, 1]},
                       {"sequences": [4, 3]}, {"sequences": [0, 1.5]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                reconstruct([0, .01], 100, **kwargs)

    def test_absent_or_partial_native_metadata_uses_available_source(self):
        for metadata in ([None, None, None], ["", "", ""], [0, None, .04]):
            with self.subTest(metadata=metadata):
                t, lost = reconstruct([0, .01, .04], 100, device_times=metadata,
                                      sequences=[0, 1, 4])
                np.testing.assert_array_equal(lost, [0, 0, 2])
                np.testing.assert_allclose(t, [0, .01, .04])
        t, lost = reconstruct([0, .01, .02], 100, device_times=[None] * 3,
                              sequences=[None] * 3)
        np.testing.assert_array_equal(lost, [0, 0, 0])
        np.testing.assert_allclose(t, [0, .01, .02])


if __name__ == "__main__":
    unittest.main()
